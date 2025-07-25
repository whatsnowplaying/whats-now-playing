#!/usr/bin/env python3
"""start of support of theaudiodb"""

import asyncio
import logging
import logging.config
import logging.handlers
import urllib.parse

import aiohttp

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.artistextras
import nowplaying.apicache
import nowplaying.utils


class Plugin(nowplaying.artistextras.ArtistExtrasPlugin):
    """handler for TheAudioDB"""

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.fnstr = None
        self.displayname = "TheAudioDB"
        self.priority = 50

    @staticmethod
    def _filter(text):
        htmlfilter = nowplaying.utils.HTMLFilter()
        htmlfilter.feed(text)
        return htmlfilter.text

    async def _fetch_async(self, apikey, api):
        delay = self.calculate_delay()
        try:
            logging.debug("Fetching async %s", api)
            connector = nowplaying.utils.create_http_connector()
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    f"https://theaudiodb.com/api/v1/json/{apikey}/{api}",
                    timeout=aiohttp.ClientTimeout(total=delay),
                ) as response:
                    return await response.json()
        except asyncio.TimeoutError:
            logging.error("TheAudioDB _fetch_async hit timeout on %s", api)
            return None
        except Exception as error:  # pragma: no cover pylint: disable=broad-except
            logging.error("TheAudioDB async hit %s", error)
            return None

    async def _fetch_cached(self, apikey, api, artist_name):
        """Cached version of _fetch for better performance."""

        async def fetch_func():
            return await self._fetch_async(apikey, api)

        return await nowplaying.apicache.cached_fetch(
            provider="theaudiodb",
            artist_name=artist_name,
            endpoint=api.split(".")[0],  # Use the first part of API call as endpoint
            fetch_func=fetch_func,
            ttl_seconds=7 * 24 * 60 * 60,  # 7 days for TheAudioDB data
        )

    def _check_artist(self, artdata):
        """is this actually the artist we are looking for?"""
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

    def _handle_extradata(self, extradata, metadata, imagecache, used_musicbrainz=False):
        """deal with the various bits of data"""
        bio = self._extract_bio_data(extradata, metadata)
        if bio:
            metadata["artistlongbio"] = bio

        for artdata in extradata:
            if not self._check_artist(artdata):
                continue

            self._handle_website_data(artdata, metadata)
            if imagecache:
                self._handle_image_data(artdata, metadata, imagecache)

        self._correct_artist_name(extradata, metadata, used_musicbrainz)
        return metadata

    def _extract_bio_data(self, extradata, metadata):
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
            elif (
                self.config.cparser.value("theaudiodb/bio_iso_en_fallback", type=bool)
                and "strBiographyEN" in artdata
            ):
                bio += self._filter(artdata["strBiographyEN"])

        return bio

    def _handle_website_data(self, artdata, metadata):
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

    def _handle_image_data(self, artdata, metadata, imagecache):
        """Handle image data from TheAudioDB response"""
        self._queue_single_image(
            artdata,
            metadata,
            imagecache,
            "strArtistBanner",
            "artistbannerraw",
            "artistbanner",
            "banners",
        )
        self._queue_single_image(
            artdata, metadata, imagecache, "strArtistLogo", "artistlogoraw", "artistlogo", "logos"
        )
        self._queue_single_image(
            artdata,
            metadata,
            imagecache,
            "strArtistThumb",
            "artistthumbnailraw",
            "artistthumbnail",
            "thumbnails",
        )
        self._handle_fanart_data(artdata, metadata, imagecache)

    def _queue_single_image(  # pylint: disable=too-many-arguments
        self, artdata, metadata, imagecache, source_key, metadata_key, image_type, config_key
    ):
        """Queue a single image type from TheAudioDB data"""
        if (
            metadata.get(metadata_key)
            or not artdata.get(source_key)
            or not self.config.cparser.value(f"theaudiodb/{config_key}", type=bool)
        ):
            return

        imagecache.fill_queue(
            config=self.config,
            identifier=metadata["imagecacheartist"],
            imagetype=image_type,
            srclocationlist=[artdata[source_key]],
        )

    def _handle_fanart_data(self, artdata, metadata, imagecache):
        """Handle fanart data from TheAudioDB response"""
        if not self.config.cparser.value("theaudiodb/fanart", type=bool):
            return

        fanart_queued = False
        for num in ["", "2", "3", "4"]:
            artstring = f"strArtistFanart{num}"
            if not artdata.get(artstring):
                continue

            if not metadata.get("artistfanarturls"):
                metadata["artistfanarturls"] = []
            metadata["artistfanarturls"].append(artdata[artstring])

            if not fanart_queued:
                fanart_queued = True
                imagecache.fill_queue(
                    config=self.config,
                    identifier=metadata["imagecacheartist"],
                    imagetype="artistfanart",
                    srclocationlist=[artdata[artstring]],
                )

    def _correct_artist_name(self, extradata, metadata, used_musicbrainz):
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

    async def artistdatafrommbid_async(self, apikey, mbartistid, artist_name):
        """async cached version of artistdatafrommbid"""
        data = await self._fetch_cached(apikey, f"artist-mb.php?i={mbartistid}", artist_name)
        if not data or not data.get("artists"):
            return None
        return data

    async def artistdatafromname_async(self, apikey, artist):
        """async cached version of artistdatafromname"""
        if not artist:
            return None
        urlart = urllib.parse.quote(artist)
        data = await self._fetch_cached(apikey, f"search.php?s={urlart}", artist)
        if not data or not data.get("artists"):
            return None
        return data

    @staticmethod
    async def _cache_individual_artist(artist_data, artist_name):
        """Cache individual artist data by TheAudioDB ID to handle duplicates"""
        if not artist_data.get("idArtist"):
            return artist_data

        # Cache individual artist by their unique TheAudioDB ID
        async def fetch_func():
            return artist_data  # Already have the data, just cache it

        return await nowplaying.apicache.cached_fetch(
            provider="theaudiodb",
            artist_name=artist_name,
            endpoint=f"artist_{artist_data['idArtist']}",
            fetch_func=fetch_func,
            ttl_seconds=7 * 24 * 60 * 60,  # 7 days for TheAudioDB data
        )

    async def download_async(self, metadata=None, imagecache=None):  # pylint: disable=too-many-branches
        """async do data lookup"""

        if not self.config.cparser.value("theaudiodb/enabled", type=bool):
            return None

        if not metadata or not metadata.get("artist"):
            logging.debug("No artist; skipping")
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

        return self._handle_extradata(extradata, metadata, imagecache, used_musicbrainz)

    def providerinfo(self):  # pylint: disable=no-self-use
        """return list of what is provided by this plug-in"""
        return [
            "artistbannerraw",
            "artistlongbio",
            "artistlogoraw",
            "artistthumbnailraw",
            "theaudiodb-artistfanarturls",
        ]

    def connect_settingsui(self, qwidget, uihelp):
        """pass"""

    def load_settingsui(self, qwidget):
        """draw the plugin's settings page"""
        if self.config.cparser.value("theaudiodb/enabled", type=bool):
            qwidget.theaudiodb_checkbox.setChecked(True)
        else:
            qwidget.theaudiodb_checkbox.setChecked(False)
        qwidget.apikey_lineedit.setText(self.config.cparser.value("theaudiodb/apikey"))
        qwidget.bio_iso_lineedit.setText(self.config.cparser.value("theaudiodb/bio_iso"))

        for field in ["banners", "bio", "fanart", "logos", "thumbnails"]:
            func = getattr(qwidget, f"{field}_checkbox")
            func.setChecked(self.config.cparser.value(f"theaudiodb/{field}", type=bool))
        if self.config.cparser.value("theaudiodb/bio_iso_en_fallback", type=bool):
            qwidget.bio_iso_en_checkbox.setChecked(True)
        else:
            qwidget.bio_iso_en_checkbox.setChecked(False)

    def verify_settingsui(self, qwidget):
        """pass"""

    def save_settingsui(self, qwidget):
        """take the settings page and save it"""

        self.config.cparser.setValue("theaudiodb/enabled", qwidget.theaudiodb_checkbox.isChecked())
        self.config.cparser.setValue("theaudiodb/apikey", qwidget.apikey_lineedit.text())
        self.config.cparser.setValue("theaudiodb/bio_iso", qwidget.bio_iso_lineedit.text())
        self.config.cparser.setValue(
            "theaudiodb/bio_iso_en_fallback", qwidget.bio_iso_en_checkbox.isChecked()
        )

        for field in ["banners", "bio", "fanart", "logos", "thumbnails", "websites"]:
            func = getattr(qwidget, f"{field}_checkbox")
            self.config.cparser.setValue(f"theaudiodb/{field}", func.isChecked())

    def defaults(self, qsettings):
        for field in ["banners", "bio", "fanart", "logos", "thumbnails", "websites"]:
            qsettings.setValue(f"theaudiodb/{field}", False)

        qsettings.setValue("theaudiodb/enabled", False)
        qsettings.setValue("theaudiodb/apikey", "")
        qsettings.setValue("theaudiodb/bio_iso", "EN")
        qsettings.setValue("theaudiodb/bio_iso_en_fallback", True)
