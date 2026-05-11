#!/usr/bin/env python3
# pylint: disable=invalid-name
"""support for musicbrainz"""

import asyncio
import logging
import os
import sys
from typing import Any, NamedTuple

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


class _RecordingLookup(NamedTuple):
    """Result of _lastditchrid: resolved data and whether it came from a stripped-title fallback."""

    data: dict | None
    is_fallback: bool


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

    async def _lastditchrid(self, metadata) -> _RecordingLookup:
        """extract fields and run search

        Returns a _RecordingLookup where is_fallback=True means the match was
        found only after stripping a generic suffix from the title — caller should
        use artist data only and not treat the recording fields as authoritative.
        """
        if metadata.get("musicbrainzrecordingid"):
            logger.debug("Skipping fallback: already have a rid")
            return _RecordingLookup(data=None, is_fallback=False)

        artist = metadata.get("artist")
        title = metadata.get("title")
        album = metadata.get("album")

        if not artist or not title:
            return _RecordingLookup(data=None, is_fallback=False)

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

        result = await self._mb_op_with_retry(_find, "find_recording", (None, None))
        exact_mbid, fallback_mbid = result if result else (None, None)
        if exact_mbid:
            return _RecordingLookup(data=await self.recordingid(exact_mbid), is_fallback=False)
        if fallback_mbid:
            return _RecordingLookup(data=await self.recordingid(fallback_mbid), is_fallback=True)
        return _RecordingLookup(data=None, is_fallback=False)

    async def lastditcheffort(self, metadata):
        """there is like no data, so..."""

        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        self._setemail()

        lookup = await self._lastditchrid(metadata)
        riddata = lookup.data

        if riddata:
            use_artist_only = lookup.is_fallback or (
                normalize(riddata.get("title")) != normalize(metadata.get("title"))
            )
            if use_artist_only:
                logger.debug(
                    "Using artist data only: %s",
                    "fallback match on stripped title" if lookup.is_fallback else "title mismatch",
                )

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

        # Fetch cover art separately from the recording cache so that CAA
        # failures (timeout, 404, network error) do not poison the 7-day
        # recording cache entry.  Cover art is cached in its own entry;
        # failures are not cached so they are retried on the next play.
        if data and not data.get("coverimageraw"):
            if self.config.cparser.value("musicbrainz/coverart", type=bool, defaultValue=True):
                release_id = data.get("musicbrainzalbumid")
                rg_id = data.get("musicbrainzreleasegroupid")
                if release_id or rg_id:
                    if coverart := await self._fetch_cover_art(release_id, rg_id):
                        data = dict(data)
                        data["coverimageraw"] = coverart

        return data

    async def _fetch_cover_art(self, release_id: str | None, rg_id: str | None) -> bytes | None:
        """Fetch front cover art from CAA, trying release then release-group.

        Results are cached per entity in their own apicache entries so that
        a successful fetch is reused on subsequent plays without re-hitting
        CAA.  Failed fetches are NOT cached so they are retried next time.
        """
        self._setemail()

        async def _try(entity_id: str, entity_type: str) -> bytes | None:
            async def _do_fetch() -> dict | None:
                try:
                    async with self.mb_client:
                        logger.debug("Fetching CAA cover art for %s/%s", entity_type, entity_id)
                        raw = await self.mb_client.get_image_front(entity_id, entity_type)
                        if raw:
                            logger.debug(
                                "Got CAA cover art (%d bytes) for %s/%s",
                                len(raw),
                                entity_type,
                                entity_id,
                            )
                            return {"coverimageraw": raw}
                except Exception:  # pylint: disable=broad-except
                    logger.debug("CAA cover art fetch failed for %s/%s", entity_type, entity_id)
                return None

            result = await nowplaying.apicache.cached_fetch(
                provider="musicbrainz_caa",
                artist_name=entity_type,
                endpoint=f"front/{entity_id}",
                fetch_func=_do_fetch,
                ttl_seconds=7 * 24 * 60 * 60,
            )
            if result and isinstance(result.get("coverimageraw"), bytes):
                return result["coverimageraw"]
            return None

        if release_id:
            if art := await _try(release_id, "release"):
                return art
        if rg_id:
            if art := await _try(rg_id, "release-group"):
                return art
        return None

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
                # Store release ID so the separate cover-art fetch can use it
                if "musicbrainz_release_id" in enriched:
                    newdata["musicbrainzalbumid"] = enriched["musicbrainz_release_id"]
                if "musicbrainz_release_group_id" in enriched:
                    newdata["musicbrainzreleasegroupid"] = enriched["musicbrainz_release_group_id"]
                if "genres" in enriched:
                    newdata["genres"] = enriched["genres"]
                    newdata["genre"] = "/".join(enriched["genres"])
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
