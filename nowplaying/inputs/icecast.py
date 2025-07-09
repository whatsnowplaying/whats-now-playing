#!/usr/bin/env python3
''' driver for Icecast SOURCE Protocol, as used by Traktor and Mixxx and others? '''

import asyncio
import codecs
import io
import logging
import logging.config
import os
import struct
import urllib.parse
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import nowplaying.config
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget


logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

# pylint: disable=wrong-import-position

#from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

METADATALIST: list[str] = ['artist', 'title', 'album', 'key', 'filename', 'bpm']

PLAYLIST: list[str] = ['name', 'filename']


class IcecastProtocol(asyncio.Protocol):
    ''' a terrible implementation of the Icecast SOURCE protocol '''

    def __init__(self, metadata_callback: Callable[[dict[str, str]], None] | None = None) -> None:
        self.streaming: bool = False
        self.previous_page: bytes = b''
        self.metadata_callback: Callable[[dict[str, str]], None] | None = metadata_callback
        self._current_metadata: dict[str, str] = {}

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        ''' initial connection gives us a transport to use '''
        self.transport = transport  # type: ignore  # pylint: disable=attribute-defined-outside-init

    def data_received(self, data: bytes) -> None:
        ''' every time data is received, this method is called '''

        if not self.streaming:
            # if 200 gets set, new page. data content here is irrelevant

            self.streaming = True
            self.previous_page = b''
            if data[:19] == b'GET /admin/metadata':
                self._query_parse(data)
            logging.debug('Sending initial 200')
            self.transport.write(b'HTTP/1.0 200 OK\r\n\r\n')  # type: ignore
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

    def _parse_page(self, dataio: io.BytesIO):
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

    def _query_parse(self, data: bytes) -> None:
        ''' try to parse the query '''
        logging.debug('Processing updinfo')

        # Parse the URL from the request data
        url = self._extract_url_from_data(data)
        if not url:
            return

        # Check if this is a metadata update request
        if url.path != '/admin/metadata':
            return

        query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        if query.get('mode') != ['updinfo']:
            return

        # Extract metadata from query parameters
        metadata = self._extract_metadata_from_query(query)

        # Update instance metadata and notify callback
        self._current_metadata.update(metadata)
        if self.metadata_callback:
            self.metadata_callback(self._current_metadata.copy())

    @staticmethod
    def _extract_url_from_data(data: bytes) -> urllib.parse.ParseResult | None:
        ''' Extract and parse URL from request data '''
        try:
            text = data.decode('utf-8').replace('GET ', 'http://localhost').split()[0]
            return urllib.parse.urlparse(text)
        except UnicodeDecodeError:
            logging.warning('Failed to decode icecast query data as UTF-8')
            return None
        except (IndexError, ValueError) as error:
            logging.warning('Failed to parse icecast query URL: %s', error)
            return None

    @staticmethod
    def _extract_metadata_from_query(query: dict[str, list[str]]) -> dict[str, str]:
        ''' Extract metadata from parsed query parameters '''
        metadata: dict[str, str] = {}

        # Direct artist/title parameters
        if query.get('artist'):
            metadata['artist'] = query['artist'][0]
        if query.get('title'):
            metadata['title'] = query['title'][0]

        # Handle 'song' parameter that might contain "Artist - Title"
        if 'song' in query:
            song_text = query['song'][0].strip()
            if ' - ' not in song_text:
                # No separator found, treat entire string as title
                metadata['title'] = song_text
            else:
                # Split on first occurrence of ' - ' (with spaces)
                # This handles cases like "Artist - Song - Remix" correctly
                artist, title = song_text.split(' - ', 1)
                metadata['artist'] = artist.strip()
                metadata['title'] = title.strip()

        return metadata

    def _parse_vorbis_comment(self, fh: io.BytesIO) -> None:  # pylint: disable=invalid-name
        ''' from tinytag, with slight modifications, pull out metadata '''
        comment_type_to_attr_mapping: dict[str, str] = {
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
        metadata: dict[str, str] = {}

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
                    metadata[fieldname] = value

        # Update instance metadata and notify callback
        self._current_metadata.update(metadata)
        if self.metadata_callback:
            self.metadata_callback(self._current_metadata.copy())


class Plugin(InputPlugin):
    ''' base class of input plugins '''

    def __init__(self,
                 config: "nowplaying.config.ConfigFile | None" = None,
                 qsettings: "QWidget | None" = None) -> None:
        ''' no custom init '''
        super().__init__(config=config, qsettings=qsettings)
        self.displayname: str = "Icecast"
        self.server: asyncio.Server | None = None
        self.mode: str | None = None
        self.lastmetadata: dict[str, str] = {}
        self._current_metadata: dict[str, str] = {}

    def _metadata_callback(self, metadata: dict[str, str]) -> None:
        ''' Callback to receive metadata from the protocol '''
        self._current_metadata = metadata

    def install(self) -> bool:
        ''' auto-install for Icecast '''
        return False

#### Settings UI methods

    def defaults(self, qsettings: "QSettings") -> None:
        ''' (re-)set the default configuration values for this plugin '''
        qsettings.setValue('icecast/port', '8000')

    def load_settingsui(self, qwidget: "QWidget") -> None:
        ''' load values from config and populate page '''
        qwidget.port_lineedit.setText(self.config.cparser.value('icecast/port'))  # type: ignore

    def save_settingsui(self, qwidget: "QWidget") -> None:
        ''' take the settings page and save it '''
        self.config.cparser.setValue('icecast/port', qwidget.port_lineedit.text())  # type: ignore

    def desc_settingsui(self, qwidget: "QWidget") -> None:
        ''' provide a description for the plugins page '''
        qwidget.setText('Icecast is a streaming broadcast protocol.'
                        '  This setting should be used for butt, MIXXX, and many others.')

#### Data feed methods

    async def getplayingtrack(self) -> TrackMetadata:
        ''' give back the current metadata '''
        return self._current_metadata.copy()  # type: ignore

    async def getrandomtrack(self, playlist: str) -> None:
        return None


#### Control methods

    async def start_port(self, port: int) -> None:
        ''' start the icecast server on a particular port '''

        loop = asyncio.get_running_loop()
        logging.debug('Launching Icecast on %s', port)
        try:
            # Create protocol factory that passes the metadata callback
            def protocol_factory() -> IcecastProtocol:
                return IcecastProtocol(metadata_callback=self._metadata_callback)
            self.server = await loop.create_server(protocol_factory, '', port)
        except Exception as error:  #pylint: disable=broad-except
            logging.error('Failed to launch icecast: %s', error)

    async def start(self) -> None:
        ''' any initialization before actual polling starts '''
        port: int = self.config.cparser.value('icecast/port', type=int,
                                              defaultValue=8000)
        await self.start_port(port)

    async def stop(self) -> None:
        ''' stopping either the entire program or just this
            input '''
        if self.server:
            self.server.close()
