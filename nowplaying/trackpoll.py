#!/usr/bin/env python3
''' thread to poll music player '''

import multiprocessing
import logging
import pathlib
import socket
import threading

from PySide6.QtCore import Signal, QThread  # pylint: disable=no-name-in-module

import nowplaying.config
import nowplaying.db
import nowplaying.inputs
import nowplaying.utils
import nowplaying.imagecache

COREMETA = ['artist', 'filename', 'title']


class TrackPoll(QThread):  # pylint: disable=too-many-instance-attributes
    '''
        QThread that runs the main polling work.
        Uses a signal to tell the Tray when the
        song has changed for notification
    '''

    currenttrack = Signal(dict)

    def __init__(self,
                 config=None,
                 inputplugin=None,
                 testmode=False,
                 parent=None):
        QThread.__init__(self, parent)
        self.endthread = False
        self.setObjectName('TrackPoll')
        if testmode and config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()
        self.currentmeta = {}
        self._resetcurrent()
        self.testmode = testmode
        self.input = inputplugin
        self.inputname = None
        self.plugins = nowplaying.utils.import_plugins(nowplaying.inputs)
        self.previoustxttemplate = None
        self.txttemplatehandler = None
        self.imagecache = None
        self.icprocess = None
        self._setup_imagecache()

    def _resetcurrent(self):
        ''' reset the currentmeta to blank '''
        for key in COREMETA:
            self.currentmeta[f'fetched{key}'] = None

    def run(self):
        ''' track polling process '''

        threading.current_thread().name = 'TrackPoll'
        socket.setdefaulttimeout(5.0)
        previousinput = None

        # sleep until we have something to write
        while not self.config.file and not self.endthread and not self.config.getpause(
        ):
            QThread.msleep(1000)
            self.config.get()

        while not self.endthread:
            QThread.msleep(500)
            self.config.get()

            if not previousinput or previousinput != self.config.cparser.value(
                    'settings/input'):
                previousinput = self.config.cparser.value('settings/input')
                if not self.testmode:
                    self.input = self.plugins[
                        f'nowplaying.inputs.{previousinput}'].Plugin()
                logging.debug('Starting %s plugin', previousinput)
                self.input.start()
            try:
                self.gettrack()
            except Exception as error:  #pylint: disable=broad-except
                logging.debug('Failed attempting to get a track: %s',
                              error,
                              exc_info=True)
        logging.debug('Exited main trackpool loop')
        self.stop()
        logging.debug('Trackpoll stopped gracefully.')

    def __del__(self):
        logging.debug('TrackPoll is being killed!')
        self.stop()

    def stop(self):
        ''' stop trackpoll thread gracefully '''
        logging.debug('Stopping trackpoll')
        if self.icprocess:
            logging.debug('stopping imagecache')
            self.imagecache.stop_process()
            logging.debug('joining imagecache')
            self.icprocess.join()
        if self.input:
            self.input.stop()

        self.endthread = True
        self.plugins = None

    def _check_title_for_path(self, title, filename):
        ''' if title actually contains a filename, move it to filename '''

        if not title:
            return title, filename

        if title == filename:
            return None, filename

        if ('\\' in title or '/' in title) and pathlib.Path(
                nowplaying.utils.songpathsubst(self.config, title)).exists():
            if not filename:
                logging.debug('Copied title to filename')
                filename = title
            logging.debug('Wiping title because it is actually a filename')
            title = None

        return title, filename

    def _ismetaempty(self, metadata):  # pylint: disable=no-self-use
        ''' need at least one value '''

        if not metadata:
            return True

        return not any(key in metadata and metadata[key] for key in COREMETA)

    def _ismetasame(self, metadata):
        ''' same as current check '''
        if not self.currentmeta:
            return False

        for key in COREMETA:
            fetched = f'fetched{key}'
            if key in metadata and fetched in self.currentmeta and metadata[
                    key] != self.currentmeta[fetched]:
                return False
        return True

    def _fillinmetadata(self, metadata):  # pylint: disable=no-self-use
        ''' keep a copy of our fetched data '''

        # Fill in as much metadata as possible. everything
        # after this expects artist, filename, and title are expected to exist
        # so if they don't, make them at least an empty string, keeping what
        # the input actually gave as 'fetched' to compare with what
        # was given before to shortcut all of this work in the future

        for key in COREMETA:
            fetched = f'fetched{key}'
            if key in metadata:
                metadata[fetched] = metadata[key]
            else:
                metadata[fetched] = None

        if metadata.get('title'):
            (metadata['title'],
             metadata['filename']) = self._check_title_for_path(
                 metadata['title'], metadata.get('filename'))

        for key in COREMETA:
            if key in metadata and not metadata[key]:
                del metadata[key]

        if metadata.get('filename'):
            metadata = nowplaying.utils.getmoremetadata(
                metadata, self.imagecache)

        for key in COREMETA:
            if key not in metadata:
                logging.info('Track missing %s data, setting it to blank.',
                             key)
                metadata[key] = ''
        return metadata

    def gettrack(self):  # pylint: disable=too-many-branches
        ''' get currently playing track, returns None if not new or not found '''

        # check paused state
        while self.config.getpause() and not self.endthread:
            QThread.msleep(500)

        if self.endthread:
            return

        nextmeta = self.input.getplayingtrack()

        if self._ismetaempty(nextmeta):
            return

        if self._ismetasame(nextmeta):
            return

        # fill in the blanks and make it live
        oldmeta = self.currentmeta
        self.currentmeta = self._fillinmetadata(nextmeta)
        logging.info('Potential new track: %s / %s',
                     self.currentmeta['artist'], self.currentmeta['title'])

        # try to interleave downloads in-between the delay
        self._half_delay_write()
        self._process_imagecache()
        self._start_artistfanartpool()
        self._half_delay_write()
        self._process_imagecache()
        self._start_artistfanartpool()

        # checkagain
        nextcheck = self.input.getplayingtrack()
        if not self._ismetaempty(nextcheck) and not self._ismetasame(
                nextcheck):
            logging.info('Track changed during delay, skipping')
            self.currentmeta = oldmeta
            return

        self._artfallbacks()

        if not self.testmode:
            metadb = nowplaying.db.MetadataDB()
            metadb.write_to_metadb(metadata=self.currentmeta)
        self._write_to_text()
        self.currenttrack.emit(self.currentmeta)

    def _artfallbacks(self):
        if self.config.cparser.value(
                'artistextras/coverfornologos',
                type=bool) and not self.currentmeta.get(
                    'artistlogoraw') and self.currentmeta.get('coverimageraw'):
            self.currentmeta['artistlogoraw'] = self.currentmeta[
                'coverimageraw']

        if self.config.cparser.value(
                'artistextras/coverfornothumbs', type=bool
        ) and not self.currentmeta.get(
                'artistthumbraw') and self.currentmeta.get('coverimageraw'):
            self.currentmeta['artistthumbraw'] = self.currentmeta[
                'coverimageraw']

    def _write_to_text(self):
        if not self.previoustxttemplate or self.previoustxttemplate != self.config.txttemplate:
            self.txttemplatehandler = nowplaying.utils.TemplateHandler(
                filename=self.config.txttemplate)
            self.previoustxttemplate = self.config.txttemplate
        nowplaying.utils.writetxttrack(filename=self.config.file,
                                       templatehandler=self.txttemplatehandler,
                                       metadata=self.currentmeta)

    def _half_delay_write(self):
        try:
            delay = self.config.cparser.value('settings/delay',
                                              type=float,
                                              defaultValue=1.0)
        except ValueError:
            delay = 1.0
        delay = int(delay * 500)
        logging.debug('got half-delay of %sms', delay)
        QThread.msleep(delay)

    def _setup_imagecache(self):
        if not self.config.cparser.value('artistextras/enabled', type=bool):
            return

        workers = self.config.cparser.value('artistextras/processes', type=int)
        sizelimit = self.config.cparser.value('artistextras/cachesize',
                                              type=int)

        self.imagecache = nowplaying.imagecache.ImageCache(sizelimit=sizelimit)
        self.icprocess = multiprocessing.Process(
            target=self.imagecache.queue_process,
            name='ICProcess',
            args=(
                self.config.logpath,
                workers,
            ))
        self.icprocess.start()

    def _start_artistfanartpool(self):
        if not self.config.cparser.value('artistextras/enabled', type=bool):
            return

        if self.currentmeta.get('artistfanarturls'):
            dedupe = list(dict.fromkeys(self.currentmeta['artistfanarturls']))
            self.currentmeta['artistfanarturls'] = dedupe
            self.imagecache.fill_queue(
                config=self.config,
                artist=self.currentmeta['artist'],
                imagetype='artistfanart',
                urllist=self.currentmeta['artistfanarturls'])
            del self.currentmeta['artistfanarturls']

    def _process_imagecache(self):
        if not self.currentmeta.get('artist'):
            return

        if not self.config.cparser.value('artistextras/enabled', type=bool):
            return

        def fillin(self):
            tryagain = False
            for key in ['artistthumb', 'artistlogo', 'artistbanner']:
                logging.debug('Calling %s', key)
                rawkey = f'{key}raw'
                if not self.currentmeta.get(rawkey):
                    image = self.imagecache.random_image_fetch(
                        artist=self.currentmeta['artist'], imagetype=key)
                    if not image:
                        logging.debug('did not get an image for %s %s %s', key,
                                      rawkey, self.currentmeta['artist'])
                        tryagain = True
                    self.currentmeta[rawkey] = image
            return tryagain

        # try to give it a bit more time if it doesn't complete the first time
        if not fillin(self):
            fillin(self)
