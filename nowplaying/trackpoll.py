#!/usr/bin/env python3
''' thread to poll music player '''

import logging
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
        self.input = None
        self.inputname = None
        self.plugins = nowplaying.utils.import_plugins(nowplaying.inputs)

    def run(self):
        ''' track polling process '''

        threading.current_thread().name = 'TrackPoll'
        previoustxttemplate = None
        previousinput = None

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

            if not previousinput or previousinput != self.config.cparser.value(
                    'settings/input'):
                previousinput = self.config.cparser.value('settings/input')
                self.input = self.plugins[
                    f'nowplaying.inputs.{previousinput}'].Plugin()

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
        self.plugins = None

    def gettrack(self):  # pylint: disable=too-many-branches
        ''' get currently playing track, returns None if not new or not found '''

        #logging.debug('called gettrack')
        # check paused state
        while True:
            if not self.config.getpause():
                break
            time.sleep(1)

        (artist, title) = self.input.getplayingtrack()

        if not artist and not title:
            return False

        if artist == self.currentmeta['fetchedartist'] and \
           title == self.currentmeta['fetchedtitle']:
            return False

        nextmeta = self.input.getplayingmetadata()
        nextmeta['fetchedtitle'] = title
        nextmeta['fetchedartist'] = artist

        if 'filename' in nextmeta:
            nextmeta = nowplaying.utils.getmoremetadata(nextmeta)

        # At this point, we have as much data as we can get from
        # either the input or from reading the file directly.
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
