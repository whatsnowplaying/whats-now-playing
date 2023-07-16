#!/usr/bin/env python3
''' djuced support '''

import asyncio
import logging
import pathlib

import sqlite3
import aiosqlite
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import PatternMatchingEventHandler

from PySide6.QtCore import QDir  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin
import nowplaying.utils


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    ''' handler for NowPlaying '''

    metadata = {'artist': None, 'title': None, 'filename': None}
    decktracker = {}

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "DJUCED"
        self.mixmode = "newest"
        self.event_handler = None
        self.observer = None
        self.djuceddir = ''
        self._reset_meta()
        self.tasks = set()

    def install(self):
        ''' locate Virtual DJ '''
        djuceddir = pathlib.Path.home().joinpath('Documents', 'DJUCED')
        if djuceddir.exists():
            self.config.cparser.value('settings/input', 'djuced')
            self.config.cparser.value('djuced/directory', str(djuceddir))
            return True
        return False

    @staticmethod
    def _reset_meta():
        Plugin.metadata = {'artist': None, 'title': None, 'filename': None}

    async def setup_watcher(self, configkey='djuced/directory'):
        ''' set up a custom watch on the m3u dir so meta info
            can update on change'''

        djuceddir = self.config.cparser.value(configkey)
        if not self.djuceddir or self.djuceddir != djuceddir:
            await self.stop()

        if self.observer:
            return

        self.djuceddir = djuceddir
        if not self.djuceddir:
            logging.error('DJUCED Directory Path does not exist: %s', self.djuceddir)
            return

        logging.info('Watching for changes on %s', self.djuceddir)
        self.event_handler = PatternMatchingEventHandler(patterns=['playing.txt'],
                                                         ignore_patterns=['.DS_Store'],
                                                         ignore_directories=True,
                                                         case_sensitive=False)
        self.event_handler.on_modified = self._fs_event
        self.event_handler.on_created = self._fs_event

        if self.config.cparser.value('quirks/pollingobserver', type=bool):
            logging.debug('Using polling observer')
            self.observer = PollingObserver(timeout=5)
        else:
            logging.debug('Using fsevent observer')
            self.observer = Observer()
        self.observer.schedule(self.event_handler, self.djuceddir, recursive=False)
        self.observer.start()

    def _fs_event(self, event):

        if event.is_directory:
            return
        filename = event.src_path
        logging.debug('event type: %s, syn: %s, path: %s', event.event_type, event.is_synthetic,
                      filename)

        deck = self._read_playingtxt()
        if not deck:
            return

        logging.debug('Looking at deck: %s', Plugin.decktracker[deck])
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._get_metadata(deck))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._get_metadata(deck))

    def _read_playingtxt(self):
        txtfile = pathlib.Path(self.djuceddir).joinpath('playing.txt')
        with open(txtfile, encoding='utf-8') as fhin:
            while line := fhin.readline():
                title, deck, artist, album = line.split(' | ')
                album = album.rstrip()
                if Plugin.decktracker.get(deck) and Plugin.decktracker[deck][
                        'title'] == title and Plugin.decktracker[deck]['artist'] == artist:
                    continue
                Plugin.decktracker[deck] = {
                    'title': title,
                    'artist': artist,
                    'album': album,
                }
                return deck
        return None

    async def _try_db(self, deck):
        metadata = {}
        dbfile = pathlib.Path(self.djuceddir).joinpath('DJUCED.db')
        sql = ('SELECT  artist, comment, coverimage, title, bpm, tracknumber, length, absolutepath '
               'FROM tracks WHERE album=? AND artist=? AND title=? '
               'ORDER BY last_played')
        async with aiosqlite.connect(dbfile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            params = (
                Plugin.decktracker[deck]['album'],
                Plugin.decktracker[deck]['artist'],
                Plugin.decktracker[deck]['title'],
            )
            await cursor.execute(sql, params)
            row = await cursor.fetchone()
            await connection.commit()

            if row:
                metadata = {
                    'artist': str(row['artist']),
                    'comment': str(row['comment']),
                    'title': str(row['title']),
                    'bpm': str(row['bpm']),
                    'tracknumber': str(row['tracknumber']),
                    'duration': str(row['length']),
                    'filename': str(row['absolutepath']),
                }
                if row['coverimage']:
                    metadata['rawcoverimage'] = nowplaying.utils.image2png(row['coverimage'])
        return metadata

    # async def _try_songxml(self, deck):
    #     filename = None
    #     xmlfile = pathlib.Path(self.djuceddir).joinpath(f'song{deck}.xml')
    #     with contextlib.suppress(Exception):
    #         root = xml.etree.ElementTree.parse(xmlfile).getroot()
    #         if root.tag == 'song':
    #             filename = root.attrib.get('path')

    #     if not filename or not pathlib.Path(filename).exists():
    #         return {}

    #     # we can get by with a shallow copy
    #     metadata = Plugin.decktracker[deck].copy()
    #     metadata['filename'] = filename
    #     return metadata

    async def _get_metadata(self, deck):
        if metadata := await self._try_db(deck):
            logging.debug('Adding data from db')
            Plugin.metadata = metadata
            return

        # print(f'trying songxml {deck}')
        # if metadata := await self._try_songxml(deck):
        #     Plugin.metadata = metadata
        #     return
        logging.debug('Setting to what we got from playing.txt')
        Plugin.metadata = Plugin.decktracker[deck]

    async def start(self):
        ''' setup the watcher to run in a separate thread '''
        await self.setup_watcher()

    async def getplayingtrack(self):
        ''' wrapper to call getplayingtrack '''

        # just in case called without calling start...
        await self.start()
        return Plugin.metadata

    async def getrandomtrack(self, playlist):
        ''' get a random track '''
        dbfile = pathlib.Path(self.djuceddir).joinpath('DJUCED.db')
        sql = 'SELECT data FROM playlist2 WHERE name=? and type=3 ORDER BY random() LIMIT 1'
        async with aiosqlite.connect(dbfile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            await cursor.execute(sql, (playlist, ))
            row = await cursor.fetchone()
            await connection.commit()
            if not row:
                return None

            return row['filename']

    async def stop(self):
        ''' stop the m3u plugin '''
        self._reset_meta()
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def on_djuced_dir_button(self):
        ''' filename button clicked action'''
        if self.qwidget.dir_lineedit.text():
            startdir = self.qwidget.dir_lineedit.text()
        else:
            startdir = QDir.homePath()
        if dirname := QFileDialog.getExistingDirectory(self.qwidget, 'Select directory', startdir):
            self.qwidget.dir_lineedit.setText(dirname)

    def connect_settingsui(self, qwidget, uihelp):
        ''' connect m3u button to filename picker'''
        self.qwidget = qwidget
        self.uihelp = uihelp
        qwidget.dir_button.clicked.connect(self.on_djuced_dir_button)

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        qwidget.dir_lineedit.setText(self.config.cparser.value('djuced/directory'))

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''
        if not pathlib.Path(qwidget.dir_lineedit.text()).exists():
            raise PluginVerifyError(r'djuced directory must exist.')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        configdir = qwidget.dir_lineedit.text()
        self.config.cparser.setValue('djuced/directory', configdir)

    def desc_settingsui(self, qwidget):
        ''' description '''
        qwidget.setText('DJUCED is DJ software built for the Hercules-series of controllers.')
