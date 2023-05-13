#!/usr/bin/env python3
''' handle twitch chat '''

import asyncio
import datetime
import fnmatch
import logging
import os
import pathlib
import platform
import socket
import traceback

import aiohttp  # pylint: disable=import-error

import jinja2  # pylint: disable=import-error

from twitchAPI.twitch import Twitch  # pylint: disable=import-error
from twitchAPI.types import AuthScope  # pylint: disable=import-error
from twitchAPI.chat import Chat, ChatEvent  # pylint: disable=import-error
from twitchAPI.oauth import validate_token  # pylint: disable=import-error

from PySide6.QtCore import QCoreApplication, QStandardPaths, Slot  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=import-error, no-name-in-module
    QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout, QLabel,
    QTableWidgetItem)

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
from nowplaying.exceptions import PluginVerifyError
import nowplaying.metadata
import nowplaying.trackrequests

LASTANNOUNCED = {'artist': None, 'title': None}
SPLITMESSAGETEXT = '****SPLITMESSSAGEHERE****'

# needs to match ui file
TWITCHBOT_CHECKBOXES = [
    'anyone', 'broadcaster', 'moderator', 'subscriber', 'founder', 'conductor',
    'vip', 'bits'
]


class TwitchChat:  #pylint: disable=too-many-instance-attributes
    ''' handle twitch chat '''

    def __init__(self, config=None, stopevent=None):
        self.config = config
        self.stopevent = stopevent
        self.watcher = None
        self.requests = nowplaying.trackrequests.Requests(config=config,
                                                          stopevent=stopevent)
        self.metadb = nowplaying.db.MetadataDB()
        self.templatedir = pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.DocumentsLocation)[0]).joinpath(
                    QCoreApplication.applicationName(), 'templates')
        self.jinja2 = self.setup_jinja2(self.templatedir)
        self.twitch = None
        self.twitchcustom = False
        self.chat = None
        self.tasks = set()
        self.starttime = datetime.datetime.utcnow()
        self.timeout = aiohttp.ClientTimeout(total=60)

    async def _try_custom_token(self, token):
        ''' if a custom token has been provided, try it. '''
        if self.twitch and self.twitchcustom:
            await self.twitch.close()
        if token:
            try:
                tokenval = await validate_token(token)
                if tokenval.get('status') == 401:
                    logging.error(tokenval['message'])
                else:
                    # don't really care if the token's clientid
                    # doesn't match the given clientid since
                    # Chat() never uses the clientid other than
                    # to do a user lookup
                    self.twitchcustom = False
                    self.twitch = await Twitch(tokenval['client_id'],
                                               authenticate_app=False,
                                               session_timeout=self.timeout)
                    self.twitch.auto_refresh_auth = False
                    await self.twitch.set_user_authentication(
                        token=token,
                        scope=[AuthScope.CHAT_READ, AuthScope.CHAT_EDIT],
                        validate=False)
                    self.twitchcustom = True
            except:  # pylint: disable=bare-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)

    async def _token_validation(self):
        if token := self.config.cparser.value('twitchbot/chattoken'):
            if 'oauth:' in token:
                token = token.replace('oauth:', '')
                self.config.cparser.setValue('twitchbot/chattoken', token)
            logging.debug('validating old token')
            try:
                valid = await validate_token(token)
                if valid.get('status') == 401:
                    token = None
                    logging.error('Old twitchbot-specific token has expired')
            except Exception as error:  #pylint: disable=broad-except
                logging.error('cannot validate token: %s', error)
                token = None
        return token

    async def run_chat(self, twitchlogin):  # pylint: disable=too-many-branches, too-many-statements
        ''' twitch chat '''

        # If the user provides us with a pre-existing token and username,
        # as was the case prior to moving to pyTwitchAPI, then use
        # those to authenticate.  This path also provides a way for
        # users to use a different account for their chat bot
        # otherwise, use the existing authentication and run as
        # the user

        while not self.config.cparser.value(
                'twitchbot/chat', type=bool) and not self.stopevent.is_set():
            await asyncio.sleep(1)
            self.config.get()

        if self.stopevent.is_set():
            return

        loggedin = False
        while not self.stopevent.is_set():

            if loggedin and self.chat and not self.chat.is_connected():
                logging.error('No longer logged into chat')
                await self.stop()
                loggedin = False

            if loggedin:
                await asyncio.sleep(60)
                continue

            try:
                token = await self._token_validation()

                if token:
                    logging.debug('attempting to use old token')
                    await self._try_custom_token(token)

                if not self.twitch:
                    logging.debug('attempting to use global token')
                    self.twitch = await twitchlogin.api_login()
                    self.twitchcustom = False
                    # sourcery skip: hoist-if-from-if
                    if not self.twitch:
                        await twitchlogin.cache_token_del()

                if not self.twitch:
                    logging.error(
                        'No valid credentials to start Twitch Chat support.')
                    await asyncio.sleep(60)
                    continue

                self.chat = await Chat(
                    self.twitch,
                    initial_channel=self.config.cparser.value(
                        'twitchbot/channel'))
                self.chat.register_event(ChatEvent.READY,
                                         self.on_twitchchat_ready)
                self.chat.register_command(
                    'whatsnowplayingversion',
                    self.on_twitchchat_whatsnowplayingversion)
                for configitem in self.config.cparser.childGroups():
                    if 'twitchbot-command-' in configitem:
                        command = configitem.replace('twitchbot-command-', '')
                        self.chat.register_command(command,
                                                   self.on_twitchchat_message)

                self.chat.start()
                loggedin = True
                try:
                    loop = asyncio.get_running_loop()
                except Exception as error:  #pylint: disable=broad-except
                    logging.debug(error)
                await asyncio.sleep(1)
                task = loop.create_task(self._setup_timer())
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            except (aiohttp.client_exceptions.ClientConnectorError,
                    socket.gaierror) as error:
                logging.error(error)
                await asyncio.sleep(60)
                continue
            except:  #pylint: disable=bare-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                await asyncio.sleep(60)
                continue
        if self.twitch:
            if self.twitchcustom:
                await self.twitch.close()
            else:
                await twitchlogin.api_logout()

    async def on_twitchchat_ready(self, ready_event):
        ''' twitch chatbot has connected, now join '''
        await ready_event.chat.join_room(
            self.config.cparser.value('twitchbot/channel'))

    async def on_twitchchat_message(self, msg):
        ''' twitch chatbot incoming message '''
        self.config.get()
        commandchar = self.config.cparser.value('twitchbot/commandchar')
        if not commandchar:
            commandchar = '!'
            self.config.cparser.setValue('twitchbot/commandchar', '!')
        if msg.text[:1] == commandchar:
            await self.do_command(msg)

    async def on_twitchchat_whatsnowplayingversion(self, cmd):
        ''' handle !whatsnowplayingversion '''
        inputsource = self.config.cparser.value('settings/input')
        delta = datetime.datetime.utcnow() - self.starttime
        plat = platform.platform()
        content = (
            f'whatsnowplaying v{self.config.version} by @modernmeerkat. '
            f'Using {inputsource} on {plat}. Running for {delta}.')
        try:
            await cmd.reply(content)
        except:  #pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            await self.chat.send_message(
                self.config.cparser.value('twitchbot/channel'), content)
        return

    def check_command_perms(self, profile, command):
        ''' given the profile, check if the command is allowed to be executed '''
        self.config.get()

        # shortcut the 'anyone' commands
        if self.config.cparser.value(f'twitchbot-command-{command}/anyone',
                                     type=bool):
            return True

        self.config.cparser.beginGroup(f'twitchbot-command-{command}')
        perms = {
            key: self.config.cparser.value(key, type=bool)
            for key in self.config.cparser.childKeys()
        }
        self.config.cparser.endGroup()

        if perms:
            return any(
                profile.get(usertype) and profile[usertype] > 0
                for usertype in perms.items())

        return True

    async def do_command(self, msg):  # pylint: disable=unused-argument
        ''' process a command '''

        metadata = {'cmduser': msg.user.display_name}
        commandlist = msg.text[1:].split()
        metadata['cmdtarget'] = []
        if len(commandlist) > 1:
            for usercheck in commandlist[1:]:
                if usercheck[0] == '@':
                    metadata['cmdtarget'].append(usercheck[1:])
                else:
                    metadata['cmdtarget'].append(usercheck)

        cmdfile = f'twitchbot_{commandlist[0]}.txt'

        if not self.check_command_perms(msg.user.badges, commandlist[0]):
            return

        if self.config.cparser.value('settings/requests',
                                     type=bool) and self.config.cparser.value(
                                         'twitchbot/chatrequests', type=bool):
            if reply := await self.handle_request(commandlist[0],
                                                  commandlist[1:],
                                                  msg.user.display_name):
                metadata |= reply

        await self._post_template(msg=msg,
                                  template=cmdfile,
                                  moremetadata=metadata)

    async def redemption_to_chat_request_bridge(self, command, metadata):
        ''' respond in chat when a redemption request triggers '''
        if self.config.cparser.value('twitchbot/chatrequests',
                                     type=bool) and self.config.cparser.value(
                                         'twitchbot/chat', type=bool):
            cmdfile = f'twitchbot_{command}.txt'
            await self._post_template(template=cmdfile, moremetadata=metadata)

    async def handle_request(self, command, params, username):  # pylint: disable=unused-argument
        ''' handle the channel point redemption '''
        reply = None
        logging.debug('got command: %s', command)
        commandlist = ' '.join(params)
        if commandlist:
            logging.debug('got commandlist: %s', commandlist)
        if setting := await self.requests.find_command(command):
            logging.debug(setting)
            setting[
                'userimage'] = await nowplaying.twitch.utils.get_user_image(
                    self.twitch, username)
            if setting.get('type') == 'Generic':
                reply = await self.requests.user_track_request(
                    setting, username, commandlist)
            elif setting.get('type') == 'Roulette':
                reply = await self.requests.user_roulette_request(
                    setting, username, commandlist[1:])
            elif setting.get('type') == 'GifWords':
                reply = await self.requests.gifwords_request(
                    setting, username, commandlist)
        return reply

    @staticmethod
    def _finalize(variable):
        ''' helper routine to avoid NoneType exceptions '''
        if variable:
            return variable
        return ''

    def setup_jinja2(self, directory):
        ''' set up the environment '''
        return jinja2.Environment(loader=jinja2.FileSystemLoader(directory),
                                  finalize=self._finalize,
                                  trim_blocks=True)

    async def _setup_timer(self):
        ''' need to watch the metadata db to know to send announcement '''
        self.watcher = self.metadb.watcher()
        self.watcher.start(customhandler=self._announce_track)
        await self._async_announce_track()
        while not self.stopevent.is_set():
            await asyncio.sleep(1)

        logging.debug('watcher stop event received')
        self.watcher.stop()

    async def _delay_write(self):
        ''' handle the twitch chat delay '''
        try:
            delay = self.config.cparser.value('twitchbot/announcedelay',
                                              type=float,
                                              defaultValue=1.0)
        except ValueError:
            delay = 1.0
        logging.debug('got delay of %s', delay)
        await asyncio.sleep(delay)

    def _announce_track(self, event):  #pylint: disable=unused-argument
        logging.debug('watcher event called')
        try:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._async_announce_track())
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            except:  # pylint: disable=bare-except
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self._async_announce_track())
        except:  #pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            logging.error('watcher failed')

    async def _async_announce_track(self):
        ''' announce new tracks '''
        global LASTANNOUNCED  # pylint: disable=global-statement, global-variable-not-assigned

        try:
            self.config.get()

            if self.chat and not self.chat.is_connected():
                logging.error('Twitch chat is not connected. Cannot announce.')
                return

            anntemplate = self.config.cparser.value('twitchbot/announce')
            if not anntemplate:
                logging.debug('No template to announce')
                return

            if not pathlib.Path(anntemplate).exists():
                logging.error('Annoucement template %s does not exist.',
                              anntemplate)
                return

            metadata = await self.metadb.read_last_meta_async()

            if not metadata:
                logging.debug('No metadata to announce')
                return

            # don't announce empty content
            if not metadata['artist'] and not metadata['title']:
                logging.warning(
                    'Both artist and title are empty; skipping announcement')
                return

            if metadata['artist'] == LASTANNOUNCED['artist'] and \
               metadata['title'] == LASTANNOUNCED['title']:
                logging.warning(
                    'Same artist and title or doubled event notification; skipping announcement.'
                )
                return

            LASTANNOUNCED['artist'] = metadata['artist']
            LASTANNOUNCED['title'] = metadata['title']

            await self._delay_write()

            logging.info('Announcing %s',
                         self.config.cparser.value('twitchbot/announce'))

            await self._post_template(template=pathlib.Path(
                self.config.cparser.value('twitchbot/announce')).name)
        except:  #pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)

    async def _post_template(self, msg=None, template=None, moremetadata=None):  #pylint: disable=too-many-branches
        ''' take a template, fill it in, and post it '''
        if not template:
            return
        metadata = await self.metadb.read_last_meta_async()
        if not metadata:
            metadata = {}
        if 'coverimageraw' in metadata:
            del metadata['coverimageraw']
        metadata['cmdtarget'] = None
        metadata['startnewmessage'] = SPLITMESSAGETEXT

        if moremetadata:
            metadata |= moremetadata

        if self.templatedir.joinpath(template).is_file():
            try:
                j2template = self.jinja2.get_template(template)
                message = j2template.render(metadata)
            except Exception as error:  # pylint: disable=broad-except
                logging.error('template %s rendering failure: %s', template,
                              error)
                return

            messages = message.split(SPLITMESSAGETEXT)
            try:
                for content in messages:
                    if not self.chat.is_connected():
                        logging.error(
                            'Twitch chat is not connected. Not sending message.'
                        )
                        return
                    if msg:
                        try:
                            await msg.reply(content)
                        except:  #pylint: disable=bare-except
                            for line in traceback.format_exc().splitlines():
                                logging.error(line)
                            await self.chat.send_message(
                                self.config.cparser.value('twitchbot/channel'),
                                content)
                    else:
                        await self.chat.send_message(
                            self.config.cparser.value('twitchbot/channel'),
                            content)
            except ConnectionResetError:
                logging.debug(
                    'Twitch appears to be down.  Cannot send message.')
            except:  #pylint: disable=bare-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                logging.error('Unknown problem.')

    async def stop(self):
        ''' stop the twitch chat support '''
        if self.watcher:
            self.watcher.stop()
        if self.chat:
            self.chat.stop()
        self.chat = None
        logging.debug('chat stopped')


class TwitchChatSettings:
    ''' for settings UI '''

    def __init__(self):
        self.widget = None
        self.uihelp = None

    def connect(self, uihelp, widget):
        '''  connect twitchbot '''
        self.widget = widget
        self.uihelp = uihelp
        widget.announce_button.clicked.connect(self.on_announce_button)
        widget.add_button.clicked.connect(self.on_add_button)
        widget.del_button.clicked.connect(self.on_del_button)

    @Slot()
    def on_announce_button(self):
        ''' twitchbot announce button clicked action '''
        self.uihelp.template_picker_lineedit(self.widget.announce_lineedit,
                                             limit='twitchbot_*.txt')

    def _twitchbot_command_load(self, command=None, **kwargs):
        if not command:
            return

        row = self.widget.command_perm_table.rowCount()
        self.widget.command_perm_table.insertRow(row)
        cmditem = QTableWidgetItem(command)
        self.widget.command_perm_table.setItem(row, 0, cmditem)

        checkbox = []
        for column, cbtype in enumerate(TWITCHBOT_CHECKBOXES):  # pylint: disable=unused-variable
            checkbox = QCheckBox()
            if cbtype in kwargs:
                checkbox.setChecked(kwargs[cbtype])
            else:
                checkbox.setChecked(True)
            self.widget.command_perm_table.setCellWidget(
                row, column + 1, checkbox)

    @Slot()
    def on_add_button(self):
        ''' twitchbot add button clicked action '''
        filename = self.uihelp.template_picker(limit='twitchbot_*.txt')
        if not filename:
            return

        filename = os.path.basename(filename)
        filename = filename.replace('twitchbot_', '')
        command = filename.replace('.txt', '')

        self._twitchbot_command_load(command)

    @Slot()
    def on_del_button(self):
        ''' twitchbot del button clicked action '''
        if items := self.widget.command_perm_table.selectedIndexes():
            self.widget.command_perm_table.removeRow(items[0].row())

    def load(self, config, widget):
        ''' load the settings window '''

        self.widget = widget

        def clear_table(widget):
            widget.clearContents()
            rows = widget.rowCount()
            for row in range(rows, -1, -1):
                widget.removeRow(row)

        clear_table(widget.command_perm_table)

        for configitem in config.cparser.childGroups():
            setting = {}
            if 'twitchbot-command-' in configitem:
                command = configitem.replace('twitchbot-command-', '')
                setting['command'] = command
                for box in TWITCHBOT_CHECKBOXES:
                    setting[box] = config.cparser.value(f'{configitem}/{box}',
                                                        defaultValue=False,
                                                        type=bool)
                self._twitchbot_command_load(**setting)

        widget.enable_checkbox.setChecked(
            config.cparser.value('twitchbot/chat', type=bool))
        widget.command_perm_table.resizeColumnsToContents()
        widget.announce_lineedit.setText(
            config.cparser.value('twitchbot/announce'))
        widget.commandchar_lineedit.setText(
            config.cparser.value('twitchbot/commandchar'))
        widget.announce_delay_lineedit.setText(
            config.cparser.value('twitchbot/announcedelay'))

    @staticmethod
    def save(config, widget, subprocesses):  #pylint: disable=unused-argument
        ''' update the twitch settings '''

        def reset_commands(widget, config):

            for configitem in config.allKeys():
                if 'twitchbot-command-' in configitem:
                    config.remove(configitem)

            rowcount = widget.rowCount()
            for row in range(rowcount):
                item = widget.item(row, 0)
                cmd = item.text()
                cmd = f'twitchbot-command-{cmd}'
                for column, cbtype in enumerate(TWITCHBOT_CHECKBOXES):
                    item = widget.cellWidget(row, column + 1)
                    value = item.isChecked()
                    config.setValue(f'{cmd}/{cbtype}', value)

        #oldenabled = config.cparser.value('twitchbot/chat', type=bool)
        newenabled = widget.enable_checkbox.isChecked()

        config.cparser.setValue('twitchbot/chat', newenabled)

        config.cparser.setValue('twitchbot/announce',
                                widget.announce_lineedit.text())
        config.cparser.setValue('twitchbot/commandchar',
                                widget.commandchar_lineedit.text())

        config.cparser.setValue('twitchbot/announcedelay',
                                widget.announce_delay_lineedit.text())

        reset_commands(widget.command_perm_table, config.cparser)

    @staticmethod
    def update_twitchbot_commands(config):
        ''' make sure all twitchbot_ files have a config entry '''
        filelist = os.listdir(config.templatedir)
        existing = config.cparser.childGroups()
        alert = False

        for file in filelist:
            if not fnmatch.fnmatch(file, 'twitchbot_*.txt'):
                continue

            command = file.replace('twitchbot_', '').replace('.txt', '')
            command = f'twitchbot-command-{command}'

            if command not in existing:
                alert = True
                logging.debug('creating %s', command)
                for box in TWITCHBOT_CHECKBOXES:
                    config.cparser.setValue(f'{command}/{box}', False)
        if alert and not config.testmode:
            dialog = ChatTemplateUpgradeDialog()
            dialog.exec()

    @staticmethod
    def verify(widget):
        ''' verify the settings are good '''
        char = widget.commandchar_lineedit.text()
        if char and char[0] in ['/', '.']:
            raise PluginVerifyError(
                'Twitch command character cannot start with / or .')


class ChatTemplateUpgradeDialog(QDialog):  # pylint: disable=too-few-public-methods
    ''' Qt Dialog for informing user about template changes '''

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("What's Now Playing Templates")
        dialogbuttons = QDialogButtonBox.Ok
        self.buttonbox = QDialogButtonBox(dialogbuttons)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)
        self.setModal(True)
        self.layout = QVBoxLayout()
        message = QLabel('Twitch Chat permissions have been added or changed.')
        self.layout.addWidget(message)
        self.layout.addWidget(self.buttonbox)
        self.setLayout(self.layout)
