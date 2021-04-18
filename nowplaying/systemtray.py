#!/usr/bin/env python3
''' system tray '''

from PySide2.QtWidgets import (  # pylint: disable=no-name-in-module
    QAction, QActionGroup, QApplication, QErrorMessage, QMenu, QSystemTrayIcon)
from PySide2.QtGui import QIcon  # pylint: disable=no-name-in-module

import nowplaying.config
import nowplaying.db
import nowplaying.serato
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
        self.settingswindow = nowplaying.settingsui.SettingsUI(
            tray=self, version=self.version)
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
            if self.config.getmixmode() == 'newest':
                self.action_newestmode.setChecked(True)
            else:
                self.action_oldestmode.setChecked(True)
        else:

            if self.config.local:
                self.action_oldestmode.setCheckable(True)
                if self.config.getmixmode() == 'newest':
                    self.action_newestmode.setChecked(True)
                else:
                    self.action_oldestmode.setChecked(True)
            else:
                self.action_oldestmode.setChecked(False)
                self.action_newestmode.setChecked(True)

            self.action_pause.setText('Pause')
            self.action_pause.setEnabled(True)

        self.error_dialog = QErrorMessage()

        # Start the polling thread
        self.trackthread = nowplaying.trackpoll.TrackPoll()
        self.trackthread.currenttrack[dict].connect(self.tracknotify)
        self.trackthread.start()

        # Start the webserver
        self.webthread = nowplaying.webserver.WebServer()
        self.webthread.webenable[bool].connect(self.webenable)
        self.webthread.start()

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

    def webenable(self, status):
        ''' If the web server gets in trouble, we need to tell the user '''
        if not status:
            self.settingswindow.disable_web()
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

    def oldestmixmode(self):  #pylint: disable=no-self-use
        ''' enable active mixing '''

        self.config.get()
        self.config.setmixmode('oldest')
        self.config.save()

    def newestmixmode(self):  #pylint: disable=no-self-use
        ''' enable passive mixing '''
        self.config.get()
        self.config.setmixmode('newest')
        self.config.save()

    def cleanquit(self):
        ''' quit app and cleanup '''

        self.tray.setVisible(False)
        if self.trackthread:
            self.trackthread.endthread = True
            self.trackthread.exit()
        if self.webthread:
            self.webthread.endthread = True
            self.webthread.stop()
        if self.config:
            self.config.get()
            if self.config.file:
                nowplaying.utils.writetxttrack(filename=self.config.file,
                                               clear=True)
        # calling exit should call __del__ on all of our QThreads
        if self.trackthread:
            self.trackthread.wait()
        if self.webthread:
            self.webthread.wait()
        app = QApplication.instance()
        app.exit(0)
