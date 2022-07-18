#!/usr/bin/env python3
''' thread to poll music player '''

import asyncio
import logging
import pathlib

from PySide6.QtGui import QIcon  # pylint: disable=no-name-in-module

import nowplaying.config
import nowplaying.db
import nowplaying.inputs
import nowplaying.utils

COREMETA = ['artist', 'filename', 'title']


class TrackPoll():  # pylint: disable=too-many-instance-attributes
    ''' handle track changes and update global metadb '''

    # pylint: disable=too-many-arguments
    def __init__(self,
                 event,
                 tray=None,
                 config=None,
                 inputplugin=None,
                 testmode=False):
        self.tray = tray
        self.endthread = False
        self.loop = asyncio.get_running_loop()
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
        self.tasks = set()
        self.create_tasks(event)

    def create_tasks(self, event):
        ''' create the asyncio tasks '''
        task = asyncio.create_task(self.run())
        task.add_done_callback(self.tasks.remove)
        self.tasks.add(task)
        task = asyncio.create_task(self.stopevent(event))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.remove)

    def _resetcurrent(self):
        ''' reset the currentmeta to blank '''
        for key in COREMETA:
            self.currentmeta[f'fetched{key}'] = None

    async def run(self):
        ''' track polling process '''

        previousinput = None

        # sleep until we have something to write
        while not self.config.file and not self.endthread and not self.config.getpause(
        ):
            await asyncio.sleep(5)
            self.config.get()

        while not self.endthread:
            await asyncio.sleep(.5)
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
                await self.gettrack()
            except Exception as error:  #pylint: disable=broad-except
                logging.debug('Failed attempting to get a track: %s',
                              error,
                              exc_info=True)

    async def stopevent(self, event):
        ''' when told of the stop event, shut things down '''
        await event.wait()
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

    async def _fillinmetadata(self, metadata):  # pylint: disable=no-self-use
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
            metadata = nowplaying.utils.getmoremetadata(metadata)

        for key in COREMETA:
            if key not in metadata:
                logging.info('Track missing %s data, setting it to blank.',
                             key)
                metadata[key] = ''
        return metadata

    async def gettrack(self):  # pylint: disable=too-many-branches
        ''' get currently playing track, returns None if not new or not found '''

        # check paused state
        while True:
            if not self.config.getpause() or self.endthread:
                break
            await asyncio.sleep(.5)

        if self.endthread:
            return

        nextmeta = self.input.getplayingtrack()

        if self._ismetaempty(nextmeta):
            return

        if self._ismetasame(nextmeta):
            return

        # fill in the blanks and make it live
        oldmeta = self.currentmeta
        self.currentmeta = await self._fillinmetadata(nextmeta)
        logging.info('Potential new track: %s / %s',
                     self.currentmeta['artist'], self.currentmeta['title'])

        await self._delay_write()

        # checkagain
        nextcheck = self.input.getplayingtrack()
        if not self._ismetaempty(nextcheck) and not self._ismetasame(
                nextcheck):
            logging.info('Track changed during delay, skipping')
            self.currentmeta = oldmeta
            return

        if not self.testmode:
            metadb = nowplaying.db.MetadataDB()
            metadb.write_to_metadb(metadata=self.currentmeta)
        await self._write_to_text()
        await self.tracknotify(self.currentmeta)

    async def _write_to_text(self):
        if not self.previoustxttemplate or self.previoustxttemplate != self.config.txttemplate:
            self.txttemplatehandler = nowplaying.utils.TemplateHandler(
                filename=self.config.txttemplate)
            self.previoustxttemplate = self.config.txttemplate
        nowplaying.utils.writetxttrack(filename=self.config.file,
                                       templatehandler=self.txttemplatehandler,
                                       metadata=self.currentmeta)

    async def _delay_write(self):
        try:
            delay = self.config.cparser.value('settings/delay',
                                              type=float,
                                              defaultValue=1.0)
        except ValueError:
            delay = 1.0
        logging.debug('got delay of %s', delay)
        await asyncio.sleep(delay)

    async def tracknotify(self, metadata):
        ''' signal handler to update the tooltip '''

        self.config.get()
        if self.config.notif:
            icon = QIcon(self.config.iconfile)
            if 'artist' in metadata:
                artist = metadata['artist']
            else:
                artist = ''

            if 'title' in metadata:
                title = metadata['title']
            else:
                title = ''

            tip = f'{artist} - {title}'
            self.tray.setIcon(icon)
            self.tray.showMessage('Now Playing ▶ ', tip, icon)
            self.tray.setIcon(icon)
