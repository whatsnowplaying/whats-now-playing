#!/usr/bin/env python3
''' Kick OAuth2 authentication handler '''

import asyncio
import logging
import urllib.parse
from typing import Any

import aiohttp

import nowplaying.config
import nowplaying.oauth2


class KickOAuth2(nowplaying.oauth2.OAuth2Client):
    ''' Handle Kick.com OAuth 2.1 authentication flow with PKCE '''

    OAUTH_HOST = 'https://id.kick.com'
    SCOPES = ['user:read', 'chat:write', 'events:subscribe']

    def __init__(self, config: nowplaying.config.ConfigFile | None = None) -> None:
        service_config: nowplaying.oauth2.ServiceConfig = {
            'oauth_host': self.OAUTH_HOST,
            'config_prefix': 'kick',
            'default_scopes': self.SCOPES
        }
        super().__init__(config, service_config)

    def get_authorization_url(self, scopes: list[str] | None = None) -> str:
        ''' Generate the authorization URL using Kick's endpoint structure '''
        if not self.client_id:
            raise ValueError("Client ID is required")
        if not self.redirect_uri:
            raise ValueError("Redirect URI is required")

        if scopes is None:
            scopes = self.default_scopes

        self._generate_pkce_parameters()

        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'state': self.state,
            'scope': ' '.join(scopes),
            'code_challenge': self.code_challenge,
            'code_challenge_method': 'S256'
        }

        # Add service-specific parameters
        params |= self._get_additional_auth_params()

        query_string = urllib.parse.urlencode(params)
        # Use Kick's specific endpoint path
        auth_url = f"{self.oauth_host}/oauth/authorize?{query_string}"

        logging.info('Generated OAuth2 authorization URL for %s', self.config_prefix)
        return auth_url

    async def exchange_code_for_token(self,
                                      authorization_code: str,
                                      received_state: str | None = None) -> dict[str, Any]:
        ''' Exchange authorization code for access token using Kick's endpoint '''
        # Load PKCE parameters from config if not already set (for callback handler)
        if not self.code_verifier and self.config:
            self.code_verifier = self.config.cparser.value(
                f'{self.config_prefix}/temp_code_verifier')
            # State may have already been invalidated by callback handler for security
            if not self.state:
                self.state = self.config.cparser.value(f'{self.config_prefix}/temp_state')

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
            'code': authorization_code,
            'redirect_uri': self.redirect_uri,
            'code_verifier': self.code_verifier
        }

        # Add client_secret if available (Kick requires it)
        if self.client_secret:
            token_data['client_secret'] = self.client_secret

        logging.debug('%s token exchange using redirect_uri: %s', self.config_prefix,
                      self.redirect_uri)

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

        try:
            async with aiohttp.ClientSession() as session:
                # Use Kick's specific endpoint path
                async with session.post(f"{self.oauth_host}/oauth/token",
                                        data=token_data,
                                        headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        token_response: dict[str, Any] = await response.json()

                        self.access_token = token_response.get('access_token')
                        self.refresh_token = token_response.get('refresh_token')

                        logging.debug(
                            'Extracted tokens from response: '
                            'access_token=%s, refresh_token=%s',
                            'present' if self.access_token else 'missing',
                            'present' if self.refresh_token else 'missing')

                        # Clean up temporary PKCE parameters
                        # Note: Token saving is now handled by caller for consistency
                        self.cleanup_temp_pkce_params()

                        logging.info('Successfully obtained %s OAuth2 tokens', self.config_prefix)
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
        ''' Refresh the access token using Kick's endpoint '''
        if not refresh_token:
            refresh_token = (self.refresh_token
                             or self.config.cparser.value(f'{self.config_prefix}/refreshtoken'))

        if not refresh_token:
            raise ValueError("Refresh token is required")

        token_data = {
            'grant_type': 'refresh_token',
            'client_id': self.client_id,
            'refresh_token': refresh_token
        }

        # Add client_secret if available (Kick requires it)
        if self.client_secret:
            token_data['client_secret'] = self.client_secret

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

        async with aiohttp.ClientSession() as session:
            # Use Kick's specific endpoint path
            async with session.post(f"{self.oauth_host}/oauth/token",
                                    data=token_data,
                                    headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    token_response: dict[str, Any] = await response.json()

                    self.access_token = token_response.get('access_token')
                    if new_refresh_token := token_response.get('refresh_token'):
                        self.refresh_token = new_refresh_token

                    # Note: Caller is responsible for saving tokens to config
                    logging.info('Successfully refreshed %s OAuth2 tokens', self.config_prefix)
                    return token_response
                error_text = await response.text()
                logging.error('Failed to refresh token: %s - %s', response.status, error_text)
                raise ValueError(f"Token refresh failed: {response.status} - {error_text}")

    async def validate_token(self, token: str | None = None) -> dict[str, Any] | None:
        ''' Validate an access token using Kick's introspect endpoint '''
        if not token:
            token = (self.access_token
                     or self.config.cparser.value(f'{self.config_prefix}/accesstoken'))

        if not token:
            logging.warning("No token to validate")
            return None

        # Use Kick's token introspect endpoint (different from generic OAuth2)
        url = 'https://api.kick.com/public/v1/token/introspect'
        headers = {'Authorization': f'Bearer {token}'}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    validation_response = await response.json()
                    data = validation_response.get('data', {})

                    # Check if token is active
                    if data.get('active'):
                        logging.debug('Token validation successful')
                        return validation_response

                    logging.debug('Token is inactive')
                    return None

                logging.debug('Token validation failed: %s', response.status)
                return None

    async def revoke_token(self, token: str | None = None) -> None:
        ''' Revoke an access or refresh token using Kick's endpoint '''
        if not token:
            token = (self.access_token
                     or self.config.cparser.value(f'{self.config_prefix}/accesstoken'))

        if not token:
            logging.warning("No token to revoke")
            return

        # Use Kick's revoke endpoint with query parameters
        revoke_url = f"{self.oauth_host}/oauth/revoke"
        params = {'token': token, 'token_hint_type': 'access_token'}

        headers = {'Content-Type': 'application/x-www-form-urlencoded'}

        async with aiohttp.ClientSession() as session:
            async with session.post(revoke_url,
                                    params=params,
                                    headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    logging.info('Successfully revoked %s OAuth2 token', self.config_prefix)

                    # Clear tokens from config
                    if self.config:
                        self.config.cparser.remove(f'{self.config_prefix}/accesstoken')
                        self.config.cparser.remove(f'{self.config_prefix}/refreshtoken')
                        self.config.save()

                    self.access_token = None
                    self.refresh_token = None
                else:
                    error_text = await response.text()
                    logging.error('Failed to revoke token: %s - %s', response.status, error_text)


async def main() -> None:
    ''' Example usage of KickOAuth2 '''
    # Initialize with config (will read kick/clientid, kick/secret from config)
    oauth = KickOAuth2()

    # Check if configuration is present
    if not oauth.client_id:
        print("Error: kick/clientid not configured")
        return
    if not oauth.client_secret:
        print("Error: kick/secret not configured")
        return

    # Set redirect URI dynamically (required for authorization)
    oauth.redirect_uri = 'http://localhost:8899/kickredirect'

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
