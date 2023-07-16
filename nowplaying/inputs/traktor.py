#!/usr/bin/env python3
''' Traktor-specific support '''

import os
import pathlib
import logging
import logging.config
import sqlite3
import xml.etree.ElementTree

import aiosqlite  # pylint: disable=import-error

from PySide6.QtCore import QStandardPaths  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=import-error, no-name-in-module

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

# pylint: disable=wrong-import-position

from nowplaying.db import LISTFIELDS
from nowplaying.exceptions import PluginVerifyError
from .icecast import Plugin as IcecastPlugin

METADATALIST = ['artist', 'title', 'album', 'key', 'filename', 'bpm']

PLAYLIST = ['name', 'filename']


class Traktor:
    ''' data from the traktor collections.nml file '''

    def __init__(self, config=None):
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]).joinpath(
                'traktor', 'traktor.db')
        self.database = None
        self.config = config

    def initdb(self):
        ''' initialize the db '''
        if not self.databasefile.exists():
            self.rewrite_db()

    @staticmethod
    def _write_playlist(sqlcursor, traktortree):
        ''' take the collections XML and save the playlists off '''
        for subnode in traktortree.iterfind('PLAYLISTS/NODE/SUBNODES'):
            for node in subnode:
                playlist = node.get('NAME')
                for tracks in node:
                    for keys in tracks:
                        for primarykey in keys:
                            filepathcomps = primarykey.attrib['KEY'].split('/:')
                            filename = str(pathlib.Path('/').joinpath(*filepathcomps[1:]))
                            sql = 'INSERT INTO playlists (name,filename) VALUES (?,?)'
                            datatuple = playlist, filename
                            sqlcursor.execute(sql, datatuple)

    @staticmethod
    def _write_filelist(sqlcursor, traktortree):
        ''' take the Traktor collections file and put it into
            a sql database for faster mapping in real-time'''
        for node in traktortree.iterfind('COLLECTION/ENTRY'):
            metadata = {
                'artist': node.get('ARTIST'),
                'title': node.get('TITLE'),
            }
            for subnode in node:
                if subnode.tag == 'ALBUM':
                    metadata['album'] = subnode.get('TITLE')
                elif subnode.tag == 'INFO':
                    metadata['key'] = subnode.get('KEY')
                elif subnode.tag == 'LOCATION':
                    volume = subnode.get('VOLUME')
                    metadata['filename'] = ''
                    if volume[0].isalpha() and volume[1] == ':':
                        metadata['filename'] = volume

                    metadata['filename'] += subnode.get('DIR').replace('/:',
                                                                       '/') + subnode.get('FILE')
                elif subnode.tag == 'TEMPO':
                    metadata['bpm'] = subnode.get('BPM')
            sql = 'INSERT INTO songs ('
            sql += ', '.join(metadata.keys()) + ') VALUES ('
            sql += '?,' * (len(metadata.keys()) - 1) + '?)'
            datatuple = tuple(list(metadata.values()))
            sqlcursor.execute(sql, datatuple)

    def rewrite_db(self, collectionsfile=None):
        ''' erase and update the old db '''
        if not collectionsfile:
            collectionsfile = self.config.cparser.value('traktor/collections')

        if not collectionsfile or not pathlib.Path(collectionsfile).exists():
            logging.error('collection.nml (%s) does not exist', collectionsfile)
            return

        self.databasefile.parent.mkdir(parents=True, exist_ok=True)
        if self.databasefile.exists():
            self.databasefile.unlink()

        with sqlite3.connect(self.databasefile) as connection:
            cursor = connection.cursor()
            sql = 'CREATE TABLE IF NOT EXISTS songs ('
            sql += ' TEXT, '.join(METADATALIST) + ' TEXT, '
            sql += 'id INTEGER PRIMARY KEY AUTOINCREMENT)'
            cursor.execute(sql)
            connection.commit()
            sql = 'CREATE TABLE IF NOT EXISTS playlists ('
            sql += ' TEXT, '.join(PLAYLIST) + ' TEXT, '
            sql += 'id INTEGER PRIMARY KEY AUTOINCREMENT)'
            cursor.execute(sql)
            connection.commit()

            traktor = xml.etree.ElementTree.parse(collectionsfile).getroot()
            self._write_filelist(cursor, traktor)
            connection.commit()
            self._write_playlist(cursor, traktor)
            connection.commit()

    async def lookup(self, artist=None, title=None):
        ''' lookup the metadata '''
        async with aiosqlite.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute(
                    '''SELECT * FROM songs WHERE artist=? AND title=? ORDER BY id DESC LIMIT 1''', (
                        artist,
                        title,
                    ))
            except sqlite3.OperationalError:
                return None

            row = await cursor.fetchone()
            if not row:
                return None

        metadata = {data: row[data] for data in METADATALIST}
        for key in LISTFIELDS:
            if metadata.get(key):
                metadata[key] = [row[key]]
        return metadata

    async def getrandomtrack(self, playlist):
        ''' return the contents of a playlist '''
        async with aiosqlite.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute(
                    '''SELECT filename FROM playlists WHERE name=? ORDER BY random() LIMIT 1''',
                    (playlist, ))
            except sqlite3.OperationalError:
                return None

            row = await cursor.fetchone()
            if not row:
                return None

            return row['filename']


class Plugin(IcecastPlugin):
    ''' base class of input plugins '''

    def __init__(self, config=None, qsettings=None):
        ''' no custom init '''
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Traktor"
        self.extradb = None

    def install(self):
        ''' auto-install for Icecast '''
        nidir = self.config.userdocs.joinpath('Native Instruments')
        if nidir.exists():
            for entry in os.scandir(nidir):
                if entry.is_dir() and 'Traktor' in entry.name:
                    cmlpath = pathlib.Path(entry).joinpath('collection.nml')
                    if cmlpath.exists():
                        self.config.cparser.value('traktor/collections', str(cmlpath))
                        self.config.cparser.value('settings/input', 'traktor')
                        self.config.cparser.value('traktor/port', 8000)
                        return True

        return False

    def defaults(self, qsettings):
        ''' (re-)set the default configuration values for this plugin '''
        qsettings.setValue('traktor/port', '8000')
        nidir = self.config.userdocs.joinpath('Native Instruments')
        if nidir.exists():
            if collist := list(nidir.glob('**/collection.nml')):
                collist.sort(key=lambda x: x.stat().st_mtime)
                qsettings.setValue('traktor/collections', str(collist[-1]))

    def connect_settingsui(self, qwidget, uihelp):
        ''' connect any UI elements such as buttons '''
        self.qwidget = qwidget
        self.uihelp = uihelp
        self.qwidget.traktor_browse_button.clicked.connect(self._on_traktor_browse_button)
        self.qwidget.traktor_rebuild_button.clicked.connect(self._on_traktor_rebuild_button)

    def _on_traktor_browse_button(self):
        ''' user clicked traktor browse button '''
        startdir = self.qwidget.traktor_collection_lineedit.text() or str(
            self.config.userdocs.joinpath('Native Instruments'))
        if filename := QFileDialog.getOpenFileName(self.qwidget, 'Open collection file', startdir,
                                                   '*.nml'):
            self.qwidget.traktor_collection_lineedit.setText(filename[0])

    def _on_traktor_rebuild_button(self):
        ''' user clicked re-read collections '''
        rewritedb = Traktor(config=self.config)
        rewritedb.rewrite_db(collectionsfile=self.qwidget.traktor_collection_lineedit.text())

    def load_settingsui(self, qwidget):
        ''' load values from config and populate page '''
        qwidget.port_lineedit.setText(self.config.cparser.value('traktor/port'))
        qwidget.traktor_collection_lineedit.setText(
            self.config.cparser.value('traktor/collections'))

    def verify_settingsui(self, qwidget):  #pylint: disable=no-self-use
        ''' verify the values in the UI prior to saving '''
        filename = qwidget.traktor_collection_lineedit.text()
        if not filename:
            raise PluginVerifyError('Traktor collections.nml is not set.')
        filepath = pathlib.Path(filename)
        if not filepath.exists():
            raise PluginVerifyError('Traktor collections.nml does not exist.')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('traktor/port', qwidget.port_lineedit.text())
        self.config.cparser.setValue('traktor/collections',
                                     qwidget.traktor_collection_lineedit.text())

    def desc_settingsui(self, qwidget):
        ''' provide a description for the plugins page '''
        qwidget.setText('Support for Native Instruments Traktor.')

#### Data feed methods

    async def getplayingtrack(self):
        ''' give back the metadata global '''
        icmetadata = await super().getplayingtrack()
        if self.lastmetadata.get('artist') == icmetadata.get('artist') and self.lastmetadata.get(
                'title') == icmetadata.get('title'):
            return self.lastmetadata

        metadata = None
        if not self.extradb:
            self.extradb = Traktor(config=self.config)

        if icmetadata.get('artist') and icmetadata.get('title'):
            metadata = await self.extradb.lookup(artist=icmetadata['artist'],
                                                 title=icmetadata['title'])
        if not metadata:
            metadata = icmetadata
        self.lastmetadata = metadata
        return metadata

    async def getrandomtrack(self, playlist):
        if not self.extradb:
            self.extradb = Traktor(config=self.config)

        if self.extradb:
            return await self.extradb.getrandomtrack(playlist)
        return None


#### Control methods

    async def start(self):
        ''' any initialization before actual polling starts '''
        port = self.config.cparser.value('traktor/port', type=int, defaultValue=8000)
        await self.start_port(port)
