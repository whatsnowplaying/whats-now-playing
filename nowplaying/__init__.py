#!/usr/bin/env python3
'''
    Titles for streaming for Serato
'''

# pylint: disable=no-name-in-module
# pylint: disable=global-statement
# pylint: disable=too-few-public-methods

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

import nowplaying.config
import nowplaying.serato
import nowplaying.settingsui
import nowplaying.utils
import nowplaying.version
import nowplaying.webserver

__version__ = nowplaying.version.get_versions()['version']

QAPP = QApplication(sys.argv)
QAPP.setOrganizationName('com.github.em1ran')
QAPP.setApplicationName('NowPlaying')

# Initialize these later..
BUNDLEDIR = None
TEMPLATEDIR = None
CONFIG = None
CURRENTMETA = None
TRAY = None


class Tray:  # pylint: disable=too-many-instance-attributes
    ''' System Tray object '''
    def __init__(self):  #pylint: disable=too-many-statements
        global CONFIG
        self.version = nowplaying.version.get_versions()['version']
        self.settingswindow = nowplaying.settingsui.SettingsUI(
            tray=self, config=CONFIG, version=self.version)
        self.icon = QIcon(CONFIG.iconfile)
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

        if not CONFIG.file:
            self.settingswindow.show()
        else:

            if CONFIG.local:
                self.action_oldestmode.setCheckable(True)
                if CONFIG.mixmode == 'newest':
                    self.action_newestmode.setChecked(True)
                else:
                    self.action_oldestmode.setChecked(True)
            else:
                CONFIG.mixmode = 'newest'
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
        self.webthread = nowplaying.webserver.WebServer(config=CONFIG)
        self.webthread.webenable[bool].connect(self.webenable)
        self.webthread.start()

    def tracknotify(self, metadata):
        ''' signal handler to update the tooltip '''
        global CONFIG

        if CONFIG.notif:
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
        global CONFIG

        CONFIG.paused = False
        self.action_pause.setText('Pause')
        self.action_pause.triggered.connect(self.pause)

    def pause(self):
        ''' pause polling '''

        global CONFIG
        CONFIG.paused = True
        self.action_pause.setText('Resume')
        self.action_pause.triggered.connect(self.unpause)

    def oldestmixmode(self):  #pylint: disable=no-self-use
        ''' enable active mixing '''
        global CONFIG

        if not CONFIG.local:
            CONFIG.mixmode = 'newest'
            logging.debug('called oldestmixmode, but overrode')
            return

        CONFIG.mixmode = 'oldest'
        CONFIG.save()
        logging.debug('called oldestmixmode')

    def newestmixmode(self):  #pylint: disable=no-self-use
        ''' enable passive mixing '''
        global CONFIG

        CONFIG.mixmode = 'newest'
        CONFIG.save()
        logging.debug('called newestmixmode')

    def cleanquit(self):
        ''' quit app and cleanup '''

        global CONFIG

        self.tray.setVisible(False)
        if self.trackthread:
            self.trackthread.endthread = True
            self.trackthread.exit()
        if self.webthread:
            self.webthread.endthread = True
            self.webthread.stop()
        if CONFIG and CONFIG.file:
            nowplaying.utils.writetxttrack(filename=CONFIG.file, clear=True)
        # calling exit should call __del__ on all of our QThreads
        if self.trackthread:
            self.trackthread.wait()
        if self.webthread:
            self.webthread.wait()
        QAPP.exit(0)


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

    def run(self):
        ''' track polling process '''

        global CONFIG
        threading.current_thread().name = 'TrackPoll'
        previoustxttemplate = None
        previoushtmltemplate = None

        # sleep until we have something to write
        while not CONFIG.file and not self.endthread:
            time.sleep(5)
            CONFIG.get()

        while not self.endthread:
            time.sleep(1)
            CONFIG.get()

            if not previoustxttemplate or previoustxttemplate != CONFIG.txttemplate:
                txttemplatehandler = nowplaying.utils.TemplateHandler(
                    filename=CONFIG.txttemplate)
                previoustxttemplate = CONFIG.txttemplate

            # get poll interval and then poll
            if CONFIG.local:
                interval = 1
            else:
                interval = CONFIG.interval

            time.sleep(interval)
            newmeta = gettrack(CONFIG)
            if not newmeta:
                continue
            time.sleep(CONFIG.delay)
            nowplaying.utils.writetxttrack(filename=CONFIG.file,
                                           templatehandler=txttemplatehandler,
                                           metadata=newmeta)
            self.currenttrack.emit(newmeta)
            if CONFIG.httpenabled:

                if not previoushtmltemplate or previoushtmltemplate != CONFIG.htmltemplate:
                    htmltemplatehandler = nowplaying.utils.TemplateHandler(
                        filename=CONFIG.htmltemplate)
                    previoushtmltemplate = CONFIG.htmltemplate

                nowplaying.utils.update_javascript(
                    serverdir=CONFIG.usinghttpdir,
                    templatehandler=htmltemplatehandler,
                    metadata=newmeta)

    def __del__(self):
        logging.debug('TrackPoll is being killed!')
        self.endthread = True
        self.wait()


# FUNCTIONS ####


def gettrack(configuration):  # pylint: disable=too-many-branches
    ''' get currently playing track, returns None if not new or not found '''
    global CURRENTMETA

    conf = configuration

    serato = None

    logging.debug('called gettrack')
    # check paused state
    while True:
        if not conf.paused:
            break

    if conf.local:  # locally derived
        # paths for session history
        sera_dir = conf.libpath
        hist_dir = os.path.abspath(os.path.join(sera_dir, "History"))
        sess_dir = os.path.abspath(os.path.join(hist_dir, "Sessions"))
        if os.path.isdir(sess_dir):
            logging.debug('SeratoHandler called against %s', sess_dir)
            serato = nowplaying.serato.SeratoHandler(seratodir=sess_dir,
                                                     mixmode=conf.mixmode)
            logging.debug('Serato processor called')
            serato.process_sessions()

    else:  # remotely derived
        logging.debug('SeratoHandler called against %s', conf.url)
        serato = nowplaying.serato.SeratoHandler(seratourl=conf.url)

    if not serato:
        logging.debug('gettrack serato is None; returning')
        return None

    logging.debug('getplayingtrack called')
    (artist, title) = serato.getplayingtrack()

    if not artist and not title:
        logging.debug('getplaying track was None; returning')
        return None

    if artist == CURRENTMETA['fetchedartist'] and \
       title == CURRENTMETA['fetchedtitle']:
        logging.debug('getplaying was existing meta; returning')
        return None

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

    CURRENTMETA = nextmeta
    logging.info('New track: %s / %s', CURRENTMETA['artist'],
                 CURRENTMETA['title'])

    return CURRENTMETA


def setuplogging():
    ''' configure logging '''
    global QAPP

    besuretorotate = False

    logpath = os.path.join(
        QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
        QAPP.applicationName(), 'logs')
    pathlib.Path(logpath).mkdir(parents=True, exist_ok=True)
    logpath = os.path.join(logpath, "debug.log")
    if os.path.exists(logpath):
        besuretorotate = True

    logfhandler = logging.handlers.RotatingFileHandler(filename=logpath,
                                                       backupCount=10,
                                                       encoding='utf-8')
    if besuretorotate:
        logfhandler.doRollover()

    # this loglevel should eventually be tied into config
    # but for now, hard-set at info
    logging.basicConfig(
        format='%(asctime)s %(threadName)s %(module)s:%(funcName)s:%(lineno)d '
        + '%(levelname)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z',
        handlers=[logfhandler],
        level=logging.DEBUG)
    logging.info('starting up v%s',
                 nowplaying.version.get_versions()['version'])


def bootstrap_template_ignore(srcdir, srclist):  # pylint: disable=unused-argument
    ''' do not copy template files that already exist '''
    global TEMPLATEDIR

    ignore = []
    for src in srclist:
        check = os.path.join(TEMPLATEDIR, src)
        if os.path.exists(check):
            ignore.append(src)
        else:
            logging.debug('Adding %s to templates dir', src)

    return ignore


def bootstrap():
    ''' bootstrap the app '''

    global BUNDLEDIR, TEMPLATEDIR, QAPP

    setuplogging()

    TEMPLATEDIR = os.path.join(
        QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
        QAPP.applicationName(), 'templates')

    pathlib.Path(TEMPLATEDIR).mkdir(parents=True, exist_ok=True)
    # set paths for bundled files
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        BUNDLEDIR = getattr(sys, '_MEIPASS',
                            os.path.abspath(os.path.dirname(__file__)))
    else:
        BUNDLEDIR = os.path.abspath(os.path.dirname(__file__))

    bundletemplatedir = os.path.join(BUNDLEDIR, 'templates')

    if os.path.exists(bundletemplatedir):
        shutil.copytree(bundletemplatedir,
                        TEMPLATEDIR,
                        ignore=bootstrap_template_ignore,
                        dirs_exist_ok=True)
    else:
        logging.error('Cannot locate templates dir during bootstrap!')


# END FUNCTIONS ####


def main():
    ''' main entrypoint '''
    global CURRENTMETA, CONFIG, TRAY, QAPP
    # define global variables
    CURRENTMETA = {'fetchedartist': None, 'fetchedtitle': None}

    bootstrap()

    CONFIG = nowplaying.config.ConfigFile(bundledir=BUNDLEDIR)
    logging.getLogger().setLevel(CONFIG.loglevel)

    logging.info('boot up mixmode: %s / local mode: %s ', CONFIG.mixmode,
                 CONFIG.local)

    TRAY = Tray()
    QAPP.setQuitOnLastWindowClosed(False)
    exitval = QAPP.exec_()
    logging.info('shutting down v%s',
                 nowplaying.version.get_versions()['version'])
    sys.exit(exitval)


if __name__ == "__main__":
    main()
