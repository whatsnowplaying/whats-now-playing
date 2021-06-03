#!/usr/bin/env python3
''' A _very_ simple and incomplete parser for Serato Live session files '''

import logging
import os
import sys

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from PySide2.QtCore import QDir  # pylint: disable=no-name-in-module
from PySide2.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

from nowplaying.inputs import InputPlugin
from nowplaying.exceptions import PluginVerifyError
import nowplaying.bootstrap
import nowplaying.utils

# https://datatracker.ietf.org/doc/html/rfc8216


class Plugin(InputPlugin):
    ''' handler for NowPlaying '''

    metadata = {'artist': None, 'title': None}

    def __init__(self, config=None, m3udir=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)

        self.m3udir = m3udir
        self.mixmode = "newest"
        self.event_handler = None
        self.observer = None
        self.qwidget = None

        if not qsettings:
            self._setup_watcher()

    def _setup_watcher(self):
        if not self.m3udir:
            self.m3udir = self.config.cparser.value('m3u/directory')

        if not self.m3udir:
            logging.error('M3U Directory Path does not exist: %s', self.m3udir)
            return

        logging.info('Watching for changes on %s', self.m3udir)
        self.event_handler = PatternMatchingEventHandler(
            patterns=['*.m3u'],
            ignore_patterns=['.DS_Store'],
            ignore_directories=True,
            case_sensitive=False)
        self.event_handler.on_modified = self._read_track
        self.event_handler.on_created = self._read_track
        self.observer = Observer()
        self.observer.schedule(self.event_handler,
                               self.m3udir,
                               recursive=False)
        self.observer.start()

    def _read_track(self, event):  #pylint: disable=no-self-use

        if event.is_directory:
            return

        filename = event.src_path
        logging.debug('got %s', filename)
        with open(filename, 'r', errors='ignore') as m3ufh:
            content = m3ufh.readlines()[-1]

        logging.debug('attempting to read %s', content)
        content = content.rstrip()
        content = content.replace('file://', '')
        if not os.path.exists(content):
            dirpath = os.path.dirname(filename)
            attempt2 = os.path.join(dirpath, content)
            if os.path.exists(attempt2):
                content = attempt2
            else:
                logging.error('Unable to read %s', content)
                return
        newmeta = {'filename': content}
        newmeta = nowplaying.utils.getmoremetadata(newmeta)
        if 'artist' not in newmeta:
            newmeta['artist'] = None
        if 'title' not in newmeta:
            newmeta['title'] = None
        Plugin.metadata = newmeta

    def getplayingtrack(self):  #pylint: disable=no-self-use
        ''' wrapper to call getplayingtrack '''
        return Plugin.metadata['artist'], Plugin.metadata['title']

    def getplayingmetadata(self):  #pylint: disable=no-self-use
        ''' wrapper to call getplayingmetadata '''
        return Plugin.metadata

    def defaults(self, qsettings):  #pylint: disable=no-self-use
        pass

    def validmixmodes(self):  #pylint: disable=no-self-use
        ''' let the UI know which modes are valid '''
        return ['newest']

    def setmixmode(self, mixmode):  #pylint: disable=no-self-use
        ''' set the mixmode '''
        return 'newest'

    def getmixmode(self):  #pylint: disable=no-self-use
        ''' get the mixmode '''
        return 'newest'

    def stop(self):
        ''' stop the m3u plugin '''
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def on_m3u_dir_button(self):
        ''' filename button clicked action'''
        if self.qwidget.dir_lineedit.text():
            startdir = self.qwidget.dir_lineedit.text()
        else:
            startdir = QDir.homePath()
        dirname = QFileDialog.getExistingDirectory(self.qwidget,
                                                   'Select directory',
                                                   startdir)
        if dirname:
            self.qwidget.dir_lineedit.setText(dirname)

    def connect_settingsui(self, qwidget):
        ''' connect m3u button to filename picker'''
        self.qwidget = qwidget
        qwidget.dir_button.clicked.connect(self.on_m3u_dir_button)

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        qwidget.dir_lineedit.setText(
            self.config.cparser.value('m3u/directory'))

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''
        if not os.path.exists(qwidget.dir_lineedit.text()):
            raise PluginVerifyError(r'm3u directory must exist.')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('m3u/directory',
                                     qwidget.dir_lineedit.text())
        self.m3udir = None
        self.stop()
        self._setup_watcher()

    def desc_settingsui(self, qwidget):
        ''' description '''
        qwidget.setText('M3U is a generic playlist format that is supported '
                        'by a wide variety of tools, including Virtual DJ.')


def main():
    ''' entry point as a standalone app'''

    logging.basicConfig(level=logging.DEBUG)

    bundledir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    nowplaying.bootstrap.set_qt_names()

    # need to make sure config is initialized with something
    config = nowplaying.config.ConfigFile(bundledir=bundledir)
    plugin = Plugin(config=config, m3udir=os.path.dirname(sys.argv[1]))
    plugin._read_track(sys.argv[1])  # pylint: disable=protected-access
    print('playing track:')
    print(plugin.getplayingtrack())
    print('metadata:')
    metadata = plugin.getplayingmetadata()
    if 'coverimageraw' in metadata:
        print('got image')
        del metadata['coverimageraw']
    print(metadata)


if __name__ == "__main__":
    main()
