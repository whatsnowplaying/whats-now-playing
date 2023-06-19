#!/usr/bin/env python3
"""Process macOS Music App via ScriptingBridge"""

import asyncio
import logging
import sys
import urllib.parse

try:
    from ScriptingBridge import SBApplication  # type: ignore[import]  # pylint: disable=import-error

    MACOS_MUSIC_STATUS = True
except ImportError:
    MACOS_MUSIC_STATUS = False

from nowplaying.inputs import InputPlugin
import nowplaying.types
import nowplaying.utils

# Music.app player state OSType constant for playing ('kPSP')
MUSIC_PLAYER_STATE_PLAYING = 1800426320


class Plugin(InputPlugin):
    """handler for NowPlaying"""

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)

        self.displayname = "macOS Music"
        self.stopevent = asyncio.Event()
        self.metadata: nowplaying.types.TrackMetadata = {}
        self.tasks = set()
        if not MACOS_MUSIC_STATUS:
            self.available = False
            return
        self.musicapp = SBApplication.applicationWithBundleIdentifier_("com.apple.Music")
        if not self.musicapp or not hasattr(self.musicapp, "playerState"):
            logging.warning("Could not obtain a handle to the macOS Music app")
            self.available = False

    def install(self):
        """Auto-install for macOS Music"""
        return False

    def desc_settingsui(self, qwidget):
        """provide a description for the plugins page"""
        qwidget.setText("Reads currently playing track data from the macOS Music app.")

    @staticmethod
    def _build_track_metadata(current: object) -> nowplaying.types.TrackMetadata:
        """Extract track fields from a ScriptingBridge MPMediaItem proxy."""
        newdata: nowplaying.types.TrackMetadata = {
            "album": str(current.album() or ""),  # type: ignore[union-attr]
            "artist": str(current.artist() or ""),  # type: ignore[union-attr]
            "bpm": str(current.bpm() or ""),  # type: ignore[union-attr]
            "comments": str(current.comment() or ""),  # type: ignore[union-attr]
            "disc": str(current.discNumber() or ""),  # type: ignore[union-attr]
            "disc_total": str(current.discCount() or ""),  # type: ignore[union-attr]
            "genre": str(current.genre() or "").replace("\n", ""),  # type: ignore[union-attr]
            "title": str(current.name() or ""),  # type: ignore[union-attr]
            "track": str(current.trackNumber() or ""),  # type: ignore[union-attr]
            "track_total": str(current.trackCount() or ""),  # type: ignore[union-attr]
            "year": str(current.year() or ""),  # type: ignore[union-attr]
        }
        try:
            location = current.location()  # type: ignore[union-attr]
            if location:
                localfile = urllib.parse.urlparse(str(location)).path
                if localfile and localfile[0] == "/":
                    newdata["filename"] = urllib.parse.unquote(localfile)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.debug("Failed to parse track location: %s", exc)
        try:
            artworks = current.artworks()  # type: ignore[union-attr]
            if artworks and artworks.count() > 0:
                img_data = artworks[0].data()
                if img_data:
                    if coverimage := nowplaying.utils.image2png(bytes(img_data)):
                        newdata["coverimageraw"] = coverimage
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.debug("Failed to get artwork: %s", exc)
        return newdata

    async def _data_loop(self):
        """check the metadata transport every so often"""
        if not self.available:
            return
        while not self.stopevent.is_set():
            await asyncio.sleep(5)
            try:
                if self.musicapp.playerState() != MUSIC_PLAYER_STATE_PLAYING:
                    self.metadata = {}
                    continue
                current = self.musicapp.currentTrack()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.debug("ScriptingBridge error polling Music app: %s", exc)
                self.metadata = {}
                continue
            if not current:
                continue

            newdata = self._build_track_metadata(current)

            # avoid expensive image2png call on unchanged tracks
            if any(value != self.metadata.get(key) for key, value in newdata.items()):
                self.metadata = newdata

    async def getplayingtrack(self):
        """Get the current playing track"""
        return self.metadata

    async def getrandomtrack(self, playlist):
        """not supported"""
        return None

    async def start(self):
        """start loop"""
        self.stopevent.clear()
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._data_loop())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def stop(self):
        """stop loop"""
        self.stopevent.set()
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()


async def main():
    """entry point as a standalone app"""
    logging.basicConfig(level=logging.DEBUG)
    if not MACOS_MUSIC_STATUS:
        print("Not on macOS or ScriptingBridge not available")
        sys.exit(1)

    plugin = Plugin()
    await plugin.start()
    await asyncio.sleep(6)
    if metadata := await plugin.getplayingtrack():
        if "coverimageraw" in metadata:
            print("Got coverart")
            del metadata["coverimageraw"]
        print(metadata)
    await plugin.stop()


if __name__ == "__main__":
    asyncio.run(main())
