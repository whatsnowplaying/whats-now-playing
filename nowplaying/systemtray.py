#!/usr/bin/env python3
''' system tray '''

import logging

import multiprocessing

from PySide2.QtWidgets import (  # pylint: disable=no-name-in-module
    QAction, QActionGroup, QApplication, QErrorMessage, QMenu, QSystemTrayIcon)
from PySide2.QtGui import QIcon  # pylint: disable=no-name-in-module

import nowplaying.config
import nowplaying.db
import nowplaying.obsws
import nowplaying.settingsui
import nowplaying.trackpoll
import nowplaying.utils
import nowplaying.version
import nowplaying.webserver


class Tray:  # pylint: disable=too-many-instance-attributes
    ''' System Tray object '''
    def __init__(self):  #pylint: disable=too-many-statements
        self.config = nowplaying.config.ConfigFile()
        self.version = nowplaying.version.get_versions()['version']

        self.icon = QIcon(self.config.iconfile)
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.icon)
        self.tray.setToolTip("Now Playing ▶")
        self.tray.setVisible(True)
        self.menu = QMenu()

        # create systemtray options and actions
        self.action_title = QAction(f'Now Playing v{self.version}')
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
        self.action_oldestmode.setCheckable(False)
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

        self.config.get()
        if not self.config.file:
            self.settingswindow.show()

        else:
            self.action_pause.setText('Pause')
            self.action_pause.setEnabled(True)

        self.fix_mixmode_menu()

        self.error_dialog = QErrorMessage()

        self.trackthread = None
        self.webprocess = None
        self.obswsthread = None
        self.threadstart()

    def threadstart(self):
        ''' start our various threads '''
        # Start the OBS WebSocket thread
        self.obswsthread = nowplaying.obsws.OBSWebSocketHandler()
        self.obswsthread.obswsenable[bool].connect(self.obswsenable)
        self.obswsthread.start()

        # Start the polling thread
        self.trackthread = nowplaying.trackpoll.TrackPoll()
        self.trackthread.currenttrack[dict].connect(self.tracknotify)
        self.trackthread.start()

        if self.config.cparser.value('weboutput/httpenabled', type=bool):
            self._start_webprocess()

    def _stop_webprocess(self):
        ''' stop the web process '''
        if self.webprocess:
            logging.debug('Notifying webserver')
            nowplaying.webserver.stop()
            logging.debug('Waiting for webserver')
            if not self.webprocess.join(20):
                logging.info('Terminating webprocess forcefully')
                self.webprocess.terminate()

    def _start_webprocess(self):
        ''' Start the webserver '''
        logging.info('Starting web process')
        if not self.webprocess:
            app = QApplication.instance()
            self.webprocess = multiprocessing.Process(
                target=nowplaying.webserver.start,
                args=(
                    app.organizationName(),
                    app.applicationName(),
                    self.config.getbundledir(),
                ))
            self.webprocess.start()

    def restart_webprocess(self):
        ''' handle starting or restarting the webserver process '''
        self._stop_webprocess()
        self._start_webprocess()

    def tracknotify(self, metadata):
        ''' signal handler to update the tooltip '''

        self.config.get()
        if self.config.notif:
            if 'artist' in metadata:
                artist = metadata['artist']
            else:
                artist = ''

            if 'title' in metadata:
                title = metadata['title']
            else:
                title = ''

            tip = f'{artist} - {title}'
            self.tray.showMessage('Now Playing ▶ ', tip)
            self.tray.setIcon(self.icon)

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
            self.action_oldestmode.setCheckable(True)

        if 'newest' in validmixmodes:
            self.action_newestmode.setCheckable(True)

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

        if self.obswsthread:
            logging.debug('Notifying obswsthread')
            self.obswsthread.endthread = True
            self.obswsthread.exit()

        if self.trackthread:
            logging.debug('Notifying trackthread')
            self.trackthread.endthread = True
            self.trackthread.exit()

        if self.config:
            self.config.get()
            if self.config.file:
                logging.debug('Writing empty file')
                nowplaying.utils.writetxttrack(filename=self.config.file,
                                               clear=True)

        logging.debug('Shutting down webprocess')
        self._stop_webprocess()

        # calling exit should call __del__ on all of our QThreads
        if self.trackthread:
            logging.debug('Waiting for trackthread')
            self.trackthread.wait()

        if self.obswsthread:
            logging.debug('Waiting for obswsthread')
            self.obswsthread.wait()
        app = QApplication.instance()
        app.exit(0)
