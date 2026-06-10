#!/usr/bin/env python3
"""support for last.fm artist metadata"""

import logging
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

import httpx
import orjson

import nowplaying.artistextras
import nowplaying.config
import nowplaying.datacache
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

    async def _get_json(self, url: str) -> dict | None:  # pylint: disable=too-many-return-statements
        """Fetch a Last.fm API URL and return the parsed JSON, or None on error."""
        safe_url = re.sub(r"(api_key=)[^&]+", r"\1<redacted>", url)
        try:
            dc_client = self._get_datacache_client()
            await dc_client.initialize()
            if dc_client.in_cooldown("lastfm"):
                return None
            async with httpx.AsyncClient(timeout=self.calculate_delay()) as session:
                response = await session.get(url)
            if response.status_code == 429:
                try:
                    retry_after = max(1, int(response.headers.get("Retry-After", "60")))
                except ValueError:
                    retry_after = 60
                dc_client.set_retry_after("lastfm", retry_after)
                logging.warning("Last.fm rate limited (429), cooldown %ds", retry_after)
                return None
            if response.status_code == 404:
                logging.debug("Last.fm 404 for %s — artist/album not found", safe_url)
                return {}  # stable negative: cache with negative_ttl
            if response.status_code != 200:
                logging.warning("Last.fm HTTP %d for %s", response.status_code, safe_url)
                return None
            data = orjson.loads(response.content)
            if "error" in data:
                logging.debug("Last.fm API error: %s", data.get("message"))
                return None
            return data
        except httpx.TimeoutException:
            logging.error("Last.fm fetch timeout: %s", safe_url)
            return None
        except Exception:  # pragma: no cover pylint: disable=broad-except
            logging.exception("Last.fm fetch unexpected error: %s", safe_url)
            return None

    def _album_url(
        self, apikey: str, artist: str, album: str, album_mbid: str | None = None
    ) -> str:
        """Build a Last.fm album.getinfo URL."""
        if album_mbid:
            return (
                f"{self.API_URL}?method=album.getinfo"
                f"&mbid={urllib.parse.quote(album_mbid)}"
                f"&api_key={apikey}&format=json&autocorrect=1"
            )
        return (
            f"{self.API_URL}?method=album.getinfo"
            f"&artist={urllib.parse.quote(artist)}"
            f"&album={urllib.parse.quote(album)}"
            f"&api_key={apikey}&format=json&autocorrect=1"
        )

    def _artist_url(
        self, apikey: str, artist: str, mbid: str | None = None, lang: str = "en"
    ) -> str:
        """Build a Last.fm artist.getinfo URL."""
        if mbid:
            return (
                f"{self.API_URL}?method=artist.getinfo"
                f"&mbid={urllib.parse.quote(mbid)}"
                f"&api_key={apikey}&format=json&autocorrect=1&lang={lang}"
            )
        return (
            f"{self.API_URL}?method=artist.getinfo"
            f"&artist={urllib.parse.quote(artist)}"
            f"&api_key={apikey}&format=json&autocorrect=1&lang={lang}"
        )

    @staticmethod
    def _clean_bio(raw: str) -> str:
        """Strip HTML and Last.fm trailing attribution from bio text"""
        # Remove the Last.fm attribution link before parsing — the link text may be
        # localized (e.g. "Mehr bei Last.fm"), so match on the URL rather than the text
        raw = re.sub(
            r'<a\s[^>]*href="[^"]*last\.fm[^"]*"[^>]*>.*?</a>',
            "",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        htmlfilter = nowplaying.utils.HTMLFilter()
        htmlfilter.feed(raw)
        return htmlfilter.text.strip()

    async def _queue_coverart(self, apikey: str, metadata: TrackMetadata) -> None:
        """Fetch album cover art from Last.fm and queue for download"""
        if not self.config.cparser.value("lastfm/coverart", type=bool):
            return
        if metadata.get("coverimageraw"):
            return
        artist = metadata.get("artist")
        album = metadata.get("album")
        if not artist or not album:
            return
        album_mbid = metadata.get("musicbrainzalbumid") or None
        cache_id = (
            album_mbid
            if album_mbid
            else (f"{urllib.parse.quote(artist)}/{urllib.parse.quote(album)}")
        )
        album_data = await nowplaying.datacache.cached_fetch(
            provider="lastfm",
            artist_name=artist,
            endpoint=f"album.getinfo/{cache_id}",
            fetch_func=lambda: self._get_json(
                self._album_url(apikey, artist, album, album_mbid=album_mbid)
            ),
            ttl_seconds=None,
            negative_ttl=24 * 3600,  # 24h: artist/album not in Last.fm
        )
        images = ((album_data or {}).get("album") or {}).get("image") or []
        cover_url = next(
            (img["#text"] for img in reversed(images) if img.get("#text")),
            None,
        )
        if cover_url:
            await self.queue_front_cover(artist, album, cover_url, provider="lastfm")

    async def download_async(self, metadata: TrackMetadata | None = None) -> TrackMetadata | None:
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
            return await self._get_json(self._artist_url(apikey, artist, mbid=mbid, lang=lang))

        cache_id = mbid if mbid else urllib.parse.quote(artist)
        data = await nowplaying.datacache.cached_fetch(
            provider="lastfm",
            artist_name=artist,
            endpoint=f"artist.getinfo/{lang}/{cache_id}",
            fetch_func=fetch_func,
            ttl_seconds=None,
            negative_ttl=24 * 3600,  # 24h: artist/album not in Last.fm
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
                data = await nowplaying.datacache.cached_fetch(
                    provider="lastfm",
                    artist_name=artist,
                    endpoint=f"artist.getinfo/en/{cache_id}",
                    fetch_func=lambda: self._get_json(
                        self._artist_url(apikey, artist, mbid=mbid, lang="en")
                    ),
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

        await self._queue_coverart(apikey, metadata)

        return result or None

    def providerinfo(self) -> list[str]:  # pylint: disable=no-self-use
        """return list of what is provided by this plug-in"""
        return [
            "artistlongbio",
            "artistwebsites",
            "coverimageraw",
        ]

    def connect_settingsui(self, qwidget: "QWidget", uihelp: Any) -> None:
        """pass"""

    def load_settingsui(self, qwidget: "QWidget") -> None:
        """draw the plugin's settings page"""
        qwidget.lastfm_checkbox.setChecked(self.config.cparser.value("lastfm/enabled", type=bool))
        qwidget.apikey_lineedit.setText(self.config.cparser.value("lastfm/apikey"))
        for field in ["bio", "coverart", "websites"]:
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
        for field in ["bio", "coverart", "websites"]:
            self.config.cparser.setValue(
                f"lastfm/{field}", getattr(qwidget, f"{field}_checkbox").isChecked()
            )
        self.config.cparser.setValue("lastfm/bio_lang", qwidget.bio_lang_lineedit.text())
        self.config.cparser.setValue(
            "lastfm/bio_lang_en_fallback", qwidget.bio_lang_en_checkbox.isChecked()
        )

    def defaults(self, qsettings: "QSettings") -> None:
        for field in ["bio", "coverart", "websites"]:
            qsettings.setValue(f"lastfm/{field}", True)
        qsettings.setValue("lastfm/enabled", False)
        qsettings.setValue("lastfm/apikey", "")
        qsettings.setValue("lastfm/bio_lang", "en")
        qsettings.setValue("lastfm/bio_lang_en_fallback", True)
