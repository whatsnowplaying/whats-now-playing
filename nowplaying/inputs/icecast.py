#!/usr/bin/env python3
''' driver for Icecast SOURCE Protocol, as used by Traktor and Mixxx and others? '''

import asyncio
import codecs

import io
import struct
import os
import pathlib
import logging
import logging.config
import sqlite3
import urllib.parse
import xml.etree.ElementTree

import aiosqlite  # pylint: disable=import-error

from PySide6.QtCore import QStandardPaths  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=import-error, no-name-in-module

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

# pylint: disable=wrong-import-position

from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin
from nowplaying.db import LISTFIELDS

METADATA = {}

METADATALIST = ['artist', 'title', 'album', 'key', 'filename', 'bpm']


class IcecastProtocol(asyncio.Protocol):
    ''' a terrible implementation of the Icecast SOURCE protocol '''

    def __init__(self):
        self.streaming = False
        self.previous_page = b''

    def connection_made(self, transport):
        ''' initial connection gives us a transport to use '''
        self.transport = transport  # pylint: disable=attribute-defined-outside-init

    def data_received(self, data):
        ''' every time data is received, this method is called '''

        if not self.streaming:
            # if 200 gets set, new page. data content here is irrelevant

            self.streaming = True
            self.previous_page = b''
            if data[:19] == b'GET /admin/metadata':
                self._query_parse(data)
            logging.debug('Sending initial 200')
            self.transport.write(b'HTTP/1.0 200 OK\r\n\r\n')
        else:
            # data block. convert to bytes and process it,
            # adding each block to the previously received block as necessary
            dataio = io.BytesIO(data)
            for page in self._parse_page(dataio):
                pageio = io.BytesIO(page)
                if page[:7] == b"\x03vorbis":
                    pageio.seek(7, os.SEEK_CUR)  # jump over header name
                    self._parse_vorbis_comment(pageio)
                elif page[:8] == b'OpusTags':  # parse opus metadata:
                    pageio.seek(8, os.SEEK_CUR)  # jump over header name
                    self._parse_vorbis_comment(pageio)

    def _parse_page(self, dataio):
        ''' modified from tinytag, modified for here '''
        header_data = dataio.read(27)  # read ogg page header
        while len(header_data) != 0:
            header = struct.unpack('<4sBBqIIiB', header_data)
            oggs, version, flags, pos, serial, pageseq, crc, segments = header  # pylint: disable=unused-variable
            # self._max_samplenum = max(self._max_samplenum, pos)
            if oggs != b'OggS' or version != 0:
                logging.debug('Not a valid ogg stream!')
            segsizes = struct.unpack('B' * segments, dataio.read(segments))
            total = 0
            for segsize in segsizes:  # read all segments
                total += segsize
                if total < 255:  # less than 255 bytes means end of page
                    yield self.previous_page + dataio.read(total)
                    self.previous_page = b''
                    total = 0
            if total != 0:
                if total % 255 == 0:
                    self.previous_page += dataio.read(total)
                else:
                    yield self.previous_page + dataio.read(total)
                    self.previous_page = b''
            header_data = dataio.read(27)

    @staticmethod
    def _query_parse(data):
        ''' try to parse the query '''
        global METADATA  # pylint: disable=global-statement
        logging.debug('Processing updinfo')

        METADATA = {}
        text = data.decode('utf-8').replace('GET ',
                                            'http://localhost').split()[0]
        url = urllib.parse.urlparse(text)
        if url.path == '/admin/metadata':
            query = urllib.parse.parse_qs(url.query)
            if query.get('mode') == ['updinfo']:
                if query.get('artist'):
                    METADATA['artist'] = query['artist'][0]
                if query.get('title'):
                    METADATA['title'] = query['title'][0]
                if query.get('song'):
                    METADATA['title'], METADATA['artist'] = query['song'][
                        0].split('-')

    @staticmethod
    def _parse_vorbis_comment(fh):  # pylint: disable=invalid-name
        ''' from tinytag, with slight modifications, pull out metadata '''
        global METADATA  # pylint: disable=global-statement
        comment_type_to_attr_mapping = {
            'album': 'album',
            'albumartist': 'albumartist',
            'title': 'title',
            'artist': 'artist',
            'date': 'year',
            'tracknumber': 'track',
            'totaltracks': 'track_total',
            'discnumber': 'disc',
            'totaldiscs': 'disc_total',
            'genre': 'genre',
            'description': 'comment',
        }

        logging.debug('Processing vorbis comment')
        METADATA = {}

        vendor_length = struct.unpack('I', fh.read(4))[0]
        fh.seek(vendor_length, os.SEEK_CUR)  # jump over vendor
        elements = struct.unpack('I', fh.read(4))[0]
        for _ in range(elements):
            length = struct.unpack('I', fh.read(4))[0]
            try:
                keyvalpair = codecs.decode(fh.read(length), 'UTF-8')
            except UnicodeDecodeError:
                continue
            if '=' in keyvalpair:
                key, value = keyvalpair.split('=', 1)
                if fieldname := comment_type_to_attr_mapping.get(key.lower()):
                    METADATA[fieldname] = value


class Traktor:
    ''' data from the traktor collections.nml file '''

    def __init__(self, config=None):
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.CacheLocation)[0]).joinpath(
                    'icecast', 'traktor.db')
        self.database = None
        self.config = config

    def initdb(self):
        ''' initialize the db '''
        if not self.databasefile.exists():
            self.rewrite_db()

    def rewrite_db(self, collectionsfile=None):
        ''' erase and update the old db '''
        if not collectionsfile:
            collectionsfile = self.config.cparser.value(
                'icecast/traktor-collections')

        if not collectionsfile or not pathlib.Path(collectionsfile).exists():
            logging.error('collection.nml (%s) does not exist',
                          collectionsfile)
            return

        self.databasefile.parent.mkdir(parents=True, exist_ok=True)
        if self.databasefile.exists():
            self.databasefile.unlink()

        with sqlite3.connect(self.databasefile) as connection:
            cursor = connection.cursor()
            sql = 'CREATE TABLE IF NOT EXISTS traktor ('
            sql += ' TEXT, '.join(METADATALIST) + ' TEXT, '
            sql += 'id INTEGER PRIMARY KEY AUTOINCREMENT)'
            cursor.execute(sql)
            connection.commit()
            traktor = xml.etree.ElementTree.parse(collectionsfile).getroot()
            for node in traktor.iterfind('COLLECTION/ENTRY'):
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

                        metadata['filename'] += subnode.get('DIR').replace(
                            '/:', '/') + subnode.get('FILE')
                    elif subnode.tag == 'TEMPO':
                        metadata['bpm'] = subnode.get('BPM')
                sql = 'INSERT INTO traktor ('
                sql += ', '.join(metadata.keys()) + ') VALUES ('
                sql += '?,' * (len(metadata.keys()) - 1) + '?)'
                datatuple = tuple(list(metadata.values()))
                cursor.execute(sql, datatuple)
                connection.commit()

    async def lookup(self, artist=None, title=None):
        ''' lookup the metadata '''
        async with aiosqlite.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute(
                    '''SELECT * FROM traktor WHERE artist=? AND title=? ORDER BY id DESC LIMIT 1''',
                    (
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


class Plugin(InputPlugin):
    ''' base class of input plugins '''

    def __init__(self, config=None, qsettings=None):
        ''' no custom init '''
        super().__init__(config=config, qsettings=qsettings)
        self.server = None
        self.mode = None
        self.extradb = None
        self.qwidget = None
        self.lastmetadata = {}

    def install(self):
        ''' auto-install for Icecast '''
        nidir = pathlib.Path.home().joinpath('Documents', 'Native Instruments')

        if nidir.exists():
            for entry in os.scandir(nidir):
                if entry.is_dir() and 'Traktor' in entry.name:
                    cmlpath = pathlib.Path(entry).joinpath('collection.nml')
                    if cmlpath.exists():
                        self.config.cparser.value(
                            'icecast/traktor-collections', str(cmlpath))
                        self.config.cparser.value('settings/input', 'icecast')
                        self.config.cparser.value('icecast/mode', 'traktor')
                        return True

        return False

    def _set_mode(self):
        mode = self.config.cparser.value('icecast/mode')
        logging.debug('icecast mode: %s', mode)
        if not mode or mode == 'none':
            return

        try:
            self.extradb = globals()[mode.capitalize()](config=self.config)
            self.extradb.initdb()
        except Exception as error:  # pylint: disable=broad-except
            logging.debug('failed to get icecast %s db: %s', mode, error)
            self.config.cparser.setValue('icecast/mode', 'none')

#### Settings UI methods

    def defaults(self, qsettings):
        ''' (re-)set the default configuration values for this plugin '''
        qsettings.setValue('icecast/mode', 'none')
        qsettings.setValue('icecast/port', '8000')

    def connect_settingsui(self, qwidget):
        ''' connect any UI elements such as buttons '''
        self.qwidget = qwidget
        self.qwidget.traktor_browse_button.clicked.connect(
            self._on_traktor_browse_button)
        self.qwidget.traktor_rebuild_button.clicked.connect(
            self._on_traktor_rebuild_button)

    def _on_traktor_browse_button(self):
        ''' user clicked traktor browse button '''
        startdir = self.qwidget.traktor_collection_lineedit.text()
        if not startdir:
            startdir = str(pathlib.Path.home().joinpath(
                'Documents', 'Native Instruments'))
        if filename := QFileDialog.getOpenFileName(self.qwidget,
                                                   'Open collection file',
                                                   startdir, '*.nml'):
            self.qwidget.traktor_collection_lineedit.setText(filename[0])

    def _on_traktor_rebuild_button(self):
        ''' user clicked re-read collections '''
        rewritedb = Traktor(config=self.config)
        rewritedb.rewrite_db(
            collectionsfile=self.qwidget.traktor_collection_lineedit.text())

    def load_settingsui(self, qwidget):
        ''' load values from config and populate page '''
        qwidget.port_lineedit.setText(
            self.config.cparser.value('icecast/port'))
        for radio in ['none', 'traktor']:
            func = getattr(qwidget, f'{radio}_button')
            func.setChecked(False)
        if mode := self.config.cparser.value('icecast/mode'):
            func = getattr(qwidget, f'{mode}_button')
            func.setChecked(True)
        else:
            qwidget.none_button.setChecked(True)

        qwidget.traktor_collection_lineedit.setText(
            self.config.cparser.value('icecast/traktor-collections'))

    def verify_settingsui(self, qwidget):  #pylint: disable=no-self-use
        ''' verify the values in the UI prior to saving '''
        if qwidget.traktor_button.isChecked():
            filename = qwidget.traktor_collection_lineedit.text()
            if not filename:
                logging.debug('raising')
                raise PluginVerifyError(
                    'Icecast/Traktor collections.nml is not set.')
            filepath = pathlib.Path(filename)
            if not filepath.exists():
                logging.debug('raising')
                raise PluginVerifyError(
                    'Icecast/Traktor collections.nml does not exist.')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('icecast/port',
                                     qwidget.port_lineedit.text())
        if qwidget.traktor_button.isChecked():
            self.config.cparser.setValue('icecast/mode', 'traktor')
            self.config.cparser.setValue(
                'icecast/traktor-collections',
                qwidget.traktor_collection_lineedit.text())
        if qwidget.none_button.isChecked():
            self.config.cparser.setValue('icecast/mode', 'none')

    def desc_settingsui(self, qwidget):
        ''' provide a description for the plugins page '''
        qwidget.setText(
            'Icecast is a streaming broadcast protocol.'
            '  This setting should be used for butt, MIXXX, Traktor, and many others.'
        )

#### Mix Mode menu item methods

    def validmixmodes(self):  #pylint: disable=no-self-use
        ''' tell ui valid mixmodes '''
        return ['newest']

    def setmixmode(self, mixmode):  #pylint: disable=no-self-use
        ''' handle user switching the mix mode: TBD '''
        return 'newest'

    def getmixmode(self):  #pylint: disable=no-self-use
        ''' return what the current mixmode is set to '''
        return 'newest'

#### Data feed methods

    async def getplayingtrack(self):
        ''' give back the metadata global '''
        if self.lastmetadata.get('artist') == METADATA.get(
                'artist') and self.lastmetadata.get('title') == METADATA.get(
                    'title'):
            return self.lastmetadata
        metadata = None
        if self.extradb and METADATA.get('artist') and METADATA.get('title'):
            metadata = await self.extradb.lookup(artist=METADATA['artist'],
                                                 title=METADATA['title'])
        if not metadata:
            metadata = METADATA
        self.lastmetadata = metadata
        return metadata


#### Control methods

    async def start(self):
        ''' any initialization before actual polling starts '''
        self._set_mode()
        loop = asyncio.get_running_loop()
        port = self.config.cparser.value('icecast/port',
                                         type=int,
                                         defaultValue=8000)
        logging.debug('Launching Icecast on %s', port)
        try:
            self.server = await loop.create_server(IcecastProtocol, '', port)
        except Exception as error:  #pylint: disable=broad-except
            logging.error('Failed to launch icecast: %s', error)
            print(error)

    async def stop(self):
        ''' stopping either the entire program or just this
            input '''
        self.server.close()
