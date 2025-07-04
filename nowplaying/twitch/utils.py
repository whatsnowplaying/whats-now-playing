#!/usr/bin/env python3
''' twitch utils '''

import asyncio
import logging

import aiohttp
from twitchAPI.twitch import Twitch

import nowplaying.twitch.oauth2
import nowplaying.utils
from nowplaying.twitch.constants import BROADCASTER_AUTH_SCOPES, BROADCASTER_SCOPE_STRINGS


async def get_user_image(oauth: 'nowplaying.twitch.oauth2.TwitchOAuth2',
                         loginname: str) -> bytes | None:
    ''' ask twitch for the user profile image '''
    image = None
    try:
        # Get user info using the OAuth2 client
        headers = {'Authorization': f'Bearer {oauth.access_token}', 'Client-Id': oauth.client_id}

        async with aiohttp.ClientSession() as session:
            # Get user data
            async with session.get(f'{oauth.api_host}/users?login={loginname}',
                                   headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    user_data = await resp.json()
                    if users := user_data.get('data', []):
                        if profile_image_url := users[0].get('profile_image_url'):
                            # Download profile image
                            async with session.get(
                                    profile_image_url,
                                    timeout=aiohttp.ClientTimeout(total=10)) as img_resp:
                                if img_resp.status == 200:
                                    raw_image = await img_resp.read()
                                    image = nowplaying.utils.image2png(raw_image)
                                    logging.debug('Downloaded profile image for user: %s',
                                                  loginname)
                                else:
                                    logging.warning('Failed to download profile image: %s',
                                                    img_resp.status)
                        else:
                            logging.debug('No profile image URL for user: %s', loginname)
                    else:
                        logging.warning('User not found: %s', loginname)
                else:
                    logging.warning('Failed to get user info: %s', resp.status)
    except Exception as error:  # pylint: disable=broad-except
        logging.error('Error getting user image for %s: %s', loginname, error)

    return image


async def async_validate_token(oauth_client: 'nowplaying.twitch.oauth2.TwitchOAuth2',
                               token: str | None = None) -> str | None:
    ''' Async version of token validation using OAuth2 client '''
    try:
        validation_response = await oauth_client.validate_token(token)
        if validation_response:
            return validation_response.get('login')
    except Exception as error:  #pylint: disable=broad-except
        logging.error('Async token validation failed: %s', error)
    return None


class TwitchLogin:
    ''' manage the global twitch login using OAuth2 '''
    OAUTH_CLIENT = None
    OAUTH_LOCK = asyncio.Lock()

    def __init__(self, config: 'nowplaying.config.ConfigFile'):
        self.config = config

    async def get_oauth_client(self):
        ''' Get or create OAuth2 client '''
        if TwitchLogin.OAUTH_CLIENT:
            return TwitchLogin.OAUTH_CLIENT

        async with TwitchLogin.OAUTH_LOCK:
            if not TwitchLogin.OAUTH_CLIENT:
                TwitchLogin.OAUTH_CLIENT = nowplaying.twitch.oauth2.TwitchOAuth2(self.config)
            return TwitchLogin.OAUTH_CLIENT

    async def attempt_token_refresh(self):
        ''' Try to refresh existing tokens '''
        oauth_client = await self.get_oauth_client()

        try:
            # Check if we have stored tokens
            access_token, refresh_token = oauth_client.get_stored_tokens()
            logging.debug('Retrieved stored tokens: access_token=%s, refresh_token=%s',
                          'present' if access_token else 'missing',
                          'present' if refresh_token else 'missing')

            if access_token:
                # Validate current token
                logging.debug('Validating stored access token')
                validation = await oauth_client.validate_token(access_token)
                if validation:
                    oauth_client.access_token = access_token
                    oauth_client.refresh_token = refresh_token
                    logging.debug('Existing Twitch token is valid')
                    return True
                logging.debug('Stored access token is invalid')

            if refresh_token:
                # Try to refresh the token
                logging.debug('Attempting to refresh token using refresh_token')
                token_response = await oauth_client.refresh_access_token(refresh_token)

                # Save the refreshed tokens
                new_access_token = token_response.get('access_token')
                new_refresh_token = token_response.get('refresh_token')
                if new_access_token:
                    self.config.cparser.setValue('twitchbot/accesstoken', new_access_token)
                    if new_refresh_token:
                        self.config.cparser.setValue('twitchbot/refreshtoken', new_refresh_token)
                    self.config.save()
                logging.debug('Twitch token refreshed successfully')
                return True
            logging.debug('No refresh_token available')

        except Exception as error:  #pylint: disable=broad-except
            logging.error('Token refresh failed: %s', error)

        return False

    async def initiate_oauth_flow(self):
        ''' Start OAuth flow by opening browser '''
        oauth_client = await self.get_oauth_client()

        if not oauth_client.client_id or not oauth_client.client_secret:
            logging.error('Twitch client ID or secret not configured')
            return False

        if not oauth_client.redirect_uri:
            # Set default redirect URI if not configured
            port = self.config.cparser.value('webserver/port', type=int) or 8899
            oauth_client.redirect_uri = f'http://localhost:{port}/twitchredirect'
            self.config.cparser.setValue('twitchbot/redirecturi', oauth_client.redirect_uri)
            self.config.save()

        return oauth_client.open_browser_for_auth(BROADCASTER_SCOPE_STRINGS)

    async def api_login(self):
        ''' authenticate with OAuth2 and return TwitchAPI Twitch object '''
        # Try to refresh existing tokens first
        if await self.attempt_token_refresh():
            oauth_client = TwitchLogin.OAUTH_CLIENT

            # Create TwitchAPI Twitch object using our OAuth2 tokens
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                twitch = await Twitch(oauth_client.client_id,
                                      oauth_client.client_secret,
                                      authenticate_app=False,
                                      session_timeout=timeout)

                await twitch.set_user_authentication(token=oauth_client.access_token,
                                                     refresh_token=oauth_client.refresh_token,
                                                     scope=BROADCASTER_AUTH_SCOPES,
                                                     validate=False)

                # Set up callback to save automatically refreshed tokens
                twitch.user_auth_refresh_callback = self.save_refreshed_tokens

                return twitch

            except Exception as error:  #pylint: disable=broad-except
                logging.error('Failed to create TwitchAPI object: %s', error)
                return None

        # If no valid tokens, need to initiate OAuth flow
        logging.info('No valid Twitch tokens found. OAuth flow required.')
        return None

    async def save_refreshed_tokens(self, access_token: str, refresh_token: str):
        ''' Save automatically refreshed tokens from TwitchAPI library '''
        oauth_client = await self.get_oauth_client()

        # Update our OAuth client with the new tokens
        oauth_client.access_token = access_token
        oauth_client.refresh_token = refresh_token

        # Save to config using our OAuth2 storage keys
        self.config.cparser.setValue('twitchbot/accesstoken', access_token)
        self.config.cparser.setValue('twitchbot/refreshtoken', refresh_token)
        self.config.save()

        logging.debug('Twitch tokens automatically refreshed and saved')

    @staticmethod
    async def api_logout():
        ''' log out and cleanup '''
        if TwitchLogin.OAUTH_CLIENT:
            try:
                await TwitchLogin.OAUTH_CLIENT.revoke_token()
                logging.debug('Twitch logout completed')
            except Exception as error:  #pylint: disable=broad-except
                logging.error('Logout error: %s', error)
            finally:
                TwitchLogin.OAUTH_CLIENT = None

    async def cache_token_del(self):
        ''' logout and delete cached tokens '''
        await self.api_logout()
        if TwitchLogin.OAUTH_CLIENT:
            TwitchLogin.OAUTH_CLIENT.clear_stored_tokens()

        # Clean up old token storage keys
        self.config.cparser.remove('twitchbot/oldusertoken')
        self.config.cparser.remove('twitchbot/oldrefreshtoken')
        self.config.cparser.remove('twitchbot/accesstoken')
        self.config.cparser.remove('twitchbot/refreshtoken')
        self.config.save()
        logging.debug('Twitch tokens cleared')
