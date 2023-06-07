#!/usr/bin/env python3
''' twitch settings '''

import time

from nowplaying.exceptions import PluginVerifyError

import nowplaying.twitch.utils


class TwitchSettings:
    ''' for settings UI '''

    def __init__(self):
        self.widget = None
        self.token = None

    def connect(self, uihelp, widget):  # pylint: disable=unused-argument
        '''  connect twitch '''
        self.widget = widget
        widget.chatbot_username_line.setBuddy(widget.token_lineedit)
        self.widget.token_lineedit.editingFinished.connect(self.update_token_name)

    def load(self, config, widget):
        ''' load the settings window '''
        self.widget = widget
        widget.enable_checkbox.setChecked(config.cparser.value('twitchbot/enabled', type=bool))
        widget.clientid_lineedit.setText(config.cparser.value('twitchbot/clientid'))
        widget.channel_lineedit.setText(config.cparser.value('twitchbot/channel'))
        #widget.username_lineedit.setText(
        #    config.cparser.value('twitchbot/username'))
        widget.token_lineedit.setText(config.cparser.value('twitchbot/chattoken'))
        widget.secret_lineedit.setText(config.cparser.value('twitchbot/secret'))
        self.update_token_name()

    @staticmethod
    def save(config, widget, subprocesses):
        ''' update the twitch settings '''
        oldchannel = config.cparser.value('twitchbot/channel')
        newchannel = widget.channel_lineedit.text()
        oldclientid = config.cparser.value('twitchbot/clientid')
        newclientid = widget.clientid_lineedit.text()
        oldsecret = config.cparser.value('twitchbot/secret')
        newsecret = widget.secret_lineedit.text()
        oldchattoken = config.cparser.value('twitchbot/chattoken')
        newchattoken = widget.token_lineedit.text()
        newchattoken = newchattoken.replace('oauth:', '')

        config.cparser.setValue('twitchbot/enabled', widget.enable_checkbox.isChecked())
        config.cparser.setValue('twitchbot/channel', newchannel)
        config.cparser.setValue('twitchbot/clientid', newclientid)
        config.cparser.setValue('twitchbot/secret', newsecret)

        config.cparser.setValue('twitchbot/chattoken', newchattoken)

        if (oldchannel != newchannel) or (oldclientid != newclientid) or (
                oldsecret != newsecret) or (oldchattoken != newchattoken):
            subprocesses.stop_twitchbot()
            config.cparser.remove('twitchbot/oldusertoken')
            config.cparser.remove('twitchbot/oldrefreshtoken')
            config.cparser.sync()
            time.sleep(5)
            subprocesses.start_twitchbot()

        #config.cparser.setValue('twitchbot/username',
        #                        widget.username_lineedit.text())

    @staticmethod
    def verify(widget):
        ''' verify the settings are good '''
        if not widget.enable_checkbox.isChecked():
            return

        if token := widget.token_lineedit.text():
            if 'oauth:' in token:
                token = token.replace('oauth:', '')
            if not nowplaying.twitch.utils.qtsafe_validate_token(token):
                raise PluginVerifyError('Twitch bot token is invalid')

    def update_token_name(self):
        ''' update the token name in the UI '''
        token = self.widget.token_lineedit.text()
        if self.token == token:
            return
        if token := token.replace('oauth:', ''):
            if username := nowplaying.twitch.utils.qtsafe_validate_token(token):
                self.widget.chatbot_username_line.setText(username)
            else:
                self.widget.chatbot_username_line.setText('(Invalid token?)')
