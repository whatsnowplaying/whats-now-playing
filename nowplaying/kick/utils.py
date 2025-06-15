#!/usr/bin/env python3
''' kick utils '''

import logging

import requests


def qtsafe_validate_kick_token(access_token: str) -> bool:
    ''' validate kick token synchronously (shared by settings and launch) '''
    if not access_token:
        return False

    # Use Kick's token introspect endpoint to validate the token
    url = 'https://api.kick.com/public/v1/token/introspect'
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        req = requests.post(url, headers=headers, timeout=10)
    except Exception as error:  # pylint: disable=broad-except
        logging.error('Kick token validation check failed: %s', error)
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
