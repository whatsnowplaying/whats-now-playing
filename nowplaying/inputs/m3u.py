#!/usr/bin/env python3
''' A _very_ simple and incomplete parser for Serato Live session files '''

import logging
import os
import sys

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from PySide2.QtCore import QCoreApplication, QDir, Qt  # pylint: disable=no-name-in-module
from PySide2.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

from nowplaying.inputs import InputPlugin
import nowplaying.utils

# https://datatracker.ietf.org/doc/html/rfc8216


class Plugin(InputPlugin):
    ''' handler for NowPlaying '''
    def __init__(self, config=None, m3ufile=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)

        self.m3ufile = m3ufile
        self.mixmode = "newest"
        self.event_handler = None
        self.observer = None
        self.metadata = {'artist': None, 'title': None}
        self.qwidget = None

        if not qsettings:
            self._setup_timer()

    def _setup_timer(self):
        if not self.m3ufile:
            self.m3ufile = self.config.cparser.value('m3u/filename')
        logging.info('Watching for changes on %s', self.m3ufile)
        self.event_handler = PatternMatchingEventHandler(
            patterns=[os.path.basename(self.m3ufile)],
            ignore_patterns=None,
            ignore_directories=True,
            case_sensitive=False)
        self.event_handler.on_closed = self._read_track
        self.observer = Observer()
        self.observer.schedule(self.event_handler,
                               os.path.dirname(self.m3ufile),
                               recursive=False)
        self.observer.start()

    def _read_track(self, filename):
        self.metadata = {'artist': None, 'title': None}
        with open(filename, 'r') as m3ufh:
            content = m3ufh.readlines()[-1].rstrip()
        content = content.replace('file://', '')
        if not os.path.exists(content):
            dirpath = os.path.dirname(filename)
            attempt2 = os.path.join(dirpath, content)
            if os.path.exists(attempt2):
                content = attempt2
            else:
                logging.error('Unable to read %s', content)
                return
        logging.debug('Updated m3u file detected')
        self.metadata = {'filename': content}
        self.metadata = nowplaying.utils.getmoremetadata(self.metadata)

    def getplayingtrack(self):
        ''' wrapper to call getplayingtrack '''
        return self.metadata['artist'], self.metadata['title']

    def getplayingmetadata(self):
        ''' wrapper to call getplayingmetadata '''
        return self.metadata

    def defaults(self, qsettings):
        pass

    def validmixmodes(self):
        ''' let the UI know which modes are valid '''
        return ['newest']

    def setmixmode(self, mixmode):
        ''' set the mixmode '''
        return 'newest'

    def getmixmode(self):
        ''' get the mixmode '''
        return 'newest'

    def stop(self):
        ''' stop the m3u plugin '''
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def on_m3u_filename_button(self):
        ''' filename button clicked action'''
        if self.qwidget.filename_lineedit.text():
            startdir = os.path.dirname(self.qwidget.filename_lineedit.text())
        else:
            startdir = QDir.homePath()
        filename = QFileDialog.getOpenFileName(self.qwidget, 'Open file',
                                               startdir, '*.m3u')
        if filename:
            self.qwidget.filename_lineedit.setText(filename[0])

    def connect_settingsui(self, qwidget):
        ''' connect m3u button to filename picker'''
        self.qwidget = qwidget
        qwidget.filename_button.clicked.connect(self.on_m3u_filename_button)

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        qwidget.filename_lineedit.setText(
            self.config.cparser.value('m3u/filename'))

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('m3u/filename',
                                     qwidget.filename_lineedit.text())
        self.m3ufile = None
        self.stop()
        self._setup_timer()

    def desc_settingsui(self, qwidget):
        ''' description '''
        qwidget.setText('M3U is a generic playlist format that is supported '
                        'by a wide variety of tools, including Virtual DJ.')


def main():
    ''' entry point as a standalone app'''

    orgname = 'com.github.em1ran'

    appname = 'NowPlaying'

    bundledir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    QCoreApplication.setOrganizationName(orgname)
    QCoreApplication.setApplicationName(appname)
    # need to make sure config is initialized with something
    config = nowplaying.config.ConfigFile(bundledir=bundledir)
    plugin = Plugin(config=config, m3ufile=sys.argv[1])
    plugin._read_track(sys.argv[1])  # pylint: disable=protected-access
    print('playing track:')
    print(plugin.getplayingtrack())
    print('metadata:')
    print(plugin.getplayingmetadata())


if __name__ == "__main__":
    main()
