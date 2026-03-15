#!/usr/bin/env python3
"""support for last.fm artist metadata"""

import logging
import urllib.parse
from typing import TYPE_CHECKING, Any

import aiohttp

import nowplaying.apicache
import nowplaying.artistextras
import nowplaying.config
import nowplaying.utils
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
    from PySide6.QtWidgets import QWidget


class Plugin(nowplaying.artistextras.ArtistExtrasPlugin):
    """handler for Last.fm"""

    API_URL = "https://ws.audioscrobbler.com/2.0/"

    def __init__(
        self, config: nowplaying.config.ConfigFile | None = None, qsettings: "QSettings" = None
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname: str = "Last.fm"
        self.priority: int = 60

    async def _fetch_async(
        self, apikey: str, artist: str, mbid: str | None = None, lang: str = "en"
    ) -> dict | None:
        """Fetch artist.getinfo from Last.fm API"""
        if mbid:
            url = (
                f"{self.API_URL}?method=artist.getinfo"
                f"&mbid={urllib.parse.quote(mbid)}"
                f"&api_key={apikey}"
                f"&format=json&autocorrect=1"
                f"&lang={lang}"
            )
        else:
            url = (
                f"{self.API_URL}?method=artist.getinfo"
                f"&artist={urllib.parse.quote(artist)}"
                f"&api_key={apikey}"
                f"&format=json&autocorrect=1"
                f"&lang={lang}"
            )
        delay = self.calculate_delay()
        try:
            connector = nowplaying.utils.create_http_connector()
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=delay),
                ) as response:
                    if response.status != 200:
                        logging.error("Last.fm HTTP error %s for %s", response.status, artist)
                        return None
                    data = await response.json()
                    if "error" in data:
                        logging.info("Last.fm: %s for %s", data.get("message"), artist)
                        return None
                    return data
        except TimeoutError:
            logging.error("Last.fm _fetch_async hit timeout for %s", artist)
            return None
        except Exception:  # pragma: no cover pylint: disable=broad-except
            logging.exception("Last.fm async hit unexpected error for %s", artist)
            return None

    @staticmethod
    def _clean_bio(raw: str) -> str:
        """Strip HTML and Last.fm trailing attribution from bio text"""
        htmlfilter = nowplaying.utils.HTMLFilter()
        htmlfilter.feed(raw)
        text = htmlfilter.text.strip()
        # Last.fm appends "Read more on Last.fm" — remove it
        text = text.split("Read more on Last.fm")[0].strip()
        return text

    async def download_async(
        self, metadata: TrackMetadata | None = None, imagecache: Any = None
    ) -> TrackMetadata | None:
        """async do data lookup"""
        if not self.config.cparser.value("lastfm/enabled", type=bool):
            return None

        if not metadata or not metadata.get("artist"):
            return None

        apikey = self.config.cparser.value("lastfm/apikey")
        if not apikey:
            logging.debug("No Last.fm API key.")
            return None

        artist = metadata["artist"]
        mbid = (metadata.get("musicbrainzartistid") or [None])[0]
        lang = (self.config.cparser.value("lastfm/bio_lang") or "en").lower()

        async def fetch_func():
            return await self._fetch_async(apikey, artist, mbid=mbid, lang=lang)

        cache_id = mbid if mbid else urllib.parse.quote(artist)
        data = await nowplaying.apicache.cached_fetch(
            provider="lastfm",
            artist_name=artist,
            endpoint=f"artist.getinfo/{lang}/{cache_id}",
            fetch_func=fetch_func,
            ttl_seconds=None,
        )
        if not data:
            return None

        artist_info = data.get("artist")
        if not artist_info:
            return None

        result: TrackMetadata = {}

        if not metadata.get("artistlongbio") and self.config.cparser.value(
            "lastfm/bio", type=bool
        ):
            raw_bio = (artist_info.get("bio") or {}).get("content") or ""
            if (
                not raw_bio
                and lang != "en"
                and self.config.cparser.value("lastfm/bio_lang_en_fallback", type=bool)
            ):
                data = await nowplaying.apicache.cached_fetch(
                    provider="lastfm",
                    artist_name=artist,
                    endpoint=f"artist.getinfo/en/{cache_id}",
                    fetch_func=lambda: self._fetch_async(apikey, artist, mbid=mbid, lang="en"),
                    ttl_seconds=None,
                )
                raw_bio = ((data or {}).get("artist") or {}).get("bio", {}).get("content") or ""
            if bio := self._clean_bio(raw_bio):
                result["artistlongbio"] = bio

        if not metadata.get("artistwebsites") and self.config.cparser.value(
            "lastfm/websites", type=bool
        ):
            if url := artist_info.get("url"):
                result["artistwebsites"] = [url]

        return result or None

    def providerinfo(self) -> list[str]:  # pylint: disable=no-self-use
        """return list of what is provided by this plug-in"""
        return [
            "artistlongbio",
            "artistwebsites",
        ]

    def connect_settingsui(self, qwidget: "QWidget", uihelp: Any) -> None:
        """pass"""

    def load_settingsui(self, qwidget: "QWidget") -> None:
        """draw the plugin's settings page"""
        qwidget.lastfm_checkbox.setChecked(self.config.cparser.value("lastfm/enabled", type=bool))
        qwidget.apikey_lineedit.setText(self.config.cparser.value("lastfm/apikey"))
        for field in ["bio", "websites"]:
            getattr(qwidget, f"{field}_checkbox").setChecked(
                self.config.cparser.value(f"lastfm/{field}", type=bool)
            )
        qwidget.bio_lang_lineedit.setText(self.config.cparser.value("lastfm/bio_lang") or "en")
        qwidget.bio_lang_en_checkbox.setChecked(
            self.config.cparser.value("lastfm/bio_lang_en_fallback", type=bool)
        )

    def verify_settingsui(self, qwidget: "QWidget") -> bool:
        """pass"""
        return True

    def save_settingsui(self, qwidget: "QWidget") -> None:
        """take the settings page and save it"""
        self.config.cparser.setValue("lastfm/enabled", qwidget.lastfm_checkbox.isChecked())
        self.config.cparser.setValue("lastfm/apikey", qwidget.apikey_lineedit.text())
        for field in ["bio", "websites"]:
            self.config.cparser.setValue(
                f"lastfm/{field}", getattr(qwidget, f"{field}_checkbox").isChecked()
            )
        self.config.cparser.setValue("lastfm/bio_lang", qwidget.bio_lang_lineedit.text())
        self.config.cparser.setValue(
            "lastfm/bio_lang_en_fallback", qwidget.bio_lang_en_checkbox.isChecked()
        )

    def defaults(self, qsettings: "QSettings") -> None:
        for field in ["bio", "websites"]:
            qsettings.setValue(f"lastfm/{field}", True)
        qsettings.setValue("lastfm/enabled", False)
        qsettings.setValue("lastfm/apikey", "")
        qsettings.setValue("lastfm/bio_lang", "en")
        qsettings.setValue("lastfm/bio_lang_en_fallback", True)
