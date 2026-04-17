#!/usr/bin/env python3
# pylint: disable=invalid-name
"""support for musicbrainz"""

import asyncio
import contextlib
import logging
import os
import sys
from typing import Any

from wnpmb import (
    MusicBrainzClient,
    MusicBrainzError,
    RateLimitError,
    WNPCacheAdapter,
    extract_artist_urls,
)
from wnpmb.client._base import RetrySettings
from wnpmb.normalization import normalize

import nowplaying.apicache
import nowplaying.bootstrap
import nowplaying.config
import nowplaying.utils.metadata

logger = logging.getLogger(__name__)


class MusicBrainzHelper:
    """handler for NowPlaying"""

    def __init__(self, config=None, test_mode: bool = False):
        if config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()

        self.test_mode = test_mode
        self.emailaddressset = False
        self.mb_client = MusicBrainzClient(
            timeout=5.0,
            retry_settings=RetrySettings(max_retries=2, wait=0.5, timeout_retries=1),
        )

    async def _mb_op_with_retry(self, operation, error_msg: str, default: Any) -> Any:
        """Run an async MB operation, retrying on RateLimitError only in test_mode.

        In live performance mode (test_mode=False) a rate-limit failure returns
        the default immediately so the DJ is never blocked waiting for retries.
        """
        max_attempts = 3 if self.test_mode else 1
        for attempt in range(max_attempts):
            if attempt > 0:
                sleep_time = 10 * attempt
                logger.warning(
                    "Rate limited; sleeping %ds before retry %d/%d",
                    sleep_time,
                    attempt,
                    max_attempts - 1,
                )
                await asyncio.sleep(sleep_time)
            try:
                return await operation()
            except RateLimitError:
                if attempt < max_attempts - 1:
                    continue
                logger.warning("Rate limited after %d attempts: %s", max_attempts, error_msg)
                return default
            except MusicBrainzError:
                logger.exception("MusicBrainz error: %s", error_msg)
                return default
        return default

    def _setemail(self):
        """make sure the musicbrainz fetch has an email address set
        according to their requirements"""
        if not self.emailaddressset:
            emailaddress = (
                self.config.cparser.value("musicbrainz/emailaddress")
                or "aw+wnp@effectivemachines.com"
            )
            self.mb_client.set_useragent(emailaddress)
            self.mb_client.cache_service = WNPCacheAdapter(nowplaying.apicache.get_cache())
            self.emailaddressset = True

    async def _lastditchrid(self, metadata):
        """extract fields and run search"""
        if metadata.get("musicbrainzrecordingid"):
            logger.debug("Skipping fallback: already have a rid")
            return None

        artist = metadata.get("artist")
        title = metadata.get("title")
        album = metadata.get("album")

        if not artist or not title:
            return None

        self._setemail()
        year = nowplaying.utils.metadata.get_best_year(metadata)

        async def _find():
            async with self.mb_client:
                return await self.mb_client.find_recording(
                    title=title,
                    artist=artist,
                    album=album,
                    year=year,
                )

        mbid = await self._mb_op_with_retry(_find, "find_recording", None)
        if mbid:
            return await self.recordingid(mbid)
        return None

    async def lastditcheffort(self, metadata):
        """there is like no data, so..."""

        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        self._setemail()

        riddata = await self._lastditchrid(metadata)

        if riddata:
            if normalize(riddata.get("title")) != normalize(metadata.get("title")):
                logger.debug("No title match, so just using artist data")

                strict_album_matching = self.config.cparser.value(
                    "musicbrainz/strict_album_matching", True, type=bool
                )

                if strict_album_matching and metadata.get("album"):
                    logger.debug(
                        "Strict album matching enabled: rejecting partial match for album request"
                    )
                    return {}

                for delitem in [
                    "album",
                    "coverimageraw",
                    "date",
                    "genre",
                    "genres",
                    "label",
                    "musicbrainzrecordingid",
                ]:
                    if delitem in riddata:
                        del riddata[delitem]

            logger.debug(
                "metadata added artistid = %s / recordingid = %s",
                riddata.get("musicbrainzartistid"),
                riddata.get("musicbrainzrecordingid"),
            )
        return riddata or {}

    async def recognize(self, metadata):
        """fill in any blanks from musicbrainz"""

        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        addmeta = {}

        if metadata.get("musicbrainzrecordingid"):
            logger.debug("Preprocessing with musicbrainz recordingid")
            addmeta = await self.recordingid(metadata["musicbrainzrecordingid"])
            if addmeta:
                return addmeta

        if metadata.get("isrc"):
            logger.debug("Preprocessing with musicbrainz isrc")
            addmeta = await self.isrc(metadata["isrc"])
            if addmeta:
                return addmeta

        if metadata.get("musicbrainzartistid"):
            logger.debug("Preprocessing with musicbrainz artistid")
            addmeta = await self.artistids(metadata["musicbrainzartistid"])
            if addmeta:
                return addmeta

        if metadata.get("artist") and metadata.get("title"):
            logger.debug("Attempting lastditcheffort lookup")
            addmeta = await self.lastditcheffort(metadata)

        return addmeta

    async def isrc(self, isrclist):
        """lookup musicbrainz information based upon isrc"""
        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        self._setemail()

        async def _resolve():
            async with self.mb_client:
                return await self.mb_client.resolve_recording_by_isrc(isrclist)

        mbid = await self._mb_op_with_retry(_resolve, "resolve_recording_by_isrc", None)
        if mbid:
            return await self.recordingid(mbid)
        return None

    async def recordingid(self, recordingid):
        """lookup the musicbrainz information based upon recording id"""
        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        async def fetch_func():
            return await self._recordingid_uncached(recordingid)

        data = await nowplaying.apicache.cached_fetch(
            provider="musicbrainz",
            artist_name="recording",
            endpoint=f"recording/{recordingid}",
            fetch_func=fetch_func,
            ttl_seconds=7 * 24 * 60 * 60,
        )
        if data and data.get("musicbrainzartistid"):
            # artistwebsites is config-dependent (which URLs to inject depends on
            # user settings), so it must be computed fresh on every call rather
            # than baked into the cached recording data
            data = dict(data)
            data["artistwebsites"] = await self._websites(data["musicbrainzartistid"])
        return data

    async def _recordingid_uncached(self, recordingid) -> dict:
        """uncached version of recordingid lookup"""
        self._setemail()

        async def _fetch() -> dict:
            async with self.mb_client:
                mb_data = await self.mb_client.get_recording_by_id(recordingid)
                if not mb_data:
                    return {}

                enriched = await self.mb_client.process_recording_data(mb_data, recordingid)

                # Map wnpmb key names to WNP TrackMetadata key names
                newdata: dict[str, Any] = {
                    "musicbrainzrecordingid": enriched["musicbrainz_recording_id"],
                }
                for key in ("title", "artist", "album", "date", "label"):
                    if key in enriched:
                        newdata[key] = enriched[key]
                if "musicbrainz_artist_id" in enriched:
                    newdata["musicbrainzartistid"] = enriched["musicbrainz_artist_id"]
                if "genres" in enriched:
                    newdata["genres"] = enriched["genres"]
                    newdata["genre"] = "/".join(enriched["genres"])

                # Cover art — use the release already selected by process_recording_data
                if release_id := enriched.get("musicbrainz_release_id"):
                    with contextlib.suppress(Exception):
                        newdata["coverimageraw"] = await self.mb_client.get_image_front(release_id)
                if not newdata.get("coverimageraw"):
                    if rg_id := enriched.get("musicbrainz_release_group_id"):
                        with contextlib.suppress(Exception):
                            newdata["coverimageraw"] = await self.mb_client.get_image_front(
                                rg_id, "release-group"
                            )
                return newdata

        return await self._mb_op_with_retry(_fetch, "get_recording_by_id", {})

    async def artistids(self, idlist):
        """add data available via musicbrainz artist ids"""

        self._setemail()

        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        return {"artistwebsites": await self._websites(idlist)}

    async def _websites(self, idlist):
        if not idlist:
            return None

        sitelist = []
        async with self.mb_client:
            for artistid in idlist:
                if self.config.cparser.value("musicbrainz/musicbrainz", type=bool):
                    sitelist.append(f"https://musicbrainz.org/artist/{artistid}")

                webdata = None
                try:
                    webdata = await self.mb_client.get_artist_by_id(
                        artistid, includes=["url-rels"]
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.exception("MusicBrainz does not know artistid %s", artistid)
                    continue

                if not webdata:
                    continue

                urls = extract_artist_urls(webdata)

                convdict = {
                    "bandcamp": "bandcamp",
                    "official homepage": "homepage",
                    "last.fm": "lastfm",
                    "discogs": "discogs",
                    "wikidata": "wikidata",
                }

                for src, dest in convdict.items():
                    if src not in urls:
                        continue
                    # inject Discogs URL from MB relations if either the full
                    # Discogs plugin is enabled OR the MB-level discogs toggle
                    # is on (allows MB→Discogs URL without the full plugin)
                    if src == "discogs" and (
                        self.config.cparser.value("discogs/enabled", type=bool)
                        or self.config.cparser.value("musicbrainz/discogs", type=bool)
                    ):
                        sitelist.append(urls[src])
                        logger.debug("placed %s", dest)
                    elif src == "wikidata":
                        sitelist.append(urls[src])
                    elif self.config.cparser.value(f"musicbrainz/{dest}", type=bool):
                        sitelist.append(urls[src])
                        logger.debug("placed %s", dest)

        return list(dict.fromkeys(sitelist))

    def providerinfo(self):  # pylint: disable=no-self-use
        """return list of what is provided by this recognition system"""
        return [
            "album",
            "artist",
            "artistwebsites",
            "coverimageraw",
            "date",
            "label",
            "title",
            "genre",
            "genres",
        ]


def main():
    """integration test"""
    isrc = sys.argv[1]

    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names()
    nowplaying.config.ConfigFile(bundledir=bundledir)
    musicbrainz = MusicBrainzHelper(config=nowplaying.config.ConfigFile(bundledir=bundledir))
    metadata = asyncio.run(musicbrainz.recordingid(isrc))
    if not metadata:
        print("No information")
        sys.exit(1)

    if "coverimageraw" in metadata:
        print("got an image")
        del metadata["coverimageraw"]
    print(metadata)


if __name__ == "__main__":
    main()
