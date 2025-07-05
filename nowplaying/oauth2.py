#!/usr/bin/env python3
''' Generic OAuth2 authentication handler with PKCE for streaming services '''

import base64
import hashlib
import logging
import secrets
import urllib.parse
import webbrowser
from typing import Any, TypedDict, NotRequired  # pylint: disable=no-name-in-module

import aiohttp
from aiohttp import web
import jinja2

import nowplaying.config


class ServiceConfig(TypedDict):
    """Configuration for OAuth2 service-specific settings."""
    oauth_host: str  # OAuth server URL (e.g., 'https://id.twitch.tv')
    config_prefix: str  # Config key prefix (e.g., 'twitchbot', 'kick')
    default_scopes: list[str]  # List of default OAuth scopes
    api_host: NotRequired[str | None]  # API server URL (optional, for user info calls)
    token_endpoint: str  # e.g., '/oauth/token' for Kick, '/oauth2/token' for Twitch
    authorize_endpoint: str  # e.g., '/oauth/authorize' for Kick, '/oauth2/authorize' for Twitch
    revoke_endpoint: NotRequired[str]  # e.g., '/oauth/revoke' (optional)
    validate_endpoint: NotRequired[str]  # e.g., '/oauth2/validate' for Twitch (optional)


class OAuth2Client:  # pylint: disable=too-many-instance-attributes
    ''' Generic OAuth 2.1 authentication flow with PKCE for any service '''

    def __init__(self,
                 config: nowplaying.config.ConfigFile | None = None,
                 service_config: ServiceConfig | None = None) -> None:
        """Initialize OAuth2 client with service-specific configuration.

        Args:
            config: Application config object
            service_config: Service-specific configuration (see ServiceConfig TypedDict)
        """
        self.config = config or nowplaying.config.ConfigFile()

        # Service-specific configuration
        if not service_config:
            raise ValueError("service_config is required")

        self.oauth_host = service_config['oauth_host']
        self.api_host = service_config.get('api_host')
        self.config_prefix = service_config['config_prefix']
        self.default_scopes = service_config['default_scopes']
        self.token_endpoint = service_config['token_endpoint']
        self.authorize_endpoint = service_config['authorize_endpoint']
        self.revoke_endpoint = service_config.get('revoke_endpoint')
        self.validate_endpoint = service_config.get('validate_endpoint')

        # Read service-specific config
        self.client_id: str = self.config.cparser.value(f'{self.config_prefix}/clientid')
        self.client_secret: str = self.config.cparser.value(f'{self.config_prefix}/secret')
        # Redirect URI is set dynamically by the calling code, not stored in config
        self.redirect_uri: str = None

        # PKCE parameters with unique session ID to prevent conflicts
        session_bytes = secrets.token_bytes(16)
        self.session_id: str = base64.urlsafe_b64encode(session_bytes).decode('utf-8').rstrip('=')
        self.code_verifier: str | None = None
        self.code_challenge: str | None = None
        self.state: str | None = None

        # Tokens
        self.access_token: str | None = None
        self.refresh_token: str | None = None

    def _get_additional_auth_params(self) -> dict[str, str]:  # pylint: disable=no-self-use
        ''' Override in subclasses to add service-specific OAuth parameters '''
        return {}

    def _generate_pkce_parameters(self) -> None:
        ''' Generate PKCE code verifier and challenge '''
        # Generate code verifier (43-128 characters, URL-safe)
        self.code_verifier = secrets.token_urlsafe(43)

        # Generate code challenge (SHA256 hash of verifier, base64url encoded)
        challenge_bytes = hashlib.sha256(self.code_verifier.encode('utf-8')).digest()
        self.code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')

        # Generate state parameter for CSRF protection, include session ID
        state_data = f"{self.session_id}:{secrets.token_urlsafe(32)}"
        state_bytes = state_data.encode('utf-8')
        self.state = base64.urlsafe_b64encode(state_bytes).decode('utf-8').rstrip('=')

        # Store PKCE parameters temporarily in config for callback handler
        # Use session ID to prevent conflicts between simultaneous OAuth flows
        if self.config:
            verifier_key = f'{self.config_prefix}/temp_code_verifier_{self.session_id}'
            state_key = f'{self.config_prefix}/temp_state_{self.session_id}'
            self.config.cparser.setValue(verifier_key, self.code_verifier)
            self.config.cparser.setValue(state_key, self.state)
            self.config.save()

    def get_authorization_url(self, scopes: list[str] | None = None) -> str:
        ''' Generate the authorization URL for user consent '''
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
        auth_url = f"{self.oauth_host}{self.authorize_endpoint}?{query_string}"

        logging.info('Generated OAuth2 authorization URL for %s', self.config_prefix)
        return auth_url

    def open_browser_for_auth(self, scopes: list[str] | None = None) -> bool:
        ''' Open browser to initiate OAuth2 flow '''
        auth_url = self.get_authorization_url(scopes)

        try:
            webbrowser.open(auth_url)
            logging.info('Opened browser for %s OAuth2 authentication', self.config_prefix)
            return True
        except OSError as error:
            logging.error('Failed to open browser for %s OAuth2: %s', self.config_prefix, error)
            return False

    async def exchange_code_for_token(self,
                                      authorization_code: str,
                                      received_state: str | None = None) -> dict[str, Any]:
        ''' Exchange authorization code for access token '''
        # Load PKCE parameters from config if not already set (for callback handler)
        if not self.code_verifier and self.config:
            verifier_key = f'{self.config_prefix}/temp_code_verifier_{self.session_id}'
            self.code_verifier = self.config.cparser.value(verifier_key)
            # State may have already been invalidated by callback handler for security
            if not self.state:
                state_key = f'{self.config_prefix}/temp_state_{self.session_id}'
                self.state = self.config.cparser.value(state_key)

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

        logging.debug('%s token exchange using redirect_uri: %s', self.config_prefix,
                      self.redirect_uri)

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.oauth_host}{self.token_endpoint}",
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

    async def refresh_access_token_async(self, refresh_token: str | None = None) -> dict[str, Any]:
        ''' Refresh the access token using refresh token '''
        if not refresh_token:
            refresh_token = (self.refresh_token
                             or self.config.cparser.value(f'{self.config_prefix}/refreshtoken'))

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
            async with session.post(f"{self.oauth_host}{self.token_endpoint}",
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

    async def revoke_token(self, token: str | None = None) -> None:
        ''' Revoke an access or refresh token '''
        if not token:
            token = self.access_token or self.config.cparser.value(
                f'{self.config_prefix}/accesstoken')

        if not token:
            logging.warning("No token to revoke")
            return

        revoke_data = {'client_id': self.client_id, 'token': token}

        headers = {'Content-Type': 'application/x-www-form-urlencoded'}

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.oauth_host}{self.revoke_endpoint}",
                                    data=revoke_data,
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

    async def validate_token_async(self, token: str | None = None) -> dict[str, Any] | None:
        ''' Validate an access token and return user info '''
        if not token:
            token = self.access_token or self.config.cparser.value(
                f'{self.config_prefix}/accesstoken')

        if not token:
            logging.warning("No token to validate")
            return None

        headers = {'Authorization': f'OAuth {token}'}

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.oauth_host}{self.validate_endpoint}",
                                   headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    validation_response = await response.json()
                    logging.debug('Token validation successful')
                    return validation_response

                logging.debug('Token validation failed: %s', response.status)
                return None

    async def get_user_info_async(self, token: str | None = None) -> dict[str, Any] | None:
        ''' Get current user information (requires api_host to be configured) '''
        if not self.api_host:
            logging.warning("API host not configured for %s", self.config_prefix)
            return None

        if not token:
            token = self.access_token or self.config.cparser.value(
                f'{self.config_prefix}/accesstoken')

        if not token:
            logging.warning("No token available for user info")
            return None

        headers = {'Authorization': f'Bearer {token}', 'Client-Id': self.client_id}

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.api_host}/users",
                                   headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    user_response = await response.json()
                    if users := user_response.get('data', []):
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
        access_token = self.config.cparser.value(f'{self.config_prefix}/accesstoken')
        refresh_token = self.config.cparser.value(f'{self.config_prefix}/refreshtoken')

        return access_token, refresh_token

    def cleanup_temp_pkce_params(self) -> None:
        '''Remove temporary PKCE parameters from config to prevent stale data.'''
        if self.config:
            verifier_key = f'{self.config_prefix}/temp_code_verifier_{self.session_id}'
            state_key = f'{self.config_prefix}/temp_state_{self.session_id}'
            self.config.cparser.remove(verifier_key)
            self.config.cparser.remove(state_key)
            self.config.save()
            self.config.cparser.sync()  # Ensure cross-process visibility
            logging.debug('Cleaned up temporary PKCE parameters for %s session %s',
                         self.config_prefix, self.session_id)

    def clear_stored_tokens(self) -> None:
        ''' Clear tokens from config storage '''
        if self.config:
            self.config.cparser.remove(f'{self.config_prefix}/accesstoken')
            self.config.cparser.remove(f'{self.config_prefix}/refreshtoken')
            self.config.save()

        self.access_token = None
        self.refresh_token = None

    @classmethod
    def cleanup_stray_temp_credentials(cls, config: nowplaying.config.ConfigFile) -> None:
        '''Clean up any stray temporary PKCE credentials from config.

        This should be called on app startup and shutdown to ensure no temporary
        credentials are left in the config file if OAuth flows were interrupted.
        '''
        if not config:
            return

        config.get()  # Refresh from disk

        # Get all config keys and find temporary PKCE parameters
        stray_keys = []
        for key in config.cparser.allKeys():
            key_str = str(key)
            if '/temp_code_verifier_' in key_str or '/temp_state_' in key_str:
                stray_keys.append(key_str)

        if stray_keys:
            logging.info('Cleaning up %d stray temporary OAuth2 credentials', len(stray_keys))
            for key in stray_keys:
                config.cparser.remove(key)
                logging.debug('Removed stray temporary credential: %s', key)
            config.save()
            config.cparser.sync()
        else:
            logging.debug('No stray temporary OAuth2 credentials found')

    def get_auth_url(self, token_type: str = 'main') -> str | None:  # pylint: disable=unused-argument
        ''' Generate OAuth authentication URL for specified token type '''
        # Validate configuration
        if not self.client_id or not self.client_secret:
            logging.error('OAuth2 configuration incomplete')
            return None

        # Set appropriate redirect URI based on token type
        port = self.config.cparser.value('webserver/port', type=int) or 8899

        # Default redirect path - can be overridden by subclasses
        redirect_path = f'{self.config_prefix}redirect'
        self.redirect_uri = f'http://localhost:{port}/{redirect_path}'

        try:
            return self.get_authorization_url()
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.exception('Failed to generate auth URL: %s', error)
            return None

    def is_configuration_complete(self) -> bool:
        ''' Check if OAuth configuration is complete '''
        return bool(self.client_id and self.client_secret)

    def get_redirect_uri(self, token_type: str = 'main') -> str:  # pylint: disable=unused-argument
        ''' Get the redirect URI for the specified token type '''
        port = self.config.cparser.value('webserver/port', type=int) or 8899
        redirect_path = f'{self.config_prefix}redirect'
        return f'http://localhost:{port}/{redirect_path}'

    @staticmethod
    async def handle_oauth_redirect(request, oauth_config: dict, config, jinja2_env):
        """Generic OAuth2 redirect handler for any service.

        This method handles the OAuth2 authorization code flow redirect for any service.
        It validates the state parameter (CSRF protection), exchanges the authorization
        code for tokens, and saves them to the configuration.

        Args:
            request: The web request object (aiohttp.web.Request)
            oauth_config: Dictionary containing service-specific configuration:
                - 'service_name': Display name for logging (e.g., 'Kick OAuth2', 'Twitch OAuth2')
                - 'oauth_class': OAuth2 class to instantiate
                - 'config_prefix': Config key prefix (e.g., 'kick', 'twitchbot')
                - 'template_prefix': Template filename prefix (e.g., 'kick_oauth', 'twitch_oauth')
                - 'redirect_path': Path component for redirect URI (e.g., 'kickredirect')
                - 'token_keys': Dict with 'access' and 'refresh' keys for token storage
                - 'success_template': Success template name (optional)
            config: The config object (nowplaying.config.ConfigFile)
            jinja2_env: The Jinja2 environment (jinja2.Environment)

        Returns:
            aiohttp.web.Response: HTML response for the OAuth flow result
        """
        # Initialize helper
        helper = _OAuthRedirectHelper(request, oauth_config, config, jinja2_env)

        # Process OAuth flow steps
        if error_response := helper.handle_oauth_error():
            return error_response
        if code_error_response := helper.validate_authorization_code():
            return code_error_response
        if state_error_response := helper.validate_state_parameter():
            return state_error_response

        return await helper.exchange_code_for_tokens()


class _OAuthRedirectHelper:  # pylint: disable=too-many-instance-attributes
    """Helper class to handle OAuth redirect processing steps."""

    def __init__(self, request: web.Request, oauth_config: dict, config, jinja2_env):
        self.request = request
        self.oauth_config = oauth_config
        self.params = dict(request.query)
        self.web = web

        # Extract config values
        self.service_name = oauth_config['service_name']
        self.oauth_class = oauth_config['oauth_class']
        self.config_prefix = oauth_config['config_prefix']
        self.template_prefix = oauth_config['template_prefix']
        self.redirect_path = oauth_config['redirect_path']
        self.token_keys = oauth_config['token_keys']
        self.success_template = oauth_config.get('success_template',
                                                 f"{oauth_config['template_prefix']}_success.htm")

        # Use provided config and jinja2 environment
        self.config = config
        self.config.get()
        self.load_template = self._create_template_loader(jinja2_env)

        # Session ID will be extracted from state parameter during validation
        self.session_id = None

        # Log redirect for debugging (don't log auth code for security)
        logging.info('%s redirect received with parameters: %s', self.service_name, {
            k: v
            for k, v in self.params.items() if k != 'code'
        })

    @staticmethod
    def _create_template_loader(jinja2_env: jinja2.Environment):
        """Create a template loader function with error handling."""

        def load_oauth_template(template_name: str, **kwargs) -> str:
            try:
                template = jinja2_env.get_template(f'oauth/{template_name}')
                return template.render(**kwargs)
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.error('Template error for %s: %s', template_name, error)
                return '<html><body><h1>Template Error</h1></body></html>'

        return load_oauth_template

    def handle_oauth_error(self) -> web.Response | None:
        """Handle OAuth error responses."""
        if 'error' not in self.params:
            return None

        error_code = self.params.get('error', 'unknown_error')
        error_description = self.params.get('error_description', 'No description provided')
        response_html = self.load_template(f'{self.template_prefix}_error.htm',
                                           error_code=error_code,
                                           error_description=error_description)
        return self.web.Response(content_type='text/html', text=response_html)

    def validate_authorization_code(self):
        """Validate presence of authorization code."""
        if self.params.get('code'):
            return None

        # Try to extract session ID from state for cleanup
        received_state = self.params.get('state')
        if received_state:
            try:
                state_data = base64.urlsafe_b64decode(received_state + '==').decode('utf-8')
                session_id, _ = state_data.split(':', 1)
                oauth = self.oauth_class(self.config)
                oauth.session_id = session_id
                oauth.cleanup_temp_pkce_params()
            except (ValueError, UnicodeDecodeError):
                # Malformed state, can't cleanup specific session
                pass

        response_html = self.load_template(f'{self.template_prefix}_no_code.htm')
        return self.web.Response(content_type='text/html', text=response_html)

    def validate_state_parameter(self):
        """Validate state parameter to prevent CSRF attacks."""
        received_state = self.params.get('state')

        if not received_state:
            response_html = self.load_template(f'{self.template_prefix}_invalid_session.htm')
            logging.warning('%s callback without state parameter', self.service_name)
            return self.web.Response(content_type='text/html', text=response_html)

        # Extract session ID from state parameter
        try:
            state_data = base64.urlsafe_b64decode(received_state + '==').decode('utf-8')
            session_id, _ = state_data.split(':', 1)
        except (ValueError, UnicodeDecodeError):
            response_html = self.load_template(f'{self.template_prefix}_invalid_session.htm')
            logging.warning('%s callback with malformed state parameter', self.service_name)
            return self.web.Response(content_type='text/html', text=response_html)

        # Look up expected state using session ID
        expected_state = self.config.cparser.value(f'{self.config_prefix}/temp_state_{session_id}')

        if not expected_state:
            response_html = self.load_template(f'{self.template_prefix}_invalid_session.htm')
            logging.warning('%s callback without valid session state for session %s',
                          self.service_name, session_id)
            return self.web.Response(content_type='text/html', text=response_html)

        if received_state != expected_state:
            # Create OAuth instance with matching session ID for cleanup
            oauth = self.oauth_class(self.config)
            oauth.session_id = session_id
            oauth.cleanup_temp_pkce_params()
            response_html = self.load_template(f'{self.template_prefix}_csrf_error.htm')
            logging.error('%s CSRF attack detected: state mismatch for session %s',
                         self.service_name, session_id)
            return self.web.Response(content_type='text/html', text=response_html)

        # State validation successful - invalidate to prevent replay attacks
        self.config.cparser.remove(f'{self.config_prefix}/temp_state_{session_id}')
        self.config.save()
        logging.debug('%s state parameter invalidated after validation for session %s',
                     self.service_name, session_id)

        # Store session ID for use in token exchange
        self.session_id = session_id
        return None

    async def exchange_code_for_tokens(self):
        """Exchange authorization code for access/refresh tokens."""
        try:
            # Initialize OAuth2 handler and set redirect URI
            oauth = self.oauth_class(self.config)
            # Set the session ID to match the one from state validation
            oauth.session_id = self.session_id
            port = self.config.cparser.value('webserver/port', type=int) or 8899
            oauth.redirect_uri = f'http://localhost:{port}/{self.redirect_path}'

            # Exchange code for tokens
            authorization_code = self.params.get('code')
            received_state = self.params.get('state')
            token_response = await oauth.exchange_code_for_token(authorization_code, received_state)

            # Save tokens
            self._save_tokens(token_response)

            # Success response
            response_html = self.load_template(self.success_template)
            logging.info('%s authentication completed successfully', self.service_name)
            return self.web.Response(content_type='text/html', text=response_html)

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error('%s token exchange failed: %s', self.service_name, error)
            response_html = self.load_template(f'{self.template_prefix}_token_error.htm',
                                               error_message='Authentication failed. '
                                               'Please check your configuration and try again.')
            return self.web.Response(content_type='text/html', text=response_html)

    def _save_tokens(self, token_response: dict) -> None:
        """Save access and refresh tokens to configuration."""
        access_token = token_response.get('access_token')
        refresh_token = token_response.get('refresh_token')

        if access_token:
            self.config.cparser.setValue(self.token_keys['access'], access_token)
            if refresh_token:
                self.config.cparser.setValue(self.token_keys['refresh'], refresh_token)
            self.config.save()
            logging.info('%s tokens saved successfully', self.service_name)
