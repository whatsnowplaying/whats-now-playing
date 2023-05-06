#!/usr/bin/env python3
''' Process Windows Media '''

import asyncio
import logging
import sys

try:

    from winsdk.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as MediaManager
    from winsdk.windows.storage.streams import (DataReader, Buffer,
                                                InputStreamOptions)
    WINMEDIA_STATUS = True
except ImportError:
    WINMEDIA_STATUS = False

from nowplaying.inputs import InputPlugin
import nowplaying.utils


class Plugin(InputPlugin):
    ''' handler for NowPlaying '''

    def __init__(self, config=None, qsettings=None):

        super().__init__(config=config, qsettings=qsettings)

        self.winmedia_status = True
        if not WINMEDIA_STATUS:
            self.available = False
            self.winmedia_status = False
            return

    def install(self):
        ''' Auto-install for WinMedia '''
        return False

    async def start(self):
        ''' configure WinMedia client '''

    @staticmethod
    async def _getcoverimage(thumbref):
        ''' read the thumbnail buffer '''
        thumb_read_buffer = Buffer(5000000)

        readable_stream = await thumbref.open_read_async()
        readable_stream.read_async(thumb_read_buffer,
                                   thumb_read_buffer.capacity,
                                   InputStreamOptions.READ_AHEAD)
        buffer_reader = DataReader.from_buffer(thumb_read_buffer)
        if byte_buffer := bytearray(
                buffer_reader.read_buffer(thumb_read_buffer.length)):
            return nowplaying.utils.image2png(byte_buffer)
        return None

    async def getplayingtrack(self):
        ''' Get the current playing track '''

        if not self.winmedia_status:
            return {}

        sessions = await MediaManager.request_async()
        current_session = sessions.get_current_session()
        if not current_session:
            logging.debug('No winmedia session active')
            return {}

        info = await current_session.try_get_media_properties_async()
        info_dict = {
            song_attr: getattr(info, song_attr)
            for song_attr in dir(info) if song_attr[0] != '_'
        }
        info_dict['genres'] = list(info_dict['genres'])

        mapping = {
            'album_title': 'album',
            'album_artist': 'albumartist',
            'artist': 'artist',
            'title': 'title',
            'track': 'track_number'
        }
        newmeta = {
            outkey: info_dict[inkey]
            for inkey, outkey in mapping.items() if info_dict.get(inkey)
        }
        if thumb_stream_ref := info_dict.get('thumbnail'):
            if coverimage := await self._getcoverimage(thumb_stream_ref):
                newmeta['coverimageraw'] = coverimage

        return newmeta

    async def getrandomtrack(self, playlist):
        ''' not supported '''
        return None

    def defaults(self, qsettings):
        ''' none '''

    def validmixmodes(self):
        ''' let the UI know which modes are valid '''
        return ['newest']

    def setmixmode(self, mixmode):
        ''' only support newest for now '''
        return 'newest'

    def getmixmode(self):
        ''' only support newest for now '''
        return 'newest'

    async def stop(self):
        ''' not needed '''

    def connect_settingsui(self, qwidget, uihelp):
        ''' not needed '''
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget):
        ''' populate the combobox '''
        if not self.winmedia_status:
            return

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''

    def save_settingsui(self, qwidget):
        ''' save the combobox '''
        if not self.winmedia_status:
            return

    def desc_settingsui(self, qwidget):
        ''' description '''
        if not self.winmedia_status:
            return


async def main():
    ''' entry point as a standalone app'''
    logging.basicConfig(level=logging.DEBUG)
    if not WINMEDIA_STATUS:
        print('Not on Windows')
        sys.exit(1)

    plugin = Plugin()
    if metadata := await plugin.getplayingtrack():
        if 'coverimageraw' in metadata:
            logging.info('Got coverart')
            del metadata['coverimageraw']
        logging.info(metadata)


if __name__ == "__main__":
    asyncio.run(main())
