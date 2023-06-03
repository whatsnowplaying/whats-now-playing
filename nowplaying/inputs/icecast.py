#!/usr/bin/env python3
''' driver for Icecast SOURCE Protocol, as used by Traktor and Mixxx and others? '''

import asyncio
import codecs

import io
import struct
import os
import logging
import logging.config
import urllib.parse

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

# pylint: disable=wrong-import-position

#from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin

METADATA = {}

METADATALIST = ['artist', 'title', 'album', 'key', 'filename', 'bpm']

PLAYLIST = ['name', 'filename']


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
        text = data.decode('utf-8').replace('GET ', 'http://localhost').split()[0]
        url = urllib.parse.urlparse(text)
        if url.path == '/admin/metadata':
            query = urllib.parse.parse_qs(url.query)
            if query.get('mode') == ['updinfo']:
                if query.get('artist'):
                    METADATA['artist'] = query['artist'][0]
                if query.get('title'):
                    METADATA['title'] = query['title'][0]
                if query.get('song'):
                    METADATA['title'], METADATA['artist'] = query['song'][0].split('-')

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


class Plugin(InputPlugin):
    ''' base class of input plugins '''

    def __init__(self, config=None, qsettings=None):
        ''' no custom init '''
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Icecast"
        self.server = None
        self.mode = None
        self.lastmetadata = {}

    def install(self):
        ''' auto-install for Icecast '''
        return False

#### Settings UI methods

    def defaults(self, qsettings):
        ''' (re-)set the default configuration values for this plugin '''
        qsettings.setValue('icecast/port', '8000')

    def load_settingsui(self, qwidget):
        ''' load values from config and populate page '''
        qwidget.port_lineedit.setText(self.config.cparser.value('icecast/port'))

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('icecast/port', qwidget.port_lineedit.text())

    def desc_settingsui(self, qwidget):
        ''' provide a description for the plugins page '''
        qwidget.setText('Icecast is a streaming broadcast protocol.'
                        '  This setting should be used for butt, MIXXX, and many others.')

#### Data feed methods

    async def getplayingtrack(self):
        ''' give back the metadata global '''
        return METADATA

    async def getrandomtrack(self, playlist):
        return None


#### Control methods

    async def start_port(self, port):
        ''' start the icecast server on a particular port '''

        loop = asyncio.get_running_loop()
        logging.debug('Launching Icecast on %s', port)
        try:
            self.server = await loop.create_server(IcecastProtocol, '', port)
        except Exception as error:  #pylint: disable=broad-except
            logging.error('Failed to launch icecast: %s', error)

    async def start(self):
        ''' any initialization before actual polling starts '''
        port = self.config.cparser.value('icecast/port', type=int, defaultValue=8000)
        await self.start_port(port)

    async def stop(self):
        ''' stopping either the entire program or just this
            input '''
        self.server.close()
