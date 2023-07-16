#!/usr/bin/env python3
''' system tray '''

import logging

from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QApplication, QErrorMessage, QMenu, QMessageBox, QSystemTrayIcon)
from PySide6.QtGui import QAction, QActionGroup, QIcon  # pylint: disable=no-name-in-module
from PySide6.QtCore import QFileSystemWatcher  # pylint: disable=no-name-in-module

import nowplaying.config
import nowplaying.db
import nowplaying.settingsui
import nowplaying.subprocesses
import nowplaying.twitch.chat
import nowplaying.trackrequests
import nowplaying.utils

LASTANNOUNCED = {'artist': None, 'title': None}


class Tray:  # pylint: disable=too-many-instance-attributes
    ''' System Tray object '''

    def __init__(self, beam=False):  #pylint: disable=too-many-statements
        self.config = nowplaying.config.ConfigFile(beam=beam)
        self._configure_beamstatus(beam)
        self.icon = QIcon(str(self.config.iconfile))
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.icon)
        self.tray.setToolTip("Now Playing ▶")
        self.tray.setVisible(True)
        self.menu = QMenu()

        # create systemtray options and actions
        self.aboutwindow = nowplaying.settingsui.load_widget_ui(self.config, 'about')
        nowplaying.settingsui.about_version_text(self.config, self.aboutwindow)
        self.about_action = QAction('About What\'s Now Playing')
        self.menu.addAction(self.about_action)
        self.about_action.setEnabled(True)
        self.about_action.triggered.connect(self.aboutwindow.show)

        self.subprocesses = nowplaying.subprocesses.SubprocessManager(self.config)
        self.settingswindow = nowplaying.settingsui.SettingsUI(tray=self, beam=beam)

        self.settings_action = QAction("Settings")
        self.settings_action.triggered.connect(self.settingswindow.show)
        self.menu.addAction(self.settings_action)
        self.request_action = QAction('Requests')
        self.request_action.triggered.connect(self._requestswindow)
        self.request_action.setEnabled(True)
        self.menu.addAction(self.request_action)
        self.menu.addSeparator()

        self.action_newestmode = QAction('Newest')
        self.action_oldestmode = QAction('Oldest')
        self.mixmode_actiongroup = QActionGroup(self.tray)
        self._configure_newold_menu()
        self.menu.addSeparator()

        self.action_pause = QAction()
        self._configure_pause_menu()
        self.menu.addSeparator()

        self.action_exit = QAction("Exit")
        self.action_exit.triggered.connect(self.cleanquit)
        self.menu.addAction(self.action_exit)

        # add menu to the systemtray UI
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.config.get()
        self.installer()
        self.action_pause.setText('Pause')
        self.action_pause.setEnabled(True)
        self.fix_mixmode_menu()

        self.settingswindow.post_tray_init()
        self.subprocesses.start_all_processes()

        # Start the track notify handler
        metadb = nowplaying.db.MetadataDB()
        self.watcher = QFileSystemWatcher()
        self.watcher.addPath(str(metadb.databasefile))
        self.watcher.fileChanged.connect(self.tracknotify)

        self.requestswindow = None
        self._configure_twitchrequests()

    def _configure_beamstatus(self, beam):
        self.config.cparser.setValue('control/beam', beam)
        # these will get filled in by their various subsystems as required
        self.config.cparser.remove('control/beamport')
        self.config.cparser.remove('control/beamserverport')
        self.config.cparser.remove('control/beamservername')
        self.config.cparser.remove('control/beamserverip')

    def _configure_twitchrequests(self):
        self.requestswindow = nowplaying.trackrequests.Requests(config=self.config)
        self.requestswindow.initial_ui()

    def _requestswindow(self):
        if self.config.cparser.value('settings/requests', type=bool):
            self.requestswindow.raise_window()

    def _configure_newold_menu(self):
        self.action_newestmode.setCheckable(True)
        self.action_newestmode.setEnabled(True)
        self.action_oldestmode.setCheckable(True)
        self.action_oldestmode.setEnabled(False)
        self.menu.addAction(self.action_newestmode)
        self.menu.addAction(self.action_oldestmode)
        self.mixmode_actiongroup.addAction(self.action_newestmode)
        self.mixmode_actiongroup.addAction(self.action_oldestmode)
        self.action_newestmode.triggered.connect(self.newestmixmode)
        self.action_oldestmode.triggered.connect(self.oldestmixmode)

    def _configure_pause_menu(self):
        self.action_pause.triggered.connect(self.pause)
        self.menu.addAction(self.action_pause)
        self.action_pause.setEnabled(False)

    def webenable(self, status):
        ''' If the web server gets in trouble, we need to tell the user '''
        if not status:
            self.settingswindow.disable_web()
            self.settingswindow.show()
            self.pause()

    def obswsenable(self, status):
        ''' If the OBS WebSocket gets in trouble, we need to tell the user '''
        if not status:
            self.settingswindow.disable_obsws()
            self.settingswindow.show()
            self.pause()

    def unpause(self):
        ''' unpause polling '''
        self.config.unpause()
        self.action_pause.setText('Pause')
        self.action_pause.triggered.connect(self.pause)

    def pause(self):
        ''' pause polling '''
        self.config.pause()
        self.action_pause.setText('Resume')
        self.action_pause.triggered.connect(self.unpause)

    def fix_mixmode_menu(self):
        ''' update the mixmode based upon current rules '''
        plugins = self.config.cparser.value('settings/input', defaultValue=None)
        if not plugins:
            return

        validmixmodes = self.config.validmixmodes()

        if 'oldest' in validmixmodes:
            self.action_oldestmode.setEnabled(True)
        else:
            self.action_oldestmode.setEnabled(False)

        if 'newest' in validmixmodes:
            self.action_newestmode.setEnabled(True)
        else:
            self.action_newestmode.setEnabled(False)

        if self.config.getmixmode() == 'newest':
            self.action_newestmode.setChecked(True)
            self.action_oldestmode.setChecked(False)
        else:
            self.action_oldestmode.setChecked(True)
            self.action_newestmode.setChecked(False)

    def oldestmixmode(self):
        ''' enable active mixing '''
        self.config.setmixmode('oldest')
        self.fix_mixmode_menu()

    def newestmixmode(self):
        ''' enable passive mixing '''
        self.config.setmixmode('newest')
        self.fix_mixmode_menu()

    def tracknotify(self):  # pylint: disable=unused-argument
        ''' signal handler to update the tooltip '''
        global LASTANNOUNCED  # pylint: disable=global-statement, global-variable-not-assigned

        self.config.get()
        if self.config.notif:
            metadb = nowplaying.db.MetadataDB()
            metadata = metadb.read_last_meta()
            if not metadata:
                return

            # don't announce empty content
            if not metadata['artist'] and not metadata['title']:
                logging.warning('Both artist and title are empty; skipping notify')
                return

            if 'artist' in metadata:
                artist = metadata['artist']
            else:
                artist = ''

            if 'title' in metadata:
                title = metadata['title']
            else:
                title = ''

            if metadata['artist'] == LASTANNOUNCED['artist'] and \
               metadata['title'] == LASTANNOUNCED['title']:
                return

            LASTANNOUNCED['artist'] = metadata['artist']
            LASTANNOUNCED['title'] = metadata['title']

            tip = f'{artist} - {title}'
            self.tray.setIcon(self.icon)
            self.tray.showMessage('Now Playing ▶ ', tip, icon=QSystemTrayIcon.NoIcon)
            self.tray.show()

    def exit_everything(self):
        ''' quit app and cleanup '''

        logging.debug('Starting shutdown')
        if self.requestswindow:
            self.requestswindow.close_window()

        self.action_pause.setEnabled(False)
        self.request_action.setEnabled(False)
        self.action_newestmode.setEnabled(False)
        self.action_oldestmode.setEnabled(False)
        self.settings_action.setEnabled(False)

        self.subprocesses.stop_all_processes()

    def fresh_start_quit(self):
        ''' wipe the current config '''
        self.exit_everything()
        self.config.initialized = False
        self.config.cparser.sync()
        for key in self.config.cparser.allKeys():
            self.config.cparser.remove(key)
        self.config.cparser.sync()

        self._exit_app()

    def cleanquit(self):
        ''' quit app and cleanup '''

        self.exit_everything()
        self.config.get()
        if not self.config.initialized:
            self.config.cparser.clear()
            self.config.cparser.sync()

        self._exit_app()

    def _exit_app(self):
        ''' actually exit '''
        app = QApplication.instance()
        logging.info('shutting qapp down v%s', self.config.version)
        if app:
            app.exit(0)

    def installer(self):
        ''' make some guesses as to what the user needs '''
        plugin = self.config.cparser.value('settings/input', defaultValue=None)
        if plugin and not self.config.validate_source(plugin):
            self.config.cparser.remove('settings/input')
            msgbox = QErrorMessage()
            msgbox.showMessage(f'Configured source {plugin} is not supported. Reconfiguring.')
            msgbox.show()
            msgbox.exec()
        elif not plugin:
            msgbox = QMessageBox()
            msgbox.setText('New installation! Thanks! '
                           'Determining setup. This operation may take a bit!')
            msgbox.show()
            msgbox.exec()
        else:
            return

        plugins = self.config.pluginobjs['inputs']

        for plugin in plugins:
            if plugins[plugin].install():
                self.config.cparser.setValue('settings/input', plugin.split('.')[-1])
                break

        twitchchatsettings = nowplaying.twitch.chat.TwitchChatSettings()
        twitchchatsettings.update_twitchbot_commands(self.config)

        msgbox = QMessageBox()
        msgbox.setText('Basic configuration hopefully in place. '
                       'Bringing up the Settings windows. '
                       ' Please check the Source is correct for'
                       ' your DJ software.')
        msgbox.show()
        msgbox.exec()

        self.settingswindow.show()
