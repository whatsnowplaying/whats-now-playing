#!/usr/bin/env python3
''' thread to poll music player '''
import asyncio
import multiprocessing
import logging
import os
import pathlib
import signal
import socket
import threading
import time
import traceback
import sys

import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.imagecache
import nowplaying.inputs
import nowplaying.metadata
import nowplaying.pluginimporter
import nowplaying.trackrequests
import nowplaying.textoutput
import nowplaying.utils

COREMETA = ['artist', 'filename', 'title']


class TrackPoll():  # pylint: disable=too-many-instance-attributes
    '''
        Do the heavy lifting of reading from the DJ software
    '''

    def __init__(self, stopevent=None, config=None, testmode=False):
        self.datestr = time.strftime("%Y%m%d-%H%M%S")
        self.stopevent = stopevent
        # we can't use asyncio's because it doesn't work on Windows
        signal.signal(signal.SIGINT, self.forced_stop)
        if testmode and config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()
        self.currentmeta = {}
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
        self._resetcurrent()
        self.testmode = testmode
        self.input = None
        self.previousinput = None
        self.inputname = None
        self.plugins = nowplaying.pluginimporter.import_plugins(nowplaying.inputs)
        self.previoustxttemplate = None
        self.txttemplatehandler = None
        self.imagecache = None
        self.icprocess = None
        self.trackrequests = None
        if not self.config.cparser.value('control/beam', type=bool):
            self._setup_imagecache()
            self.trackrequests = nowplaying.trackrequests.Requests(config=self.config,
                                                                   stopevent=self.stopevent)
            self.trackrequests.clear_roulette_artist_dupes()

        self.tasks = set()
        nowplaying.textoutput.deltxttrack(self.config)
        self.metadataprocessors = nowplaying.metadata.MetadataProcessors(config=self.config)
        self.create_tasks()
        if not testmode:
            self.loop.run_forever()

    def _resetcurrent(self):
        ''' reset the currentmeta to blank '''
        for key in COREMETA:
            self.currentmeta[f'fetched{key}'] = None

    def create_tasks(self):
        ''' create the asyncio tasks '''
        task = self.loop.create_task(self.run())
        task.add_done_callback(self.tasks.remove)
        self.tasks.add(task)
        if self.trackrequests:
            task = self.loop.create_task(self.trackrequests.watch_for_respin(self.stopevent))
            task.add_done_callback(self.tasks.remove)
            self.tasks.add(task)
        if self.imagecache:
            task = self.loop.create_task(self.imagecache.verify_cache_timer(self.stopevent))
            task.add_done_callback(self.tasks.remove)
            self.tasks.add(task)

    async def switch_input_plugin(self):
        ''' handle user switching source input while running '''
        if not self.previousinput or self.previousinput != self.config.cparser.value(
                'settings/input'):
            if self.input:
                logging.info('stopping %s', self.previousinput)
                await self.input.stop()
            self.previousinput = self.config.cparser.value('settings/input')
            self.input = self.plugins[f'nowplaying.inputs.{self.previousinput}'].Plugin(
                config=self.config)
            logging.info('Starting %s plugin', self.previousinput)
            if not self.input:
                return False

            try:
                await self.input.start()
            except Exception as error:  # pylint: disable=broad-except
                logging.error('cannot start %s: %s', self.previousinput, error)
                return False

        return True

    async def run(self):
        ''' track polling process '''

        threading.current_thread().name = 'TrackPoll'
        socket.setdefaulttimeout(5.0)

        if not self.config.cparser.value('settings/input', defaultValue=None):
            logging.debug('Waiting for user to configure source input.')

        # sleep until we have something to do
        while not self.stopevent.is_set() and not self.config.getpause(
        ) and not self.config.cparser.value('settings/input', defaultValue=None):
            await asyncio.sleep(.5)
            self.config.get()

        while not self.stopevent.is_set():
            await asyncio.sleep(.5)
            self.config.get()

            if not await self.switch_input_plugin():
                continue

            try:
                await self.gettrack()
            except Exception as error:  #pylint: disable=broad-except
                logging.error('Failed attempting to get a track: %s', error, exc_info=True)

        if not self.testmode and self.config.cparser.value('setlist/enabled', type=bool):
            nowplaying.db.create_setlist(self.config)
        await self.stop()
        logging.debug('Trackpoll stopped gracefully.')

    async def stop(self):
        ''' stop trackpoll thread gracefully '''
        logging.debug('Stopping trackpoll')
        self.stopevent.set()
        if self.icprocess:
            logging.debug('stopping imagecache')
            self.imagecache.stop_process()
            logging.debug('joining imagecache')
            self.icprocess.join()
        if self.input:
            await self.input.stop()
        self.plugins = None
        loop = asyncio.get_running_loop()
        if not self.testmode:
            loop.stop()

    def forced_stop(self, signum, frame):  # pylint: disable=unused-argument
        ''' caught an int signal so tell the world to stop '''
        self.stopevent.set()

    def _verify_filename(self, metadata):
        ''' verify filename actual exists and/or needs path substitution '''
        if metadata.get('filename'):
            filepath = pathlib.Path(metadata['filename'])
            if not filepath.exists():
                metadata['filename'] = nowplaying.utils.songpathsubst(self.config,
                                                                      metadata['filename'])
                filepath = pathlib.Path(metadata['filename'])
                if not filepath.exists():
                    logging.error('cannot find %s; removing from metadata', metadata['filename'])
                    del metadata['filename']
        return metadata

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

    @staticmethod
    def _ismetaempty(metadata):
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

    @staticmethod
    def _isignored(metadata):
        ''' bail out if the text NPIGNORE appears in the comment field '''
        if metadata.get('comments') and 'NPIGNORE' in metadata['comments']:
            return True
        return False

    async def checkskip(self, nextmeta):
        ''' check if this metadata is meant to be skipped '''
        for skiptype in ['comment', 'genre']:
            skipdata = self.config.cparser.value(f'trackskip/{skiptype}', defaultValue=None)
            if not skipdata:
                continue
            if skipdata in nextmeta.get(skiptype, ''):
                return True
        return False

    async def _fillinmetadata(self, metadata):
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

        if metadata.get('filename'):
            metadata = self._verify_filename(metadata)

        if metadata.get('title'):
            (metadata['title'],
             metadata['filename']) = self._check_title_for_path(metadata['title'],
                                                                metadata.get('filename'))

        for key in COREMETA:
            if key in metadata and not metadata[key]:
                del metadata[key]

        try:
            metadata = await self.metadataprocessors.getmoremetadata(metadata=metadata,
                                                                     imagecache=self.imagecache)
            if duration := metadata.get('duration'):
                metadata['duration_hhmmss'] = nowplaying.utils.humanize_time(duration)
        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            logging.error('Ignoring metadataprocessor failure.')

        for key in COREMETA:
            if key not in metadata:
                logging.info('Track missing %s data, setting it to blank.', key)
                metadata[key] = ''
        return metadata

    async def gettrack(self):  # pylint: disable=too-many-branches,
        ''' get currently playing track, returns None if not new or not found '''

        # check paused state
        while self.config.getpause() and not self.stopevent.is_set():
            await asyncio.sleep(.5)

        if self.stopevent.is_set():
            return

        try:
            nextmeta = await self.input.getplayingtrack()
        except:  #pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            await asyncio.sleep(5)
            return

        if self._ismetaempty(nextmeta) or self._ismetasame(nextmeta) or self._isignored(nextmeta):
            return

        # fill in the blanks and make it live
        oldmeta = self.currentmeta
        try:
            self.currentmeta = await self._fillinmetadata(nextmeta)
        except:  #pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            await asyncio.sleep(5)
            logging.error('Ignoring the crash and just keep going!')
            self.currentmeta = nextmeta

        logging.info('Potential new track: %s / %s', self.currentmeta['artist'],
                     self.currentmeta['title'])

        if await self.checkskip(nextmeta):
            logging.info('Skipping %s / %s', self.currentmeta['artist'], self.currentmeta['title'])
            return

        # try to interleave downloads in-between the delay
        await self._half_delay_write()
        await self._process_imagecache()
        self._start_artistfanartpool()
        await self._half_delay_write()
        await self._process_imagecache()
        self._start_artistfanartpool()

        # checkagain
        nextcheck = await self.input.getplayingtrack()
        if not self._ismetaempty(nextcheck) and not self._ismetasame(nextcheck):
            logging.info('Track changed during delay, skipping')
            self.currentmeta = oldmeta
            return

        if self.config.cparser.value(
                'settings/requests',
                type=bool) and not self.config.cparser.value('control/beam', type=bool):
            if data := await self.trackrequests.get_request(self.currentmeta):
                self.currentmeta.update(data)

        self._artfallbacks()

        if not self.testmode:
            metadb = nowplaying.db.MetadataDB()
            await metadb.write_to_metadb(metadata=self.currentmeta)
        self._write_to_text()

    def _artfallbacks(self):
        if self.config.cparser.value(
                'artistextras/coverfornologos', type=bool
        ) and not self.currentmeta.get('artistlogoraw') and self.currentmeta.get('coverimageraw'):
            self.currentmeta['artistlogoraw'] = self.currentmeta['coverimageraw']

        if self.config.cparser.value(
                'artistextras/coverfornothumbs', type=bool
        ) and not self.currentmeta.get('artistthumbraw') and self.currentmeta.get('coverimageraw'):
            self.currentmeta['artistthumbraw'] = self.currentmeta['coverimageraw']

    def _write_to_text(self):
        if configfile := self.config.cparser.value('textoutput/file'):
            if configtemplate := self.config.cparser.value('textoutput/txttemplate'):
                if not self.previoustxttemplate or self.previoustxttemplate != configtemplate:
                    self.txttemplatehandler = nowplaying.utils.TemplateHandler(
                        filename=configtemplate)
                    self.previoustxttemplate = configtemplate
                nowplaying.textoutput.writetxttrack(config=self.config,
                                                    filename=configfile,
                                                    templatehandler=self.txttemplatehandler,
                                                    metadata=self.currentmeta)

    async def _half_delay_write(self):
        try:
            delay = self.config.cparser.value('settings/delay', type=float, defaultValue=1.0)
        except ValueError:
            delay = 1.0
        delay /= 2
        logging.debug('got half-delay of %ss', delay)
        await asyncio.sleep(delay)

    def _setup_imagecache(self):
        if not self.config.cparser.value('artistextras/enabled', type=bool):
            return

        workers = self.config.cparser.value('artistextras/processes', type=int)
        sizelimit = self.config.cparser.value('artistextras/cachesize', type=int)

        self.imagecache = nowplaying.imagecache.ImageCache(sizelimit=sizelimit,
                                                           stopevent=self.stopevent)
        self.config.cparser.setValue('artistextras/cachedbfile', self.imagecache.databasefile)
        self.icprocess = multiprocessing.Process(target=self.imagecache.queue_process,
                                                 name='ICProcess',
                                                 args=(
                                                     self.config.logpath,
                                                     workers,
                                                 ))
        self.icprocess.start()

    def _start_artistfanartpool(self):
        if not self.config.cparser.value('artistextras/enabled',
                                         type=bool) or self.config.cparser.value('control/beam',
                                                                                 type=bool):
            return

        if self.currentmeta.get('artistfanarturls'):
            dedupe = list(dict.fromkeys(self.currentmeta['artistfanarturls']))
            self.currentmeta['artistfanarturls'] = dedupe
            self.imagecache.fill_queue(config=self.config,
                                       artist=self.currentmeta['artist'],
                                       imagetype='artistfanart',
                                       urllist=self.currentmeta['artistfanarturls'])
            del self.currentmeta['artistfanarturls']

    async def _process_imagecache(self):
        if not self.currentmeta.get('artist') or self.config.cparser.value(
                'control/beam',
                type=bool) or not self.config.cparser.value('artistextras/enabled', type=bool):
            return

        def fillin(self):
            tryagain = False

            if not self.imagecache:
                logging.debug('Artist Extras was enabled without restart; skipping image downloads')
                return True

            for key in ['artistthumb', 'artistlogo', 'artistbanner']:
                logging.debug('Calling %s', key)
                rawkey = f'{key}raw'
                if not self.currentmeta.get(rawkey):
                    image = self.imagecache.random_image_fetch(artist=self.currentmeta['artist'],
                                                               imagetype=key)
                    if not image:
                        logging.debug('did not get an image for %s %s %s', key, rawkey,
                                      self.currentmeta['artist'])
                        tryagain = True
                    self.currentmeta[rawkey] = image
            return tryagain

        # try to give it a bit more time if it doesn't complete the first time
        if not fillin(self):
            fillin(self)


def stop(pid):
    ''' stop the web server -- called from Tray '''
    logging.info('sending INT to %s', pid)
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        pass


def start(stopevent, bundledir, testmode=False):  #pylint: disable=unused-argument
    ''' multiprocessing start hook '''
    threading.current_thread().name = 'TrackPoll'

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
    else:
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname='debug.log', rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir, logpath=logpath, testmode=testmode)
    try:
        TrackPoll(  # pylint: disable=unused-variable
            stopevent=stopevent,
            config=config,
            testmode=testmode)
    except Exception as error:  #pylint: disable=broad-except
        logging.error('TrackPoll crashed: %s', error, exc_info=True)
        sys.exit(1)
    logging.info('shutting down trackpoll v%s', config.version)
