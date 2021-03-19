#!/usr/bin/env python3
'''
    Titles for streaming for Serato
'''

# pylint: disable=no-name-in-module
# pylint: disable=global-statement
# pylint: disable=too-few-public-methods

import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import pathlib
from socketserver import ThreadingMixIn
import sys
import tempfile
import time
import urllib.parse

from PyQt5.QtCore import \
                            pyqtSignal, \
                            QThread
from PyQt5.QtWidgets import \
                            QAction, \
                            QApplication, \
                            QErrorMessage, \
                            QMenu, \
                            QSystemTrayIcon
from PyQt5.QtGui import QIcon

import nowplaying.settingsui
import nowplaying.config
import nowplaying.serato
import nowplaying.utils

__author__ = "Ely Miranda"
__version__ = "1.5.0"
__license__ = "MIT"


# this loglevel should eventually be tied into config
# but for now, hard-set at debug
logging.basicConfig(format='%(asctime)s %(module)s:%(funcName)s:%(lineno)d ' +
                    '%(levelname)s %(message)s',
                    datefmt='%Y-%m-%dT%H:%M:%S%z',
                    filename=os.path.join(tempfile.gettempdir(),
                                          'npsdebug.log'),
                    level=logging.DEBUG)
logging = logging.getLogger(__name__)
logging.info('booting up %s', __version__)

# set paths for bundled files
if getattr(sys, 'frozen', False) and sys.platform == "darwin":
    BUNDLEDIR = os.path.abspath(os.path.dirname(
        sys.executable))  # sys._MEIPASS
else:
    BUNDLEDIR = os.path.abspath(os.path.dirname(__file__))

# define global variables
CURRENTMETA = {'fetchedartist': None, 'fetchedtitle': None}

CONFIG = nowplaying.config.ConfigFile(bundledir=BUNDLEDIR)
QAPP = QApplication([])
QAPP.setOrganizationName('com.github.em1ran')
QAPP.setApplicationName('NowPlaying')
QAPP.setQuitOnLastWindowClosed(False)

TRAY = None


class Tray:  # pylint: disable=too-many-instance-attributes
    ''' System Tray object '''
    def __init__(self):
        global __version__, CONFIG
        logging.debug('Tray is thread %u', QThread.currentThreadId())
        self.settingswindow = nowplaying.settingsui.SettingsUI(
            tray=self, config=CONFIG, version=__version__)
        ''' create systemtray UI '''
        self.icon = QIcon(CONFIG.iconfile)
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.icon)
        self.tray.setToolTip("Now Playing ▶")
        self.tray.setVisible(True)
        self.menu = QMenu()

        # create systemtray options and actions
        self.action_title = QAction(f'Now Playing v{__version__}')
        self.menu.addAction(self.action_title)
        self.action_title.setEnabled(False)

        self.action_config = QAction("Settings")
        self.action_config.triggered.connect(self.settingswindow.show)
        self.menu.addAction(self.action_config)
        self.menu.addSeparator()

        self.action_mixmode = QAction()
        self.action_mixmode.triggered.connect(self.newestmixmode)
        self.menu.addAction(self.action_mixmode)
        self.action_mixmode.setEnabled(False)

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
                self.action_mixmode.setText('Newest')
                self.action_mixmode.setEnabled(True)
            else:
                CONFIG.mixmode = 'newest'
                self.action_mixmode.setEnabled(False)
            self.action_pause.setText('Pause')
            self.action_pause.setEnabled(True)

        self.error_dialog = QErrorMessage()

        # Start the polling thread
        self.trackthread = TrackPoll()
        self.trackthread.currenttrack[dict].connect(self.tracknotify)
        self.trackthread.start()

        # Start the webserver
        self.webthread = WebServer()
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
            self.tray.showMessage('Now Playing ▶ ', tip, 0)

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

    def oldestmixmode(self):
        ''' enable active mixing '''

        global CONFIG

        if not CONFIG.local:
            CONFIG.mixmode = 'newest'
            self.action_mixmode.setEnabled(False)
            self.action_mixmode.setText('Newest')
            self.action_mixmode.triggered.connect(self.oldestmixmode)
            return

        CONFIG.mixmode = 'oldest'
        self.action_mixmode.setText('Newest')
        self.action_mixmode.triggered.connect(self.newestmixmode)

    def newestmixmode(self):
        ''' enable passive mixing '''

        global CONFIG

        if not CONFIG.local:
            CONFIG.mixmode = 'newest'
            self.action_mixmode.setText('Newest')
            self.action_mixmode.triggered.connect(self.oldestmixmode)
            self.action_mixmode.setEnabled(False)
            return

        CONFIG.mixmode = 'newest'
        self.action_mixmode.setText('Oldest')
        self.action_mixmode.triggered.connect(self.oldestmixmode)

    def cleanquit(self):
        ''' quit app and cleanup '''

        global CONFIG

        self.tray.setVisible(False)

        if CONFIG.file:
            nowplaying.utils.writetxttrack(filename=CONFIG.file)
        # calling exit should call __del__ on all of our QThreads
        QAPP.exit(0)


class WebHandler(BaseHTTPRequestHandler):
    ''' Custom handler for built-in webserver '''
    def do_GET(self):  # pylint: disable=invalid-name
        '''
            HTTP GET
                - if there is an index.htm file to read, give it out
                  then delete it
                - if not, have our reader check back in 5 seconds

            Note that there is very specific path information
            handling here.  So any chdir() that happens MUST
            be this directory.

            Also, doing it this way means the webserver can only ever
            share specific content.
        '''

        global CONFIG

        # see what was asked for
        parsedrequest = urllib.parse.urlparse(self.path)

        if parsedrequest.path in ['/favicon.ico']:
            self.send_response(200)
            self.send_header('Content-type', 'image/x-icon')
            self.end_headers()
            with open(CONFIG.iconfile, 'rb') as iconfh:
                self.wfile.write(iconfh.read())
            return

        if parsedrequest.path in ['/', 'index.html', 'index.htm']:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            if os.path.isfile('index.htm'):
                with open('index.htm', 'rb') as indexfh:
                    self.wfile.write(indexfh.read())
                os.unlink('index.htm')
                return

            self.wfile.write(b'<!doctype html><html lang="en">')
            self.wfile.write(
                b'<head><meta http-equiv="refresh" content="5" ></head>')
            self.wfile.write(b'<body></body></html>\n')
            return

        if parsedrequest.path in ['/index.txt']:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            with open(CONFIG.file, 'rb') as textfh:
                self.wfile.write(textfh.read())
            return

        if parsedrequest.path in ['/cover.jpg']:
            if os.path.isfile('cover.jpg'):
                self.send_response(200, 'OK')
                self.send_header('Content-type', 'image/jpeg')
                self.end_headers()
                with open('cover.jpg', 'rb') as indexfh:
                    self.wfile.write(indexfh.read())
                os.unlink('cover.jpg')
                return

        if parsedrequest.path in ['/cover.png']:
            if os.path.isfile('cover.png'):
                self.send_response(200, 'OK')
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                with open('cover.png', 'rb') as indexfh:
                    self.wfile.write(indexfh.read())
                os.unlink('cover.png')
                return

        self.send_error(404)

    def log_message(self, format, *args):  ## pylint: disable=redefined-builtin
        logging.info("%s - - [%s] %s\n", self.address_string(),
                     self.log_date_time_string(), format % args)


class ThreadingWebServer(ThreadingMixIn, HTTPServer):
    ''' threaded webserver object '''
    pass  # pylint: disable=unnecessary-pass


class WebServer(QThread):
    ''' Now Playing built-in web server using custom handler '''

    webenable = pyqtSignal(bool)

    def __init__(self, parent=None):
        QThread.__init__(self, parent)
        self.server = None
        self.prevport = 0
        self.prevdir = None
        self.endthread = False

    def run(self):  # pylint: disable=too-many-branches, too-many-statements
        '''
            Configure a webserver.

            The sleeps are here to make sure we don't
            tie up a CPU constantly checking on
            status.  If we cannot open the port or
            some other situation, we bring everything
            to a halt by triggering pause.

        '''
        global CONFIG
        logging.debug('WebServer is thread %u', QThread.currentThreadId())

        while not CONFIG.httpenabled and not self.endthread and not CONFIG.initialized:
            time.sleep(5)
            CONFIG.get()

        logging.debug('Web server is enabled!')

        while not self.endthread:
            while CONFIG.paused:
                time.sleep(1)

            resetserver = False
            time.sleep(1)
            CONFIG.get()

            if CONFIG.usinghttpdir:
                if CONFIG.usinghttpdir != self.prevdir:
                    logging.debug('Using web server dir %s',
                                  CONFIG.usinghttpdir)
                    self.prevdir = CONFIG.usinghttpdir
                    resetserver = True
            else:
                if not self.prevdir:
                    logging.debug('No web server dir?!?')
                    self.prevdir = tempfile.gettempdir()
                    CONFIG.setusinghttpdir(self.prevdir)

            if not os.path.exists(self.prevdir):
                try:
                    pathlib.Path(self.prevdir).mkdir(parents=True,
                                                     exist_ok=True)
                except Exception as error:  # pylint: disable=broad-except
                    print(f'webserver error: {error}')
                    logging.error('Web server threw exception! %s', error)
                    self.webenable.emit(False)

            os.chdir(self.prevdir)

            if CONFIG.httpport != self.prevport:
                self.prevport = CONFIG.httpport

            if not CONFIG.httpenabled:
                self.stop()
                continue

            if resetserver:
                self.stop()
                time.sleep(5)

            if not self.server:
                try:
                    self.server = ThreadingWebServer(
                        ('0.0.0.0', CONFIG.httpport), WebHandler)
                except Exception as error:  # pylint: disable=broad-except
                    print(f'webserver error: {error}')
                    logging.error('Web server threw exception! %s', error)
                    self.webenable.emit(False)

            try:
                if self.server:
                    self.server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                if self.server:
                    self.server.shutdown()

    def stop(self):
        ''' method to stop the thread '''
        if self.server:
            self.server.shutdown()

    def __del__(self):
        logging.debug('Web server thread is being killed!')
        self.endthread = True
        self.stop()
        self.wait()


class TrackPoll(QThread):
    '''
        QThread that runs the main polling work.
        Uses a signal to tell the Tray when the
        song has changed for notification
    '''

    currenttrack = pyqtSignal(dict)

    def __init__(self, parent=None):
        QThread.__init__(self, parent)
        self.endthread = False

    def run(self):
        ''' track polling process '''

        global CONFIG
        logging.debug('TrackPoll is thread %u', QThread.currentThreadId())
        previoustxttemplate = None
        previoushtmltemplate = None

        # sleep until we have something to write
        while not CONFIG.file and not self.endthread:
            time.sleep(5)
            CONFIG.get()

        while not self.endthread:

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
    (artist, song) = serato.getplayingtrack()

    if not artist and not song:
        logging.debug('getplaying track was None; returning')
        return None

    if artist == CURRENTMETA['fetchedartist'] and \
       song == CURRENTMETA['fetchedtitle']:
        logging.debug('getplaying was existing meta; returning')
        return None

    logging.debug('Fetching more metadata from serato')
    nextmeta = serato.getplayingmetadata()
    nextmeta['fetchedtitle'] = song
    nextmeta['fetchedartist'] = artist

    if 'filename' in nextmeta:
        logging.debug('serato provided filename, parsing file')
        nextmeta = nowplaying.utils.getmoremetadata(nextmeta)

    CURRENTMETA = nextmeta

    return CURRENTMETA


# END FUNCTIONS ####

if __name__ == "__main__":
    TRAY = Tray()
    exitval = QAPP.exec_()
    logging.info('shutting down %s', __version__)
    sys.exit(exitval)
