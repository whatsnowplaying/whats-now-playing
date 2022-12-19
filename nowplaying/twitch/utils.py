#!/usr/bin/env python3
''' twitch utils '''

import logging
import threading
import traceback
import requests

from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
from twitchAPI.types import AuthScope
from twitchAPI.oauth import UserAuthenticator, validate_token

import nowplaying.utils

USER_SCOPE = [
    AuthScope.CHANNEL_READ_REDEMPTIONS, AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT
]


async def get_user_image(twitch, loginname):
    ''' ask twitch for the user profile image '''
    image = None
    try:
        user = await first(twitch.get_users(logins=loginname))
        req = requests.get(user.profile_image_url, timeout=5)
        image = nowplaying.utils.image2png(req.content)
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

    valid = req.json()
    if valid.get('status') == 401:
        logging.debug('Twitch token is invalid')
        return None
    return valid.get('login')


class TwitchLogin:
    ''' manage the global twitch login for clientid/secret '''
    TWITCH = None
    TWITCH_LOCK = threading.Lock()

    def __init__(self, config):
        self.config = config

    async def api_login(self):
        ''' authenticate with the configured clientid/secret '''

        if TwitchLogin.TWITCH:
            return TwitchLogin.TWITCH

        logging.debug('entering lock')
        with TwitchLogin.TWITCH_LOCK:
            try:

                if self.config.cparser.value(
                        'twitchbot/clientid') and self.config.cparser.value(
                            'twitchbot/secret'):
                    TwitchLogin.TWITCH = await Twitch(
                        self.config.cparser.value('twitchbot/clientid'),
                        self.config.cparser.value('twitchbot/secret'))
                    token = self.config.cparser.value('twitchbot/oldusertoken')
                    refresh_token = self.config.cparser.value(
                        'twitchbot/oldrefreshtoken')
                    oldscopes = self.config.cparser.value(
                        'twitchbot/oldscopes')

                    if oldscopes != USER_SCOPE:
                        token = None

                    if token or not refresh_token:
                        valid = await validate_token(token)
                        if valid.get('status') == 401:
                            token = None

                    if not token:
                        auth = UserAuthenticator(TwitchLogin.TWITCH,
                                                 USER_SCOPE,
                                                 force_verify=False)
                        token, refresh_token = await auth.authenticate()
                        oldscopes = USER_SCOPE

                    await TwitchLogin.TWITCH.set_user_authentication(
                        token, USER_SCOPE, refresh_token)

                    self.config.cparser.setValue('twitchbot/oldusertoken',
                                                 token)
                    self.config.cparser.setValue('twitchbot/oldrefreshtoken',
                                                 token)
                    self.config.cparser.setValue('twitchbot/oldscopes',
                                                 USER_SCOPE)
                    TwitchLogin.TWITCH.user_auth_refresh_callback = self.save_refreshed_tokens
            except Exception:  #pylint: disable=broad-except
                logging.error(traceback.format_exc())
                return None
        logging.debug('exiting lock')
        return TwitchLogin.TWITCH

    async def save_refreshed_tokens(self, usertoken, refreshtoken):
        ''' every time token is updated, save it '''
        self.config.cparser.setValue('twitchbot/oldusertoken', usertoken)
        self.config.cparser.setValue('twitchbot/oldrefreshtoken', refreshtoken)
        self.config.save()

    @staticmethod
    async def api_logout():
        ''' log out of the global twitch login '''
        if TwitchLogin.TWITCH:
            try:
                with TwitchLogin.TWITCH_LOCK:
                    await TwitchLogin.TWITCH.refresh_used_token()
                    await TwitchLogin.TWITCH.close()
                TwitchLogin.TWITCH = None
                logging.debug('TWITCH shutdown')
            except Exception:  #pylint: disable=broad-except
                logging.error(traceback.format_exc())
