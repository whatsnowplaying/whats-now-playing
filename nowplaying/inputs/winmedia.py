#!/usr/bin/env python3
''' Process Windows Media '''

import asyncio
import logging
import sys
import traceback

try:

    from winsdk.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as MediaManager
    from winsdk.windows.storage.streams import (DataReader, Buffer, InputStreamOptions)
    WINMEDIA_STATUS = True
except ImportError:
    WINMEDIA_STATUS = False

from nowplaying.inputs import InputPlugin
import nowplaying.utils


class Plugin(InputPlugin):
    ''' handler for NowPlaying '''

    def __init__(self, config=None, qsettings=None):

        super().__init__(config=config, qsettings=qsettings)

        self.displayname = "WinMedia"
        self.winmedia_status = True
        self.stopevent = asyncio.Event()
        self.metadata = {}
        self.tasks = set()
        if not WINMEDIA_STATUS:
            self.available = False
            self.winmedia_status = False
            return

    def install(self):
        ''' Auto-install for WinMedia '''
        return False

    def desc_settingsui(self, qwidget):
        ''' provide a description for the plugins page '''
        qwidget.setText('WinMedia will read data from Windows Media Transport'
                        ' -compatible software such as Soundcloud and Spotify.')

    @staticmethod
    async def _getcoverimage(thumbref):
        ''' read the thumbnail buffer '''
        try:
            thumb_read_buffer = Buffer(5000000)

            readable_stream = await thumbref.open_read_async()
            readable_stream.read_async(thumb_read_buffer, thumb_read_buffer.capacity,
                                       InputStreamOptions.READ_AHEAD)
            buffer_reader = DataReader.from_buffer(thumb_read_buffer)
            if byte_buffer := bytearray(
                    buffer_reader.read_buffer(buffer_reader.unconsumed_buffer_length)):
                return nowplaying.utils.image2png(byte_buffer)
        except:  # pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
        return None

    async def _data_loop(self):
        ''' check the metadata transport every so often '''
        while not self.stopevent.is_set():
            await asyncio.sleep(5)
            sessions = await MediaManager.request_async()
            current_session = sessions.get_current_session()
            if not current_session:
                logging.debug('No winmedia session active')
                continue

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
                'track_number': 'track'
            }

            newdata = {
                outkey: info_dict[inkey]
                for inkey, outkey in mapping.items() if info_dict.get(inkey)
            }

            # avoid expensive image2png call
            diff = any(
                newdata.get(cmpval) != self.metadata.get(cmpval) for cmpval in mapping.values())

            if not diff:
                continue

            if thumb_stream_ref := info_dict.get('thumbnail'):
                if coverimage := await self._getcoverimage(thumb_stream_ref):
                    newdata['coverimageraw'] = coverimage

            self.metadata = newdata

    async def getplayingtrack(self):
        ''' Get the current playing track '''
        return self.metadata

    async def getrandomtrack(self, playlist):
        ''' not supported '''
        return None

    async def start(self):
        ''' start loop '''
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._data_loop())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def stop(self):
        ''' stop loop '''
        self.stopevent.set()


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
