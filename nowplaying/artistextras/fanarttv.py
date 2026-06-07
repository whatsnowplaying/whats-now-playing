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

    async def download_async(self, metadata: TrackMetadata | None = None, imagecache=None):
        """async download the extra data"""

        if not self._validate_inputs(metadata, imagecache):
            return None

        apikey = self.config.cparser.value("fanarttv/apikey")
        datacache_client = nowplaying.datacache.get_client()

        for artistid in metadata["musicbrainzartistid"]:
            url = f"http://webservice.fanart.tv/v3/music/{artistid}"
            result = await datacache_client.get_or_fetch(
                url=url,
                identifier=metadata.get("imagecacheartist", artistid),
                data_type="artist",
                provider="fanarttv",
                timeout=self.calculate_delay(),
                retries=3,
                ttl_seconds=_FANARTTV_TTL,
                headers=nowplaying.datacache.CacheHeaders({"client-key": apikey}),
                negative_ttl=24 * 3600,  # 24h: artist not in FanartTV DB
            )
            if result is None:
                return None
            data, _ = result
            try:
                artist_data = orjson.loads(data)
            except orjson.JSONDecodeError:
                return None
            if not artist_data or artist_data.get("status") == "error":
                return None
            self._process_artist_images(artist_data, metadata, imagecache)
            break

        return metadata

    def _validate_inputs(self, metadata: TrackMetadata, imagecache):
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

        if not imagecache:
            logging.debug("imagecache is dead?")
            return False

        if not metadata.get("musicbrainzartistid"):
            return False

        logging.debug("got musicbrainzartistid: %s", metadata["musicbrainzartistid"])
        return True

    def _process_artist_images(
        self, artist_data: dict[str, str] | None, metadata: TrackMetadata | None, imagecache
    ):
        """Process and queue artist images from FanartTV data."""

        if not metadata or not artist_data or not imagecache:
            return

        identifier = metadata.get("imagecacheartist")
        # Process banners
        if artist_data.get("musicbanner") and self.config.cparser.value(
            "fanarttv/banners", type=bool
        ):
            self._queue_images(artist_data["musicbanner"], identifier, "artistbanner", imagecache)

        # Process logos (prefer HD, fallback to regular)
        if self.config.cparser.value("fanarttv/logos", type=bool):
            if logo_data := artist_data.get("hdmusiclogo") or artist_data.get("musiclogo"):
                self._queue_images(logo_data, identifier, "artistlogo", imagecache)

        # Process thumbnails
        if artist_data.get("artistthumb") and self.config.cparser.value(
            "fanarttv/thumbnails", type=bool
        ):
            self._queue_images(
                artist_data["artistthumb"], identifier, "artistthumbnail", imagecache
            )

        # Process fanart backgrounds
        if self.config.cparser.value("fanarttv/fanart", type=bool) and artist_data.get(
            "artistbackground"
        ):
            self._process_fanart_backgrounds(
                artist_data["artistbackground"], metadata, identifier, imagecache
            )

        # Process album cover art — already in the response, keyed by album MBID
        if self.config.cparser.value("fanarttv/coverart", type=bool):
            self._process_album_cover(artist_data, metadata, imagecache)

    def _process_album_cover(self, artist_data: dict, metadata: TrackMetadata, imagecache) -> None:
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
            self.queue_front_cover(artist, album, url, imagecache)

    def _queue_images(self, image_list, identifier, image_type, imagecache):
        """Queue images sorted by popularity (likes)."""
        sorted_images = sorted(image_list, key=lambda x: x.get("likes", 0), reverse=True)
        urls = [img["url"] for img in sorted_images]
        self.queue_artist_image(identifier, image_type, urls, imagecache)

    def _process_fanart_backgrounds(
        self, backgrounds, metadata: TrackMetadata | None, identifier, imagecache
    ):
        """Process fanart backgrounds and collect URLs."""

        if not metadata:
            return

        if not metadata.get("artistfanarturls"):
            metadata["artistfanarturls"] = []
        # Queue first image for display
        if backgrounds:
            self.queue_artist_image(
                identifier, "artistfanart", [backgrounds[0]["url"]], imagecache
            )
            # Collect all URLs for reference
            for background in backgrounds:
                metadata["artistfanarturls"].append(background["url"])

    def providerinfo(self):  # pylint: disable=no-self-use
        """return list of what is provided by this plug-in"""
        return [
            "artistbannerraw",
            "artistlogoraw",
            "artistthumbnailraw",
            "coverimageraw",
            "fanarttv-artistfanarturls",
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
