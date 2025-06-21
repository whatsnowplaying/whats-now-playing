#!/usr/bin/env python3
''' kick utils '''

import logging
from typing import Any

import requests

import nowplaying.config
import nowplaying.kick.oauth2


async def attempt_token_refresh(config: nowplaying.config.ConfigFile) -> bool:
    ''' Try to refresh existing tokens '''
    oauth = nowplaying.kick.oauth2.KickOAuth2(config)

    try:
        # Check if we have stored tokens
        access_token, refresh_token = oauth.get_stored_tokens()
        logging.debug('Retrieved stored tokens: access_token=%s, refresh_token=%s',
                     'present' if access_token else 'missing',
                     'present' if refresh_token else 'missing')

        if access_token:
            # Validate current token
            logging.debug('Validating stored access token')
            validation = await oauth.validate_token(access_token)
            if validation:
                oauth.access_token = access_token
                oauth.refresh_token = refresh_token
                logging.debug('Existing Kick token is valid')
                return True
            logging.debug('Stored access token is invalid')

        if refresh_token:
            # Try to refresh the token
            logging.debug('Attempting to refresh token using refresh_token')
            await oauth.refresh_access_token(refresh_token)
            logging.info('Successfully refreshed Kick OAuth2 tokens')
            return True
        logging.debug('No refresh_token available')

    except Exception as error:  # pylint: disable=broad-except
        logging.error('Token refresh failed: %s', error)

    return False


# Token Validation - Dual Implementation for Different Use Cases:
# 1. async version for chat/launch components (non-blocking)
# 2. sync version for UI components (Qt-safe, immediate feedback)
# Both use the same Kick introspect endpoint for consistency

async def validate_kick_token_async(config: nowplaying.config.ConfigFile,
                                   access_token: str | None = None) -> dict[str, Any] | None:
    ''' Async wrapper for token validation (for non-UI components) '''
    oauth = nowplaying.kick.oauth2.KickOAuth2(config)
    return await oauth.validate_token(access_token)


def qtsafe_validate_kick_token(access_token: str) -> bool:  # pylint: disable=too-many-return-statements
    ''' Validate kick token synchronously (Qt-safe for UI components) '''
    if not access_token:
        return False

    # Use Kick's token introspect endpoint
    url = 'https://api.kick.com/public/v1/token/introspect'
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        req = requests.post(url, headers=headers, timeout=10)
    except (requests.ConnectionError, requests.Timeout) as error:
        logging.warning('Kick token validation network error (token status unknown): %s', error)
        return False
    except Exception as error:  # pylint: disable=broad-except
        logging.error('Kick token validation unexpected error: %s', error)
        return False

    if req.status_code != 200:
        if req.status_code == 401:
            logging.debug('Kick token is invalid/expired')
        else:
            logging.warning('Kick token validation returned status %s', req.status_code)
        return False

    try:
        response_data = req.json()
        data = response_data.get('data', {})

        # Check if token is active
        if data.get('active'):
            client_id = data.get('client_id', 'Unknown')
            scopes = data.get('scope', 'Unknown')
            token_type = data.get('token_type', 'Unknown')
            logging.debug('Kick token valid - client: %s, type: %s, scopes: %s',
                         client_id, token_type, scopes)
            return True

        logging.debug('Kick token is inactive')
        return False
    except Exception as error:  # pylint: disable=broad-except
        logging.error('Kick token validation/bad json: %s', error)
        return False
