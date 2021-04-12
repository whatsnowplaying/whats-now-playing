#!/usr/bin/env python3
'''
    Titles for streaming for Serato
'''

# pylint: disable=no-name-in-module

import logging
import logging.handlers
import os
import pathlib
import shutil
import sys
import threading
import time

from PySide2.QtCore import \
                            Signal, \
                            QCoreApplication, \
                            QStandardPaths, \
                            QThread
from PySide2.QtWidgets import \
                            QAction, \
                            QActionGroup, \
                            QApplication, \
                            QErrorMessage, \
                            QMenu, \
                            QSystemTrayIcon
from PySide2.QtGui import QIcon

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.serato
import nowplaying.settingsui
import nowplaying.utils
import nowplaying.version
import nowplaying.webserver

__version__ = nowplaying.version.get_versions()['version']


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
        self.trackthread = TrackPoll()
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


class TrackPoll(QThread):
    '''
        QThread that runs the main polling work.
        Uses a signal to tell the Tray when the
        song has changed for notification
    '''

    currenttrack = Signal(dict)

    def __init__(self, parent=None):
        QThread.__init__(self, parent)
        self.endthread = False
        self.setObjectName('TrackPoll')
        self.config = nowplaying.config.ConfigFile()
        self.currentmeta = {'fetchedartist': None, 'fetchedtitle': None}

    def run(self):
        ''' track polling process '''

        threading.current_thread().name = 'TrackPoll'
        previoustxttemplate = None
        previoushtmltemplate = None

        # sleep until we have something to write
        while not self.config.file and not self.endthread and not self.config.getpause(
        ):
            time.sleep(5)
            self.config.get()

        while not self.endthread:
            time.sleep(1)
            self.config.get()

            if not previoustxttemplate or previoustxttemplate != self.config.txttemplate:
                txttemplatehandler = nowplaying.utils.TemplateHandler(
                    filename=self.config.txttemplate)
                previoustxttemplate = self.config.txttemplate

            # get poll interval and then poll
            if self.config.local:
                interval = 1
            else:
                interval = self.config.interval

            time.sleep(interval)
            if not self.gettrack():
                continue
            time.sleep(self.config.delay)
            nowplaying.utils.writetxttrack(filename=self.config.file,
                                           templatehandler=txttemplatehandler,
                                           metadata=self.currentmeta)
            self.currenttrack.emit(self.currentmeta)
            if self.config.httpenabled:

                if not previoushtmltemplate or previoushtmltemplate != self.config.htmltemplate:
                    htmltemplatehandler = nowplaying.utils.TemplateHandler(
                        filename=self.config.htmltemplate)
                    previoushtmltemplate = self.config.htmltemplate

                nowplaying.utils.update_javascript(
                    serverdir=self.config.usinghttpdir,
                    templatehandler=htmltemplatehandler,
                    metadata=self.currentmeta)

    def __del__(self):
        logging.debug('TrackPoll is being killed!')
        self.endthread = True

    def gettrack(self):  # pylint: disable=too-many-branches
        ''' get currently playing track, returns None if not new or not found '''
        serato = None

        logging.debug('called gettrack')
        # check paused state
        while True:
            if not self.config.getpause():
                break
            time.sleep(1)

        if self.config.local:  # locally derived
            # paths for session history
            sera_dir = self.config.libpath
            hist_dir = os.path.abspath(os.path.join(sera_dir, "History"))
            sess_dir = os.path.abspath(os.path.join(hist_dir, "Sessions"))
            if os.path.isdir(sess_dir):
                logging.debug('SeratoHandler called against %s', sess_dir)
                serato = nowplaying.serato.SeratoHandler(
                    seratodir=sess_dir, mixmode=self.config.getmixmode())
                logging.debug('Serato processor called')
                serato.process_sessions()

        else:  # remotely derived
            logging.debug('SeratoHandler called against %s', self.config.url)
            serato = nowplaying.serato.SeratoHandler(seratourl=self.config.url)

        if not serato:
            logging.debug('gettrack serato is None; returning')
            return False

        logging.debug('getplayingtrack called')
        (artist, title) = serato.getplayingtrack()

        if not artist and not title:
            logging.debug('getplaying track was None; returning')
            return False

        if artist == self.currentmeta['fetchedartist'] and \
           title == self.currentmeta['fetchedtitle']:
            logging.debug('getplaying was existing meta; returning')
            return False

        logging.debug('Fetching more metadata from serato')
        nextmeta = serato.getplayingmetadata()
        nextmeta['fetchedtitle'] = title
        nextmeta['fetchedartist'] = artist

        if 'filename' in nextmeta:
            logging.debug('serato provided filename, parsing file')
            nextmeta = nowplaying.utils.getmoremetadata(nextmeta)

        # At this point, we have as much data as we can get from
        # either the handler or from reading the file directly.
        # There is still a possibility that artist and title
        # are empty because the user never provided it to anything
        # In this worst case, put in empty strings since
        # everything from here on out will expect them to
        # exist.  If we do not do this, we risk a crash.

        if 'artist' not in nextmeta:
            nextmeta['artist'] = ''
            logging.error('Track missing artist data, setting it to blank.')

        if 'title' not in nextmeta:
            nextmeta['title'] = ''
            logging.error('Track missing title data, setting it to blank.')

        self.currentmeta = nextmeta
        logging.info('New track: %s / %s', self.currentmeta['artist'],
                     self.currentmeta['title'])

        metadb = nowplaying.db.MetadataDB()
        metadb.write_to_metadb(metadata=self.currentmeta)
        return True


def run_bootstrap(bundledir=None):
    ''' bootstrap the app '''

    logpath = os.path.join(
        QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
        QCoreApplication.applicationName(), 'logs')
    pathlib.Path(logpath).mkdir(parents=True, exist_ok=True)
    logpath = os.path.join(logpath, "debug.log")

    nowplaying.bootstrap.setuplogging(logpath=logpath)

    # fail early if metadatadb can't be configured
    metadb = nowplaying.db.MetadataDB()
    metadb.setupsql()

    templatedir = os.path.join(
        QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
        QCoreApplication.applicationName(), 'templates')

    pathlib.Path(templatedir).mkdir(parents=True, exist_ok=True)
    nowplaying.bootstrap.setuptemplates(bundledir=bundledir,
                                        templatedir=templatedir)


def main():
    ''' main entrypoint '''
    # set paths for bundled files
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundledir = getattr(sys, '_MEIPASS',
                            os.path.abspath(os.path.dirname(__file__)))
    else:
        bundledir = os.path.abspath(os.path.dirname(__file__))

    qapp = QApplication(sys.argv)
    qapp.setOrganizationName('com.github.em1ran')
    qapp.setApplicationName('NowPlaying')
    run_bootstrap(bundledir=bundledir)

    config = nowplaying.config.ConfigFile(bundledir=bundledir)
    logging.getLogger().setLevel(config.loglevel)

    logging.info('boot up mixmode: %s / local mode: %s ', config.getmixmode(),
                 config.local)

    tray = Tray()  # pylint: disable=unused-variable
    qapp.setQuitOnLastWindowClosed(False)
    exitval = qapp.exec_()
    logging.info('shutting down v%s',
                 nowplaying.version.get_versions()['version'])
    sys.exit(exitval)


if __name__ == "__main__":
    main()
