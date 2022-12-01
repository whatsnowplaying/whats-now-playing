#!/usr/bin/env python3
''' handle twitch requests '''

import asyncio
import logging
import threading
import signal
import sys

import requests as urlrequests

from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
from twitchAPI.types import AuthScope
from twitchAPI.oauth import UserAuthenticator, validate_token

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
from nowplaying.exceptions import PluginVerifyError
import nowplaying.metadata
import nowplaying.version

import nowplaying.twitch.chat
import nowplaying.twitch.requests

USER_SCOPE = [
    AuthScope.CHANNEL_READ_REDEMPTIONS, AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT
]


class TwitchSupport:
    ''' handle twitch  '''

    def __init__(self, config=None, stopevent=None):
        self.config = config
        if stopevent:
            self.stopevent = stopevent
        else:
            self.stopevent = threading.Event()
        self.twitch = None
        self.widgets = None
        self.chat = None
        self.requests = None
        self.loop = None

    async def bootstrap(self):
        ''' Authenticate twitch and launch related tasks '''

        signal.signal(signal.SIGINT, self.forced_stop)

        while not self.config.cparser.value(
                'twitchbot/clientid') and not self.stopevent.is_set():
            asyncio.sleep(1)

        if self.stopevent.is_set():
            return

        if self.config.cparser.value(
                'twitchbot/clientid') and self.config.cparser.value(
                    'twitchbot/secret'):
            self.twitch = await Twitch(
                self.config.cparser.value('twitchbot/clientid'),
                self.config.cparser.value('twitchbot/secret'))

            token = self.config.cparser.value('twitchbot/oldtoken')
            refresh_token = self.config.cparser.value(
                'twitchbot/oldrefreshtoken')
            scopes = self.config.cparser.value('twitchbot/oldscopes')

            if scopes != USER_SCOPE:
                token = None

            if token:
                valid = await validate_token(token)
                if valid.get('status') == 401:
                    auth = UserAuthenticator(self.twitch,
                                             USER_SCOPE,
                                             force_verify=False)
                    token, refresh_token = await auth.authenticate()

            await self.twitch.set_user_authentication(token, scopes,
                                                      refresh_token)

            self.config.cparser.setValue('twitchbot/oldtoken', token)
            self.config.cparser.setValue('twitchbot/oldrefreshtoken', token)
            self.config.cparser.setValue('twitchbot/oldscopes', USER_SCOPE)

        # Now launch the actual tasks...
        if not self.loop:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.loop = asyncio.new_event_loop()

        self.loop.create_task(self.chat.run_chat(twitch=self.twitch))
        self.loop.create_task(self.requests.run_request(twitch=self.twitch))

    async def _watch_for_exit(self):
        while not self.stopevent.is_set():
            await asyncio.sleep(1)
        await self.stop()

    def start(self):
        ''' start twitch support '''

        self.chat = nowplaying.twitch.chat.TwitchChat(config=self.config,
                                                      stopevent=self.stopevent)
        self.requests = nowplaying.twitch.requests.TwitchRequests(
            config=self.config, stopevent=self.stopevent)
        if not self.loop:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.loop = asyncio.new_event_loop()
        self.loop.create_task(self.bootstrap())
        self.loop.create_task(self._watch_for_exit())
        self.loop.run_forever()

    def forced_stop(self, signum, frame):  # pylint: disable=unused-argument
        ''' caught an int signal so tell the world to stop '''
        self.stopevent.set()

    async def stop(self):
        ''' stop the twitch support '''
        await self.requests.stop()
        await self.chat.stop()
        await self.twitch.close()
        self.loop.stop()


class TwitchSettings:
    ''' for settings UI '''

    def __init__(self):
        self.widget = None

    def connect(self, uihelp, widget):  # pylint: disable=unused-argument
        '''  connect twitch '''
        self.widget = widget

    @staticmethod
    def load(config, widget):
        ''' load the settings window '''
        widget.enable_checkbox.setChecked(
            config.cparser.value('twitchbot/enabled', type=bool))
        widget.clientid_lineedit.setText(
            config.cparser.value('twitchbot/clientid'))
        widget.channel_lineedit.setText(
            config.cparser.value('twitchbot/channel'))
        widget.username_lineedit.setText(
            config.cparser.value('twitchbot/username'))
        widget.token_lineedit.setText(config.cparser.value('twitchbot/token'))
        widget.secret_lineedit.setText(
            config.cparser.value('twitchbot/secret'))

    @staticmethod
    def save(config, widget):
        ''' update the twitch settings '''
        config.cparser.setValue('twitchbot/enabled',
                                widget.enable_checkbox.isChecked())
        config.cparser.setValue('twitchbot/channel',
                                widget.channel_lineedit.text())
        config.cparser.setValue('twitchbot/clientid',
                                widget.clientid_lineedit.text())
        config.cparser.setValue('twitchbot/secret',
                                widget.secret_lineedit.text())
        config.cparser.setValue('twitchbot/token',
                                widget.token_lineedit.text())
        config.cparser.setValue('twitchbot/username',
                                widget.username_lineedit.text())

    @staticmethod
    def verify(widget):
        ''' verify the settings are good '''
        if not widget.enable_checkbox.isChecked():
            return

        if token := widget.token_lineedit.text():
            url = 'https://id.twitch.tv/oauth2/validate'
            headers = {'Authorization': f'OAuth {token}'}

            try:
                req = urlrequests.get(url, headers=headers, timeout=5)
            except Exception as error:
                raise PluginVerifyError(
                    f'Twitch Token validation check failed: {error}'
                ) from error

            valid = req.json()
            if valid.get('status') == 401:
                raise PluginVerifyError(
                    'Twitch Token is expired and/or not valid.')
