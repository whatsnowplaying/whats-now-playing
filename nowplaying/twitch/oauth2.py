#!/usr/bin/env python3
''' Twitch OAuth2 authentication handler '''

import asyncio
import base64
import hashlib
import logging
import secrets
import urllib.parse
import webbrowser
from typing import Any

import aiohttp

import nowplaying.config
from nowplaying.twitch.constants import OAUTH_HOST, API_HOST, BROADCASTER_SCOPE_STRINGS


class TwitchOAuth2:  # pylint: disable=too-many-instance-attributes
    ''' Handle Twitch OAuth 2.1 authentication flow with PKCE '''

    def __init__(self,
                 config: nowplaying.config.ConfigFile | None = None) -> None:
        self.config = config or nowplaying.config.ConfigFile()
        self.client_id: str = self.config.cparser.value('twitchbot/clientid')
        self.client_secret: str = self.config.cparser.value('twitchbot/secret')
        # Redirect URI is set dynamically by the calling code, not stored in config
        self.redirect_uri: str = None

        # PKCE parameters
        self.code_verifier: str | None = None
        self.code_challenge: str | None = None
        self.state: str | None = None

        # Tokens
        self.access_token: str | None = None
        self.refresh_token: str | None = None

    def _generate_pkce_parameters(self) -> None:
        ''' Generate PKCE code verifier and challenge '''
        # Generate code verifier (43-128 characters, URL-safe)
        self.code_verifier = secrets.token_urlsafe(43)

        # Generate code challenge (SHA256 hash of verifier, base64url encoded)
        challenge_bytes = hashlib.sha256(self.code_verifier.encode('utf-8')).digest()
        self.code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')

        # Generate state parameter for CSRF protection
        self.state = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')

        # Store PKCE parameters temporarily in config for callback handler
        if self.config:
            self.config.cparser.setValue('twitchbot/temp_code_verifier', self.code_verifier)
            self.config.cparser.setValue('twitchbot/temp_state', self.state)
            self.config.save()

    def get_authorization_url(self, scopes: list[str] | None = None) -> str:
        ''' Generate the authorization URL for user consent '''
        if not self.client_id:
            raise ValueError("Client ID is required")
        if not self.redirect_uri:
            raise ValueError("Redirect URI is required")

        if scopes is None:
            scopes = BROADCASTER_SCOPE_STRINGS

        self._generate_pkce_parameters()

        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'state': self.state,
            'scope': ' '.join(scopes),
            'code_challenge': self.code_challenge,
            'code_challenge_method': 'S256',
            'force_verify': 'false'
        }

        query_string = urllib.parse.urlencode(params)
        auth_url = f"{OAUTH_HOST}/oauth2/authorize?{query_string}"

        logging.info('Generated Twitch OAuth2 authorization URL')
        return auth_url

    def open_browser_for_auth(self, scopes: list[str] | None = None) -> bool:
        ''' Open browser to initiate OAuth2 flow '''
        auth_url = self.get_authorization_url(scopes)

        try:
            webbrowser.open(auth_url)
            logging.info('Opened browser for Twitch OAuth2 authentication')
            return True
        except OSError as error:
            logging.error('Failed to open browser for Twitch OAuth2: %s', error)
            return False

    async def exchange_code_for_token(self,
                                      authorization_code: str,
                                      received_state: str | None = None) -> dict[str, Any]:
        ''' Exchange authorization code for access token '''
        # Load PKCE parameters from config if not already set (for callback handler)
        if not self.code_verifier and self.config:
            self.code_verifier = self.config.cparser.value('twitchbot/temp_code_verifier')
            # State may have already been invalidated by callback handler for security
            if not self.state:
                self.state = self.config.cparser.value('twitchbot/temp_state')

        if not self.code_verifier:
            self.cleanup_temp_pkce_params()
            raise ValueError(
                "Code verifier not available. This can happen if:\n"
                "1. get_authorization_url() was not called before this method\n"
                "2. The application was restarted between authorization and token exchange\n"
                "3. The configuration was cleared or corrupted\n"
                "4. Multiple OAuth flows are running simultaneously\n"
                "To resolve: Generate a new authorization URL and restart the OAuth flow.")

        # Enforce state parameter presence for robust CSRF protection
        if not received_state:
            self.cleanup_temp_pkce_params()
            raise ValueError("State parameter is required for CSRF protection.")

        # Validate state parameter if we have a stored state to compare against
        if self.state and received_state != self.state:
            self.cleanup_temp_pkce_params()
            raise ValueError("State parameter mismatch. Possible CSRF attack.")

        token_data = {
            'grant_type': 'authorization_code',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': authorization_code,
            'redirect_uri': self.redirect_uri,
            'code_verifier': self.code_verifier
        }

        logging.debug('Twitch token exchange using redirect_uri: %s', self.redirect_uri)

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{OAUTH_HOST}/oauth2/token",
                                        data=token_data,
                                        headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        token_response: dict[str, Any] = await response.json()

                        self.access_token = token_response.get('access_token')
                        self.refresh_token = token_response.get('refresh_token')

                        logging.debug('Extracted tokens from response: '
                                     'access_token=%s, refresh_token=%s',
                                     'present' if self.access_token else 'missing',
                                     'present' if self.refresh_token else 'missing')

                        # Clean up temporary PKCE parameters
                        self.cleanup_temp_pkce_params()

                        logging.info('Successfully obtained Twitch OAuth2 tokens')
                        return token_response
                    error_text = await response.text()
                    logging.error('Failed to exchange code for token: %s - %s', response.status,
                                  error_text)
                    # Clean up temporary PKCE parameters on failure
                    self.cleanup_temp_pkce_params()
                    raise ValueError(f"Token exchange failed: {response.status} - {error_text}")
        except Exception as error:
            # Clean up temporary PKCE parameters if OAuth flow is interrupted
            if not isinstance(error, ValueError):
                # Don't re-cleanup if it's a ValueError we raised above
                self.cleanup_temp_pkce_params()
            raise

    async def refresh_access_token(self, refresh_token: str | None = None) -> dict[str, Any]:
        ''' Refresh the access token using refresh token '''
        if not refresh_token:
            refresh_token = (self.refresh_token or
                             self.config.cparser.value('twitchbot/refreshtoken'))

        if not refresh_token:
            raise ValueError("Refresh token is required")

        token_data = {
            'grant_type': 'refresh_token',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': refresh_token
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{OAUTH_HOST}/oauth2/token",
                                    data=token_data,
                                    headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    token_response: dict[str, Any] = await response.json()

                    self.access_token = token_response.get('access_token')
                    new_refresh_token = token_response.get('refresh_token')

                    if new_refresh_token:
                        self.refresh_token = new_refresh_token

                    # Note: Caller is responsible for saving tokens to config
                    logging.info('Successfully refreshed Twitch OAuth2 tokens')
                    return token_response
                error_text = await response.text()
                logging.error('Failed to refresh token: %s - %s', response.status, error_text)
                raise ValueError(f"Token refresh failed: {response.status} - {error_text}")

    async def revoke_token(self, token: str | None = None) -> None:
        ''' Revoke an access or refresh token '''
        if not token:
            token = self.access_token or self.config.cparser.value('twitchbot/accesstoken')

        if not token:
            logging.warning("No token to revoke")
            return

        revoke_data = {
            'client_id': self.client_id,
            'token': token
        }

        headers = {'Content-Type': 'application/x-www-form-urlencoded'}

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{OAUTH_HOST}/oauth2/revoke",
                                    data=revoke_data,
                                    headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    logging.info('Successfully revoked Twitch OAuth2 token')

                    # Clear tokens from config
                    if self.config:
                        self.config.cparser.remove('twitchbot/accesstoken')
                        self.config.cparser.remove('twitchbot/refreshtoken')
                        self.config.save()

                    self.access_token = None
                    self.refresh_token = None
                else:
                    error_text = await response.text()
                    logging.error('Failed to revoke token: %s - %s', response.status, error_text)

    async def validate_token(self, token: str | None = None) -> dict[str, Any] | None:
        ''' Validate an access token and return user info '''
        if not token:
            token = self.access_token or self.config.cparser.value('twitchbot/accesstoken')

        if not token:
            logging.warning("No token to validate")
            return None

        headers = {'Authorization': f'OAuth {token}'}

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{OAUTH_HOST}/oauth2/validate",
                                   headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    validation_response = await response.json()
                    logging.debug('Token validation successful')
                    return validation_response

                logging.debug('Token validation failed: %s', response.status)
                return None

    async def get_user_info(self, token: str | None = None) -> dict[str, Any] | None:
        ''' Get current user information '''
        if not token:
            token = self.access_token or self.config.cparser.value('twitchbot/accesstoken')

        if not token:
            logging.warning("No token available for user info")
            return None

        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': self.client_id
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_HOST}/users",
                                   headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    user_response = await response.json()
                    users = user_response.get('data', [])
                    if users:
                        logging.debug('User info retrieved successfully')
                        return users[0]

                logging.debug('Failed to get user info: %s', response.status)
                return None

    def get_stored_tokens(self) -> tuple[str | None, str | None]:
        ''' Get tokens from config storage '''
        if not self.config:
            return None, None

        # Refresh config from disk to get latest saved tokens
        self.config.get()
        access_token = self.config.cparser.value('twitchbot/accesstoken')
        refresh_token = self.config.cparser.value('twitchbot/refreshtoken')

        return access_token, refresh_token

    def cleanup_temp_pkce_params(self) -> None:
        '''Remove temporary PKCE parameters from config to prevent stale data.'''
        if self.config:
            self.config.cparser.remove('twitchbot/temp_code_verifier')
            self.config.cparser.remove('twitchbot/temp_state')
            self.config.save()
            self.config.cparser.sync()  # Ensure cross-process visibility
            logging.debug('Cleaned up temporary PKCE parameters')

    def clear_stored_tokens(self) -> None:
        ''' Clear tokens from config storage '''
        if self.config:
            self.config.cparser.remove('twitchbot/accesstoken')
            self.config.cparser.remove('twitchbot/refreshtoken')
            self.config.save()

        self.access_token = None
        self.refresh_token = None


async def main() -> None:
    ''' Example usage of TwitchOAuth2 '''
    # Initialize with config (will read twitchbot/clientid, twitchbot/secret,
    # twitchbot/redirecturi from config)
    oauth = TwitchOAuth2()

    # Check if configuration is present
    if not oauth.client_id:
        print("Error: twitchbot/clientid not configured")
        return
    if not oauth.client_secret:
        print("Error: twitchbot/secret not configured")
        return
    if not oauth.redirect_uri:
        print("Error: twitchbot/redirecturi not configured")
        return

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
