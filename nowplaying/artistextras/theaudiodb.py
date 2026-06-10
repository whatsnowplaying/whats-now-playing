#!/usr/bin/env python3
"""start of support of theaudiodb"""

import logging
import urllib.parse
from typing import TYPE_CHECKING, Any

import orjson

import nowplaying.datacache
import nowplaying.artistextras
import nowplaying.config
import nowplaying.utils
from nowplaying.types import TrackMetadata

# Public free-tier API key (30 requests/minute). Single source of truth for
# defaults() and the 5.1.0 upgrade migration.
DEFAULT_THEAUDIODB_API_KEY = "123"
_THEAUDIODB_BASE = "https://theaudiodb.com/api/v1/json"
_THEAUDIODB_TTL = 7 * 24 * 3600  # 7 days

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
    from PySide6.QtWidgets import QWidget


class Plugin(nowplaying.artistextras.ArtistExtrasPlugin):
    """handler for TheAudioDB"""

    def __init__(
        self, config: nowplaying.config.ConfigFile | None = None, qsettings: "QSettings" = None
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.fnstr: str | None = None
        self.displayname: str = "TheAudioDB"
        self.priority: int = 50

    @staticmethod
    def _filter(text: str) -> str:
        htmlfilter = nowplaying.utils.HTMLFilter()
        htmlfilter.feed(text)
        return htmlfilter.text

    async def _fetch_cached(self, apikey: str, api: str, artist_name: str) -> TrackMetadata | None:
        """Fetch and cache a TheAudioDB API response via DataCacheClient."""
        url = f"{_THEAUDIODB_BASE}/{apikey}/{api}"
        logging.debug("Fetching async %s", api)
        result = await nowplaying.datacache.get_client().get_or_fetch(
            url=url,
            identifier=artist_name,
            data_type="api_response",
            provider="theaudiodb",
            timeout=self.calculate_delay(),
            retries=3,
            ttl_seconds=_THEAUDIODB_TTL,
            negative_ttl=24 * 3600,  # 24h: artist/album not in TheAudioDB
        )
        if result is None:
            return None
        try:
            return orjson.loads(result.data)
        except orjson.JSONDecodeError:
            return None

    def _check_artist(self, artdata: dict[str, Any]) -> bool:
        """is this actually the artist we are looking for?"""
        if not self.fnstr:
            # Empty artist name = MBID-only lookup mode (e.g. featured artist), trust all results
            logging.debug("theaudiodb MBID-only mode, trusting %s", artdata.get("strArtist"))
            return True
        for fieldname in ["strArtist", "strArtistAlternate"]:
            if artdata.get(fieldname) and self.fnstr:
                normalized = nowplaying.utils.normalize(
                    artdata[fieldname], sizecheck=4, nospaces=True
                )
                if normalized and normalized in self.fnstr:
                    logging.debug("theaudiodb Trusting %s: %s", fieldname, artdata[fieldname])
                    return True
            logging.debug(
                "theaudiodb not Trusting %s vs. %s",
                self.fnstr,
                nowplaying.utils.normalize(artdata.get(fieldname), sizecheck=4, nospaces=True),
            )
        return False

    async def _handle_extradata(
        self,
        extradata: list[dict[str, Any]],
        metadata: TrackMetadata,
        used_musicbrainz: bool = False,
    ) -> TrackMetadata:
        """deal with the various bits of data"""
        if bio := self._extract_bio_data(extradata, metadata):
            metadata["artistlongbio"] = bio

        for artdata in extradata:
            if not self._check_artist(artdata):
                continue

            self._handle_website_data(artdata, metadata)
            await self._handle_image_data(artdata, metadata)

        self._correct_artist_name(extradata, metadata, used_musicbrainz)
        return metadata

    def _extract_bio_data(self, extradata: list[dict[str, Any]], metadata: TrackMetadata) -> str:
        """Extract biography data from TheAudioDB response"""
        if metadata.get("artistlongbio") or not self.config.cparser.value(
            "theaudiodb/bio", type=bool
        ):
            return ""

        lang1 = self.config.cparser.value("theaudiodb/bio_iso")
        bio = ""

        for artdata in extradata:
            if not self._check_artist(artdata):
                continue

            if f"strBiography{lang1}" in artdata:
                bio += self._filter(artdata[f"strBiography{lang1}"])
            elif lang1 and lang1.upper() == "EN" and artdata.get("strBiography"):
                # strBiography (no suffix) is TheAudioDB's English bio field;
                # strBiographyEN is absent from most entries
                bio += self._filter(artdata["strBiography"])
            elif self.config.cparser.value("theaudiodb/bio_iso_en_fallback", type=bool):
                if "strBiographyEN" in artdata:
                    bio += self._filter(artdata["strBiographyEN"])
                elif artdata.get("strBiography"):
                    bio += self._filter(artdata["strBiography"])

        return bio

    def _handle_website_data(self, artdata: dict[str, Any], metadata: TrackMetadata) -> None:
        """Handle website data from TheAudioDB response"""
        if not (
            self.config.cparser.value("theaudiodb/websites", type=bool)
            and artdata.get("strWebsite")
        ):
            return

        webstr = "https://" + artdata["strWebsite"]
        if not metadata.get("artistwebsites"):
            metadata["artistwebsites"] = []
        metadata["artistwebsites"].append(webstr)

    async def _handle_image_data(self, artdata: dict[str, Any], metadata: TrackMetadata) -> None:
        """Handle image data from TheAudioDB response"""
        await self._queue_single_image(
            artdata,
            metadata,
            "strArtistBanner",
            "artistbannerraw",
            "artistbanner",
            "banners",
        )
        await self._queue_single_image(
            artdata, metadata, "strArtistLogo", "artistlogoraw", "artistlogo", "logos"
        )
        await self._queue_single_image(
            artdata,
            metadata,
            "strArtistThumb",
            "artistthumbnailraw",
            "artistthumbnail",
            "thumbnails",
        )
        await self._handle_fanart_data(artdata, metadata)

    async def _queue_single_image(  # pylint: disable=too-many-arguments
        self,
        artdata: dict[str, Any],
        metadata: TrackMetadata,
        source_key: str,
        metadata_key: str,
        image_type: str,
        config_key: str,
    ) -> None:
        """Queue a single image type from TheAudioDB data"""
        if (
            metadata.get(metadata_key)
            or not artdata.get(source_key)
            or not self.config.cparser.value(f"theaudiodb/{config_key}", type=bool)
        ):
            return

        await self.queue_artist_image(
            metadata["imagecacheartist"], image_type, [artdata[source_key]], provider="theaudiodb"
        )

    async def _handle_fanart_data(self, artdata: dict[str, Any], metadata: TrackMetadata) -> None:
        """Handle fanart data from TheAudioDB response"""
        if not self.config.cparser.value("theaudiodb/fanart", type=bool):
            return

        fanart_queued = False
        for num in ["", "2", "3", "4"]:
            artstring = f"strArtistFanart{num}"
            if not artdata.get(artstring):
                continue

            if not fanart_queued:
                fanart_queued = True
                await self.queue_artist_image(
                    metadata["imagecacheartist"],
                    "artistfanart",
                    [artdata[artstring]],
                    provider="theaudiodb",
                )

    def _correct_artist_name(
        self, extradata: list[dict[str, Any]], metadata: TrackMetadata, used_musicbrainz: bool
    ) -> None:
        """Correct artist name from API response for name-based searches"""
        if used_musicbrainz or not extradata:
            return

        for artdata in extradata:
            if not (self._check_artist(artdata) and artdata.get("strArtist")):
                continue

            corrected_artist = artdata["strArtist"]
            if corrected_artist != metadata["artist"]:
                logging.debug(
                    "TheAudioDB corrected artist name: %s -> %s",
                    metadata["artist"],
                    corrected_artist,
                )
                metadata["artist"] = corrected_artist
            break

    async def albumdatafromname_async(self, apikey: str, artist: str, album: str) -> dict | None:
        """Fetch album data by artist and album name"""
        urlart = urllib.parse.quote(artist)
        urlalbum = urllib.parse.quote(album)
        data = await self._fetch_cached(apikey, f"searchalbum.php?s={urlart}&a={urlalbum}", artist)
        if not data or not data.get("album"):
            return None
        return data

    async def _queue_coverart(self, apikey: str, metadata: TrackMetadata) -> None:
        """Fetch album cover art from TheAudioDB and queue for download"""
        if not self.config.cparser.value("theaudiodb/coverart", type=bool):
            return
        if metadata.get("coverimageraw"):
            return
        artist = metadata.get("artist")
        album = metadata.get("album")
        if not artist or not album:
            return
        album_data = await self.albumdatafromname_async(apikey, artist, album)
        if not album_data:
            return
        for albuminfo in album_data["album"]:
            cover_url = albuminfo.get("strAlbumThumbHQ") or albuminfo.get("strAlbumThumb")
            if cover_url:
                await self.queue_front_cover(artist, album, cover_url, provider="theaudiodb")
                return

    async def artistdatafrommbid_async(
        self, apikey: str, mbartistid: str, artist_name: str
    ) -> TrackMetadata | None:
        """async cached version of artistdatafrommbid"""
        data = await self._fetch_cached(apikey, f"artist-mb.php?i={mbartistid}", artist_name)
        if not data or not data.get("artists"):
            return None
        return data

    async def artistdatafromname_async(self, apikey: str, artist: str) -> TrackMetadata | None:
        """async cached version of artistdatafromname"""
        if not artist:
            return None
        urlart = urllib.parse.quote(artist)
        data = await self._fetch_cached(apikey, f"search.php?s={urlart}", artist)
        if not data or not data.get("artists"):
            return None
        return data

    @staticmethod
    async def _cache_individual_artist(
        artist_data: TrackMetadata, artist_name: str
    ) -> TrackMetadata:
        """Cache individual artist data by TheAudioDB ID to handle duplicates"""
        if not artist_data.get("idArtist"):
            return artist_data

        # Cache individual artist by their unique TheAudioDB ID
        async def fetch_func():
            return artist_data  # Already have the data, just cache it

        return await nowplaying.datacache.cached_fetch(
            provider="theaudiodb",
            artist_name=artist_name,
            endpoint=f"artist_{artist_data['idArtist']}",
            fetch_func=fetch_func,
            ttl_seconds=None,  # Use provider default from _PROVIDER_TTL
        )

    async def download_async(  # pylint: disable=too-many-branches
        self, metadata: TrackMetadata | None = None
    ) -> TrackMetadata | None:
        """async do data lookup"""

        if not self.config.cparser.value("theaudiodb/enabled", type=bool):
            return None

        if not metadata or (
            not metadata.get("artist") and not metadata.get("musicbrainzartistid")
        ):
            logging.debug("No artist or MBID; skipping")
            return None

        # MBID-only mode (featured artist) requires imagecacheartist to be set
        if not metadata.get("artist") and not metadata.get("imagecacheartist"):
            logging.debug("No artist or imagecacheartist; skipping")
            return None

        apikey = self.config.cparser.value("theaudiodb/apikey")
        if not apikey:
            logging.debug("No API key.")
            return None

        extradata = []
        used_musicbrainz = False
        self.fnstr = nowplaying.utils.normalize(metadata["artist"], sizecheck=4, nospaces=True)

        # Try MusicBrainz ID first if available
        if metadata.get("musicbrainzartistid"):
            logging.debug("got musicbrainzartistid: %s", metadata["musicbrainzartistid"])
            for mbid in metadata["musicbrainzartistid"]:
                if newdata := await self.artistdatafrommbid_async(
                    apikey, mbid, metadata["artist"]
                ):
                    extradata.extend(
                        artist for artist in newdata["artists"] if self._check_artist(artist)
                    )
                    used_musicbrainz = True

        # Fall back to name-based search if no MusicBrainz data found
        if not extradata and metadata.get("artist"):
            logging.debug("got artist")
            for variation in nowplaying.utils.artist_name_variations(metadata["artist"]):
                if artistdata := await self.artistdatafromname_async(apikey, variation):
                    # Filter and cache individual artists to handle duplicates
                    for artist in artistdata.get("artists", []):
                        if self._check_artist(artist):
                            # Cache this specific artist by their unique ID
                            cached_artist = await self._cache_individual_artist(
                                artist, metadata["artist"]
                            )
                            extradata.append(cached_artist)
                    if extradata:
                        break

        if not extradata:
            return None

        result = await self._handle_extradata(extradata, metadata, used_musicbrainz)
        await self._queue_coverart(apikey, metadata)
        return result

    def providerinfo(self) -> list[str]:  # pylint: disable=no-self-use
        """return list of what is provided by this plug-in"""
        return [
            "artistbannerraw",
            "artistlongbio",
            "artistlogoraw",
            "artistthumbnailraw",
            "coverimageraw",
        ]

    def connect_settingsui(self, qwidget: "QWidget", uihelp: Any) -> None:
        """pass"""

    def load_settingsui(self, qwidget: "QWidget") -> None:
        """draw the plugin's settings page"""
        if self.config.cparser.value("theaudiodb/enabled", type=bool):
            qwidget.theaudiodb_checkbox.setChecked(True)
        else:
            qwidget.theaudiodb_checkbox.setChecked(False)
        qwidget.apikey_lineedit.setText(self.config.cparser.value("theaudiodb/apikey"))
        qwidget.bio_iso_lineedit.setText(self.config.cparser.value("theaudiodb/bio_iso"))

        for field in ["banners", "bio", "coverart", "fanart", "logos", "thumbnails"]:
            func = getattr(qwidget, f"{field}_checkbox")
            func.setChecked(self.config.cparser.value(f"theaudiodb/{field}", type=bool))
        if self.config.cparser.value("theaudiodb/bio_iso_en_fallback", type=bool):
            qwidget.bio_iso_en_checkbox.setChecked(True)
        else:
            qwidget.bio_iso_en_checkbox.setChecked(False)

    def verify_settingsui(self, qwidget: "QWidget") -> None:
        """pass"""

    def save_settingsui(self, qwidget: "QWidget") -> None:
        """take the settings page and save it"""

        self.config.cparser.setValue("theaudiodb/enabled", qwidget.theaudiodb_checkbox.isChecked())
        self.config.cparser.setValue("theaudiodb/apikey", qwidget.apikey_lineedit.text())
        self.config.cparser.setValue("theaudiodb/bio_iso", qwidget.bio_iso_lineedit.text())
        self.config.cparser.setValue(
            "theaudiodb/bio_iso_en_fallback", qwidget.bio_iso_en_checkbox.isChecked()
        )

        for field in ["banners", "bio", "coverart", "fanart", "logos", "thumbnails", "websites"]:
            func = getattr(qwidget, f"{field}_checkbox")
            self.config.cparser.setValue(f"theaudiodb/{field}", func.isChecked())

    def defaults(self, qsettings: "QSettings") -> None:
        for field in ["banners", "bio", "coverart", "fanart", "logos", "thumbnails", "websites"]:
            qsettings.setValue(f"theaudiodb/{field}", True)

        qsettings.setValue("theaudiodb/enabled", True)
        qsettings.setValue("theaudiodb/apikey", DEFAULT_THEAUDIODB_API_KEY)
        qsettings.setValue("theaudiodb/bio_iso", "EN")
        qsettings.setValue("theaudiodb/bio_iso_en_fallback", True)
