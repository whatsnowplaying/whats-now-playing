#!/usr/bin/env python3
''' Twitch OAuth2 authentication handler '''

import asyncio
import logging
from typing import Any

import requests

import nowplaying.config
import nowplaying.oauth2
from nowplaying.twitch.constants import (OAUTH_HOST, API_HOST, BROADCASTER_SCOPE_STRINGS,
                                         CHAT_BOT_SCOPE_STRINGS)


class TwitchOAuth2(nowplaying.oauth2.OAuth2Client):
    ''' Handle Twitch OAuth 2.1 authentication flow with PKCE '''

    def __init__(self, config: nowplaying.config.ConfigFile | None = None) -> None:
        service_config: nowplaying.oauth2.ServiceConfig = {
            'oauth_host': OAUTH_HOST,
            'api_host': API_HOST,
            'config_prefix': 'twitchbot',
            'default_scopes': BROADCASTER_SCOPE_STRINGS
        }
        super().__init__(config, service_config)

    def _get_additional_auth_params(self) -> dict[str, str]:
        ''' Add Twitch-specific authorization parameters '''
        return {'force_verify': 'false'}

    def get_oauth_status(self) -> dict[str, Any]:
        ''' Get current OAuth authentication status for both broadcaster and chat tokens '''
        # Check stored tokens
        access_token, refresh_token = self.get_stored_tokens()
        chat_token = self.config.cparser.value('twitchbot/chattoken')

        # Validate tokens
        broadcaster_valid = bool(self.validate_token_sync(access_token, return_username=False))
        chat_valid = bool(self.validate_token_sync(chat_token, return_username=False))

        # Get usernames
        broadcaster_username = None
        chat_username = None
        if broadcaster_valid and access_token:
            broadcaster_username = self.validate_token_sync(access_token, return_username=True)
        if chat_valid and chat_token:
            chat_username = self.validate_token_sync(chat_token, return_username=True)

        # Determine status text
        if broadcaster_valid and chat_valid:
            status_text = 'Broadcaster + Chat Bot authenticated'
        elif broadcaster_valid:
            status_text = 'Broadcaster authenticated (handles chat too)'
        elif chat_valid:
            status_text = 'Chat Bot authenticated (no broadcaster)'
        elif access_token:
            # Token is expired - check if we can refresh
            if refresh_token:
                status_text = 'Refreshing expired broadcaster token...'
            else:
                status_text = 'Broadcaster token expired - re-authentication needed'
        else:
            status_text = 'Not authenticated'

        return {
            'broadcaster_valid': broadcaster_valid,
            'chat_valid': chat_valid,
            'broadcaster_username': broadcaster_username,
            'chat_username': chat_username,
            'status_text': status_text,
            'has_refresh_token': bool(refresh_token)
        }

    def get_auth_url(self, token_type: str = 'broadcaster') -> str | None:
        ''' Generate OAuth authentication URL for specified token type '''
        # Validate configuration
        if not self.client_id or not self.client_secret:
            logging.error('OAuth2 configuration incomplete')
            return None

        # Set appropriate redirect URI based on token type
        port = self.config.cparser.value('webserver/port', type=int) or 8899
        if token_type == 'chat':
            self.redirect_uri = f'http://localhost:{port}/twitchchatredirect'
        else:
            self.redirect_uri = f'http://localhost:{port}/twitchredirect'

        try:
            # Generate the auth URL with appropriate scopes
            if token_type == 'chat':
                return self.get_authorization_url(CHAT_BOT_SCOPE_STRINGS)
            return self.get_authorization_url()  # Uses broadcaster scopes by default
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error('Failed to generate %s auth URL: %s', token_type, error)
            return None

    def clear_all_authentication(self) -> None:
        ''' Clear all stored authentication tokens (OAuth2 and chat) '''
        self.clear_stored_tokens()
        # Also clear chat tokens
        self.config.cparser.remove('twitchbot/chattoken')
        self.config.cparser.remove('twitchbot/chatrefreshtoken')
        self.config.save()
        logging.info('Cleared Twitch OAuth2 and chat authentication')

    def get_redirect_uri(self, token_type: str = 'broadcaster') -> str:
        ''' Get the redirect URI for the specified token type '''
        port = self.config.cparser.value('webserver/port', type=int) or 8899
        if token_type == 'chat':
            return f'http://localhost:{port}/twitchchatredirect'
        return f'http://localhost:{port}/twitchredirect'

    @staticmethod
    def validate_token_sync(  # pylint: disable=too-many-return-statements
                            token: str | None,
                            return_username: bool = False) -> str | bool | None:
        ''' Synchronously validate Twitch OAuth token

        Args:
            token: The OAuth token to validate
            return_username: If True, return username on success; if False, return boolean

        Returns:
            - If return_username=True: username string on success, None on failure
            - If return_username=False: True on success, False on failure
        '''
        if not token:
            return None if return_username else False

        url = 'https://id.twitch.tv/oauth2/validate'
        headers = {'Authorization': f'OAuth {token}'}

        try:
            req = requests.get(url, headers=headers, timeout=10)
        except Exception as error:  #pylint: disable=broad-except
            logging.error('Twitch token validation check failed: %s', error)
            return None if return_username else False

        if req.status_code != 200:
            if req.status_code == 401:
                logging.debug('Twitch token is invalid/expired')
            else:
                logging.warning('Twitch token validation returned status %s', req.status_code)
            return None if return_username else False

        try:
            response_data = req.json()

            # Check if token is valid (has required fields)
            if response_data.get('client_id') and response_data.get('login'):
                if return_username:
                    return response_data.get('login')
                return True

            logging.debug('Twitch token is invalid - missing required fields')
            return None if return_username else False
        except Exception as error:  #pylint: disable=broad-except
            logging.error('Twitch token validation/bad json: %s', error)
            return None if return_username else False


async def main() -> None:
    ''' Example usage of TwitchOAuth2 '''
    # Initialize with config (will read twitchbot/clientid, twitchbot/secret from config)
    oauth = TwitchOAuth2()

    # Check if configuration is present
    if not oauth.client_id:
        print("Error: twitchbot/clientid not configured")
        return
    if not oauth.client_secret:
        print("Error: twitchbot/secret not configured")
        return

    # Set redirect URI dynamically (required for authorization)
    oauth.redirect_uri = 'http://localhost:8899/twitchredirect'

    # Step 1: Open browser for authorization
    if oauth.open_browser_for_auth():
        print("Please authorize the application and check the redirect URI "
              "for the authorization code.")
        print("The redirect URI should be:", oauth.redirect_uri)

        # In a real application, you would capture the authorization code from the redirect
        # For this example, we'll just print the auth URL
        auth_url = oauth.get_authorization_url()
        print(f"Authorization URL: {auth_url}")
    else:
        print("Failed to open browser for authorization")


if __name__ == "__main__":
    asyncio.run(main())
