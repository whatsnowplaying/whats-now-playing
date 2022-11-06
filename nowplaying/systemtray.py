#!/usr/bin/env python3
''' system tray '''

import logging
import multiprocessing

from PySide6.QtWidgets import QApplication, QErrorMessage, QMenu, QMessageBox, QSystemTrayIcon  # pylint: disable=no-name-in-module
from PySide6.QtGui import QAction, QActionGroup, QIcon  # pylint: disable=no-name-in-module
from PySide6.QtCore import QFileSystemWatcher  # pylint: disable=no-name-in-module

import nowplaying.config
import nowplaying.db
import nowplaying.obsws
import nowplaying.settingsui
import nowplaying.trackpoll
import nowplaying.twitchbot
import nowplaying.utils
import nowplaying.version
import nowplaying.webserver

LASTANNOUNCED = {'artist': None, 'title': None}


class Tray:  # pylint: disable=too-many-instance-attributes
    ''' System Tray object '''

    def __init__(self):  #pylint: disable=too-many-statements
        self.config = nowplaying.config.ConfigFile()
        self.version = nowplaying.version.get_versions()['version']

        self.icon = QIcon(str(self.config.iconfile))
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.icon)
        self.tray.setToolTip("Now Playing ▶")
        self.tray.setVisible(True)
        self.menu = QMenu()

        # create systemtray options and actions
        self.action_title = QAction(f'What\'s Now Playing v{self.version}')
        self.menu.addAction(self.action_title)
        self.action_title.setEnabled(False)

        self.settingswindow = nowplaying.settingsui.SettingsUI(
            tray=self, version=self.version)

        self.action_config = QAction("Settings")
        self.action_config.triggered.connect(self.settingswindow.show)
        self.menu.addAction(self.action_config)
        self.menu.addSeparator()

        self.action_newestmode = QAction('Newest')
        self.action_newestmode.setCheckable(True)
        self.action_newestmode.setEnabled(True)
        self.action_oldestmode = QAction('Oldest')
        self.action_oldestmode.setCheckable(True)
        self.action_oldestmode.setEnabled(False)
        self.menu.addAction(self.action_newestmode)
        self.menu.addAction(self.action_oldestmode)
        self.mixmode_actiongroup = QActionGroup(self.tray)
        self.mixmode_actiongroup.addAction(self.action_newestmode)
        self.mixmode_actiongroup.addAction(self.action_oldestmode)

        self.action_newestmode.triggered.connect(self.newestmixmode)
        self.action_oldestmode.triggered.connect(self.oldestmixmode)

        self.menu.addSeparator()

        self.action_pause = QAction()
        self.action_pause.triggered.connect(self.pause)
        self.menu.addAction(self.action_pause)
        self.action_pause.setEnabled(False)

        self.menu.addSeparator()

        self.action_exit = QAction("Exit")
        self.action_exit.triggered.connect(self.cleanquit)
        self.menu.addAction(self.action_exit)

        # add menu to the systemtray UI
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.config.get()
        if not self.config.file:
            self.settingswindow.show()

        else:
            self.action_pause.setText('Pause')
            self.action_pause.setEnabled(True)

        self.fix_mixmode_menu()

        self.error_dialog = QErrorMessage()
        self.regular_dialog = QMessageBox()
        self._check_for_upgrade_alert()
        self.watcher = None
        self.trackpoll = None
        self.webprocess = None
        self.obswsobj = None
        self.twitchbotprocess = None
        self.threadstart()

    def _check_for_upgrade_alert(self):
        nowplaying.settingsui.update_twitchbot_commands(self.config)
        if self.config.cparser.value('settings/newtemplates', type=bool):
            self.regular_dialog.setText('Updated templates have been placed.')
            self.config.cparser.setValue('settings/newtemplates', False)
            self.regular_dialog.show()

        if self.config.cparser.value('settings/newtwitchbot', type=bool):
            self.regular_dialog.setText(
                'Twitchbot permissions have been added or changed.')
            self.config.cparser.setValue('settings/newtwitchbot', False)
            self.regular_dialog.show()

    def threadstart(self):
        ''' start our various threads '''

        # Start the polling thread
        self._start_trackpollprocess()

        # Start the OBS WebSocket thread
        self.obswsobj = nowplaying.obsws.OBSWebSocketHandler(tray=self)
        if self.config.cparser.value('obsws/enabled', type=bool):
            self._start_obsws()

        if self.config.cparser.value('weboutput/httpenabled', type=bool):
            self._start_webprocess()

        if self.config.cparser.value('twitchbot/enabled', type=bool):
            self._start_twitchbotprocess()

        metadb = nowplaying.db.MetadataDB()
        self.watcher = QFileSystemWatcher()
        self.watcher.addPath(str(metadb.databasefile))
        self.watcher.fileChanged.connect(self.tracknotify)

    def _start_obsws(self):
        self.obswsobj.start()

    def _stop_obsws(self):
        self.obswsobj.stop()

    def restart_obsws(self):
        ''' bounce the obsws connection '''
        self._stop_obsws()
        self._start_obsws()

    def _stop_trackpollprocess(self):
        ''' stop trackpoll '''
        if self.trackpoll:
            logging.debug('Notifying trackpoll')
            nowplaying.trackpoll.stop(self.trackpoll.pid)
            logging.debug('Waiting for trackpoll')
            if not self.trackpoll.join(5):
                logging.info('Terminating trackpoll forcefully')
                self.trackpoll.terminate()
            self.trackpoll.join(5)
            self.trackpoll.close()
            self.trackpoll = None

    def _start_trackpollprocess(self):
        ''' Start trackpoll '''
        if not self.trackpoll:
            logging.info('Starting trackpoll')
            bundledir = self.config.getbundledir()
            self.trackpoll = multiprocessing.Process(
                target=nowplaying.trackpoll.start,
                name='TrackProcess',
                args=(
                    bundledir,
                    False,
                ))
            self.trackpoll.start()

    def _stop_webprocess(self):
        ''' stop the web process '''
        if self.webprocess:
            logging.debug('Notifying webserver')
            nowplaying.webserver.stop(self.webprocess.pid)
            logging.debug('Waiting for webserver')
            if not self.webprocess.join(5):
                logging.info('Terminating webprocess forcefully')
                self.webprocess.terminate()
            self.webprocess.join(5)
            self.webprocess.close()
            self.webprocess = None

    def _start_webprocess(self):
        ''' Start the webserver '''
        if not self.webprocess and self.config.cparser.value(
                'weboutput/httpenabled', type=bool):
            logging.info('Starting web process')
            bundledir = self.config.getbundledir()
            self.webprocess = multiprocessing.Process(
                target=nowplaying.webserver.start,
                name='WebProcess',
                args=(bundledir, ))
            self.webprocess.start()

    def _stop_twitchbotprocess(self):
        ''' stop the twitchbot process '''
        if self.twitchbotprocess:
            logging.debug('Notifying twitchbot')
            nowplaying.twitchbot.stop(self.twitchbotprocess.pid)
            logging.debug('Waiting for twitchbot')
            if not self.twitchbotprocess.join(5):
                logging.info('Terminating twitchbot forcefully')
                self.twitchbotprocess.terminate()
            self.twitchbotprocess.join(5)
            self.twitchbotprocess.close()
            self.twitchbotprocess = None

    def _start_twitchbotprocess(self):
        ''' Start the twitchbot '''
        logging.info('Starting twitchbot')
        if not self.twitchbotprocess and self.config.cparser.value(
                'twitchbot/enabled', type=bool):
            bundledir = self.config.getbundledir()
            logpath = self.config.logpath
            self.twitchbotprocess = multiprocessing.Process(
                target=nowplaying.twitchbot.start,
                name='TwitchProcess',
                args=(
                    logpath,
                    bundledir,
                ))
            self.twitchbotprocess.start()

    def restart_trackpoll(self):
        ''' handle starting or restarting the webserver process '''
        self._stop_trackpollprocess()
        self._start_trackpollprocess()

    def restart_webprocess(self):
        ''' handle starting or restarting the webserver process '''
        self._stop_webprocess()
        self._start_webprocess()

    def restart_twitchbotprocess(self):
        ''' handle starting or restarting the webserver process '''
        self._stop_twitchbotprocess()
        self._start_twitchbotprocess()

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
                logging.warning(
                    'Both artist and title are empty; skipping notify')
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
            self.tray.showMessage('Now Playing ▶ ',
                                  tip,
                                  icon=QSystemTrayIcon.NoIcon)
            self.tray.show()

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

    def oldestmixmode(self):  #pylint: disable=no-self-use
        ''' enable active mixing '''
        self.config.setmixmode('oldest')
        self.fix_mixmode_menu()

    def newestmixmode(self):  #pylint: disable=no-self-use
        ''' enable passive mixing '''
        self.config.setmixmode('newest')
        self.fix_mixmode_menu()

    def cleanquit(self):
        ''' quit app and cleanup '''

        logging.debug('Starting shutdown')
        self.tray.setVisible(False)

        logging.debug('Notifying obswsobj')
        self._stop_obsws()

        self._stop_trackpollprocess()

        if self.config:
            self.config.get()
            if self.config.file:
                logging.debug('Writing empty file')
                nowplaying.utils.writetxttrack(filename=self.config.file,
                                               clear=True)

        logging.debug('Shutting down webprocess')
        self._stop_webprocess()
        self._stop_twitchbotprocess()

        app = QApplication.instance()
        app.exit(0)
