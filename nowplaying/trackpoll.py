#!/usr/bin/env python3
''' thread to poll music player '''

import importlib
import logging
import pkgutil
import time
import threading

from PySide2.QtCore import Signal, QThread  # pylint: disable=no-name-in-module

import nowplaying.config
import nowplaying.db
import nowplaying.inputs
import nowplaying.utils


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
        self.handler = None
        self.handlername = None
        self.plugins = {}
        self.importplugins()

    def importplugins(self):
        ''' import all of the input plugins '''
        def iter_ns(ns_pkg):
            return pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + ".")

        self.plugins = {
            name: importlib.import_module(name)
            for finder, name, ispkg in iter_ns(nowplaying.inputs)
        }

        logging.info('Plugins: %s ', self.plugins.keys())

    def run(self):
        ''' track polling process '''

        threading.current_thread().name = 'TrackPoll'
        previoustxttemplate = None
        previoushandler = None

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

            if not previoushandler or previoushandler != self.config.cparser.value(
                    'settings/handler'):
                previoushandler = self.config.cparser.value('settings/handler')
                self.handler = self.plugins[
                    f'nowplaying.inputs.{previoushandler}'].Plugin()

            if not self.gettrack():
                continue
            time.sleep(self.config.delay)
            nowplaying.utils.writetxttrack(filename=self.config.file,
                                           templatehandler=txttemplatehandler,
                                           metadata=self.currentmeta)
            self.currenttrack.emit(self.currentmeta)

    def __del__(self):
        logging.debug('TrackPoll is being killed!')
        self.endthread = True

    def gettrack(self):  # pylint: disable=too-many-branches
        ''' get currently playing track, returns None if not new or not found '''

        logging.debug('called gettrack')
        # check paused state
        while True:
            if not self.config.getpause():
                break
            time.sleep(1)

        logging.debug('getplayingtrack called')
        (artist, title) = self.handler.getplayingtrack()

        if not artist and not title:
            logging.debug('getplaying track was None; returning')
            return False

        if artist == self.currentmeta['fetchedartist'] and \
           title == self.currentmeta['fetchedtitle']:
            logging.debug('getplaying was existing meta; returning')
            return False

        logging.debug('Fetching more metadata from serato')
        nextmeta = self.handler.getplayingmetadata()
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
