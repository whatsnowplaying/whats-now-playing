#!/usr/bin/env python3
''' twitch utils '''

import asyncio
import logging
import traceback
import socket

import aiohttp
import requests

from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
from twitchAPI.types import AuthScope, InvalidRefreshTokenException
from twitchAPI.oauth import UserAuthenticator, validate_token

import nowplaying.utils

# USER_SCOPE = [
#     AuthScope.CHANNEL_READ_REDEMPTIONS, AuthScope.CHANNEL_MANAGE_REDEMPTIONS, AuthScope.CHAT_READ,
#     AuthScope.CHAT_EDIT
# ]

USER_SCOPE = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]


async def get_user_image(twitch, loginname):
    ''' ask twitch for the user profile image '''
    image = None
    try:
        user = await first(twitch.get_users(logins=[loginname]))
        if not user:
            return None
        async with aiohttp.ClientSession() as session:
            async with session.get(user.profile_image_url, timeout=5) as resp:
                image = nowplaying.utils.image2png(await resp.read())
    except Exception as error:  #pylint: disable=broad-except
        logging.error(error)
    return image


def qtsafe_validate_token(token):
    ''' get valid and get the display name for a token '''
    url = 'https://id.twitch.tv/oauth2/validate'
    headers = {'Authorization': f'OAuth {token}'}

    try:
        req = requests.get(url, headers=headers, timeout=5)
    except Exception as error:  #pylint: disable=broad-except
        logging.error('Twitch Token validation check failed:%s', error)
        return None
    try:
        valid = req.json()
    except Exception as error:  #pylint: disable=broad-except
        logging.error('Twitch Token validation/bad json:%s', error)
        return None

    if valid.get('status') == 401:
        logging.debug('Twitch token is invalid')
        return None
    return valid.get('login')


class TwitchLogin:
    ''' manage the global twitch login for clientid/secret '''
    TWITCH = None
    TWITCH_LOCK = asyncio.Lock()

    def __init__(self, config):
        self.config = config
        self.timeout = aiohttp.ClientTimeout(total=60)

    async def attempt_user_auth(self, token, refresh_token):
        ''' try user auth '''
        if not token or not refresh_token:
            return False

        valid = await validate_token(token)
        if valid.get('status') == 401:
            return False

        if not TwitchLogin.TWITCH:
            return False

        try:
            await TwitchLogin.TWITCH.set_user_authentication(token, USER_SCOPE, refresh_token)
            TwitchLogin.TWITCH.user_auth_refresh_callback = self.save_refreshed_tokens
            await TwitchLogin.TWITCH.refresh_used_token()
        except Exception as error:  #pylint: disable=broad-except
            logging.error(error)
            return False
        return True

    async def api_login(self):
        ''' authenticate with the configured clientid/secret '''

        if TwitchLogin.TWITCH:
            return TwitchLogin.TWITCH

        logging.debug('entering lock')
        async with TwitchLogin.TWITCH_LOCK:
            try:
                if self.config.cparser.value('twitchbot/clientid') and self.config.cparser.value(
                        'twitchbot/secret'):
                    TwitchLogin.TWITCH = await Twitch(
                        self.config.cparser.value('twitchbot/clientid'),
                        self.config.cparser.value('twitchbot/secret'),
                        session_timeout=self.timeout)

                    token = self.config.cparser.value('twitchbot/oldusertoken')
                    refresh_token = self.config.cparser.value('twitchbot/oldrefreshtoken')

                    if not await self.attempt_user_auth(token, refresh_token):
                        auth = UserAuthenticator(TwitchLogin.TWITCH, USER_SCOPE, force_verify=False)
                        token, refresh_token = await auth.authenticate()

                        await self.attempt_user_auth(token, refresh_token)

                    self.config.cparser.setValue('twitchbot/oldusertoken', token)
                    self.config.cparser.setValue('twitchbot/oldrefreshtoken', refresh_token)
            except (aiohttp.client_exceptions.ClientConnectorError, socket.gaierror) as error:
                logging.error(error)
            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                return None
        logging.debug('exiting lock')
        return TwitchLogin.TWITCH

    async def save_refreshed_tokens(self, usertoken, refreshtoken):
        ''' every time token is updated, save it '''
        self.config.cparser.setValue('twitchbot/oldusertoken', usertoken)
        self.config.cparser.setValue('twitchbot/oldrefreshtoken', refreshtoken)
        self.config.save()
        logging.debug('Twitch tokens refreshed and saved')

    async def api_logout(self):
        ''' log out of the global twitch login '''
        if not TwitchLogin.TWITCH:
            return

        try:
            async with TwitchLogin.TWITCH_LOCK:
                await TwitchLogin.TWITCH.refresh_used_token()
                await TwitchLogin.TWITCH.close()
            TwitchLogin.TWITCH = None
            logging.debug('TWITCH shutdown')
        except InvalidRefreshTokenException:
            logging.debug('refresh token is invalid, removing')
            self.config.cparser.remove('twitchbot/oldrefreshtoken')
            self.config.save()
        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)

    async def cache_token_del(self):
        ''' logout and delete the old tokens '''
        await self.api_logout()
        self.config.cparser.remove('twitchbot/oldusertoken')
        self.config.cparser.remove('twitchbot/oldrefreshtoken')
        self.config.cparser.sync()
        logging.debug('Broken twitch config. Removing any cached API tokens.')
