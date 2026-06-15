#!/usr/bin/env python3
"""start of support of fanarttv"""

import logging
import logging.config
import logging.handlers

import orjson

import nowplaying.datacache
from nowplaying.artistextras import ArtistExtrasPlugin
from nowplaying.types import TrackMetadata
from nowplaying.config import ConfigFile

_FANARTTV_TTL = 7 * 24 * 3600  # 7 days


class Plugin(ArtistExtrasPlugin):
    """handler for fanart.tv"""

    def __init__(self, config: ConfigFile | None = None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.client = None
        self.displayname = "fanart.tv"
        self.priority = 50

    async def download_async(self, metadata: TrackMetadata | None = None):
        """async download the extra data"""

        if not self._validate_inputs(metadata):
            return None

        apikey = self.config.cparser.value("fanarttv/apikey")
        datacache_client = nowplaying.datacache.get_client()

        for artistid in metadata["musicbrainzartistid"]:
            url = f"http://webservice.fanart.tv/v3/music/{artistid}"
            result = await datacache_client.get_or_fetch(
                nowplaying.datacache.FetchRequest(
                    url=url,
                    identifier=metadata.get("imagecacheartist", artistid),
                    data_type="artist",
                    provider="fanarttv",
                    timeout=self.calculate_delay(),
                    retries=3,
                    ttl_seconds=_FANARTTV_TTL,
                    headers=nowplaying.datacache.CacheHeaders({"client-key": apikey}),
                    negative_ttl=24 * 3600,
                )
            )
            if result is None:
                continue
            try:
                artist_data = orjson.loads(result.data)
            except orjson.JSONDecodeError:
                continue
            if not artist_data or artist_data.get("status") == "error":
                continue
            await self._process_artist_images(artist_data, metadata)
            break
        else:
            return None

        return metadata

    def _validate_inputs(self, metadata: TrackMetadata):
        """Validate required inputs for fanart download."""
        apikey = self.config.cparser.value("fanarttv/apikey")
        if not apikey or not self.config.cparser.value("fanarttv/enabled", type=bool):
            return False

        if not metadata or (
            not metadata.get("artist") and not metadata.get("musicbrainzartistid")
        ):
            logging.debug("skipping: no artist or MBID")
            return False

        # MBID-only mode (featured artist) requires imagecacheartist to be set
        if not metadata.get("artist") and not metadata.get("imagecacheartist"):
            logging.debug("skipping: MBID-only but no imagecacheartist")
            return False

        if not metadata.get("musicbrainzartistid"):
            return False

        logging.debug("got musicbrainzartistid: %s", metadata["musicbrainzartistid"])
        return True

    async def _process_artist_images(
        self, artist_data: dict[str, str] | None, metadata: TrackMetadata | None
    ):
        """Process and queue artist images from FanartTV data."""

        if not metadata or not artist_data:
            return

        identifier = metadata.get("imagecacheartist")
        # Process banners
        if artist_data.get("musicbanner") and self.config.cparser.value(
            "fanarttv/banners", type=bool
        ):
            await self._queue_images(artist_data["musicbanner"], identifier, "artistbanner")

        # Process logos (prefer HD, fallback to regular)
        if self.config.cparser.value("fanarttv/logos", type=bool):
            if logo_data := artist_data.get("hdmusiclogo") or artist_data.get("musiclogo"):
                await self._queue_images(logo_data, identifier, "artistlogo")

        # Process thumbnails
        if artist_data.get("artistthumb") and self.config.cparser.value(
            "fanarttv/thumbnails", type=bool
        ):
            await self._queue_images(artist_data["artistthumb"], identifier, "artistthumbnail")

        # Process fanart backgrounds
        if self.config.cparser.value("fanarttv/fanart", type=bool) and artist_data.get(
            "artistbackground"
        ):
            await self._process_fanart_backgrounds(
                artist_data["artistbackground"], metadata, identifier
            )

        # Process album cover art — already in the response, keyed by album MBID
        if self.config.cparser.value("fanarttv/coverart", type=bool):
            await self._process_album_cover(artist_data, metadata)

    async def _process_album_cover(self, artist_data: dict, metadata: TrackMetadata) -> None:
        """Queue album cover art from the albums section of the FanartTV response."""
        album_mbid = metadata.get("musicbrainzreleasegroupid")
        artist = metadata.get("artist")
        album = metadata.get("album")
        if not album_mbid or not artist or not album:
            return
        albums = artist_data.get("albums", {})
        album_entry = albums.get(album_mbid, {})
        covers = album_entry.get("albumcover", [])
        if not covers:
            return
        sorted_covers = sorted(covers, key=lambda x: x.get("likes", 0), reverse=True)
        if url := sorted_covers[0].get("url"):
            logging.debug("fanarttv: queuing album cover for %s - %s", artist, album)
            await self.queue_front_cover(artist, album, url, provider="fanarttv")

    async def _queue_images(self, image_list, identifier, image_type):
        """Queue images sorted by popularity (likes)."""
        sorted_images = sorted(image_list, key=lambda x: x.get("likes", 0), reverse=True)
        urls = [img["url"] for img in sorted_images]
        await self.queue_artist_image(identifier, image_type, urls, provider="fanarttv")

    async def _process_fanart_backgrounds(
        self, backgrounds, metadata: TrackMetadata | None, identifier
    ):
        """Process fanart backgrounds and collect URLs."""

        if not metadata or not backgrounds:
            return
        await self.queue_artist_image(
            identifier, "artistfanart", [b["url"] for b in backgrounds], provider="fanarttv"
        )

    def providerinfo(self):  # pylint: disable=no-self-use
        """return list of what is provided by this plug-in"""
        return [
            "artistbannerraw",
            "artistlogoraw",
            "artistthumbnailraw",
            "coverimageraw",
        ]

    def connect_settingsui(self, qwidget, uihelp):
        """pass"""

    def load_settingsui(self, qwidget):
        """draw the plugin's settings page"""
        if self.config.cparser.value("fanarttv/enabled", type=bool):
            qwidget.fanarttv_checkbox.setChecked(True)
        else:
            qwidget.fanarttv_checkbox.setChecked(False)
        qwidget.apikey_lineedit.setText(self.config.cparser.value("fanarttv/apikey"))

        for field in ["banners", "logos", "fanart", "thumbnails", "coverart"]:
            func = getattr(qwidget, f"{field}_checkbox")
            func.setChecked(self.config.cparser.value(f"fanarttv/{field}", type=bool))

    def verify_settingsui(self, qwidget):
        """pass"""

    def save_settingsui(self, qwidget):
        """take the settings page and save it"""

        self.config.cparser.setValue("fanarttv/enabled", qwidget.fanarttv_checkbox.isChecked())
        self.config.cparser.setValue("fanarttv/apikey", qwidget.apikey_lineedit.text())

        for field in ["banners", "logos", "fanart", "thumbnails", "coverart"]:
            func = getattr(qwidget, f"{field}_checkbox")
            self.config.cparser.setValue(f"fanarttv/{field}", func.isChecked())

    def defaults(self, qsettings):
        for field in ["banners", "logos", "fanart", "thumbnails", "coverart"]:
            qsettings.setValue(f"fanarttv/{field}", False)

        qsettings.setValue("fanarttv/enabled", False)
        qsettings.setValue("fanarttv/apikey", "")
