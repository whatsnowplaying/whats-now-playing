#!/usr/bin/env python3
# pylint: disable=invalid-name
"""support for musicbrainz"""

import asyncio
import logging
import os
import sys
from typing import Any, NamedTuple

import orjson
from wnpmb import (
    MusicBrainzClient,
    MusicBrainzError,
    RateLimitError,
    ResponseError,
    extract_artist_urls,
)
from wnpmb.client._base import RetrySettings
from wnpmb.normalization import normalize

import nowplaying.bootstrap
import nowplaying.datacache
import nowplaying.config
import nowplaying.utils.metadata

logger = logging.getLogger(__name__)

_MB_TTL = 7 * 24 * 3600


class _WNPDatacacheAdapter:
    """Adapts nowplaying.datacache.DataStorage to the wnpmb MusicBrainzCache protocol.

    Replaces WNPCacheAdapter (which wrapped apicache) so that MusicBrainz data
    is stored in the unified datacache rather than the old APIResponseCache.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def _url(provider: str, cache_key: str) -> str:
        """Build the synthetic datacache URL for a wnpmb cache entry."""
        return f"wnpmb://{provider}/{cache_key}"

    async def get(self, provider: str, cache_key: str) -> Any | None:
        """Return cached data for (provider, cache_key), or None on miss/expiry."""
        storage = nowplaying.datacache.get_shared_storage()
        cached = await storage.retrieve_by_url(self._url(provider, cache_key))
        if cached is None:
            return None
        data, _ = cached
        try:
            return orjson.loads(data)
        except orjson.JSONDecodeError:
            return None

    async def set(  # pylint: disable=too-many-arguments
        self,
        provider: str,
        cache_key: str,
        data: Any,
        ttl: int,
        url: str | None = None,  # pylint: disable=unused-argument
    ) -> None:
        """Store data for (provider, cache_key) with the given TTL."""
        storage = nowplaying.datacache.get_shared_storage()
        try:
            await storage.store(
                url=self._url(provider, cache_key),
                identifier=cache_key,
                data_type="musicbrainz",
                provider=provider,
                data_value=orjson.dumps(data),
                ttl_seconds=ttl,
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.warning("datacache store failed for wnpmb %s/%s: %s", provider, cache_key, err)


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
                or "wnp@effectivemachines.com"
            )
            self.mb_client.set_useragent(emailaddress)
            self.mb_client.cache_service = _WNPDatacacheAdapter()
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
            return _RecordingLookup(
                data=await self.recordingid(exact_mbid, track_data=metadata),
                is_fallback=False,
            )
        if fallback_mbid:
            return _RecordingLookup(
                data=await self.recordingid(fallback_mbid, track_data=metadata),
                is_fallback=True,
            )
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
            addmeta = await self.recordingid(
                metadata["musicbrainzrecordingid"], track_data=metadata
            )
            if addmeta:
                return addmeta

        if metadata.get("isrc"):
            logger.debug("Preprocessing with musicbrainz isrc")
            addmeta = await self.isrc(metadata["isrc"], track_data=metadata)
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

    async def isrc(self, isrclist, track_data: dict | None = None):
        """lookup musicbrainz information based upon isrc.

        track_data: optional original metadata forwarded to the recording lookup
        so album/year hints reach wnpmb's release scorer.
        """
        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        self._setemail()

        async def _resolve():
            async with self.mb_client:
                return await self.mb_client.resolve_recording_by_isrc(isrclist)

        mbid = await self._mb_op_with_retry(_resolve, "resolve_recording_by_isrc", None)
        if mbid:
            return await self.recordingid(mbid, track_data=track_data)
        return None

    async def recordingid(self, recordingid, track_data: dict | None = None):
        """lookup the musicbrainz information based upon recording id.

        track_data: optional original metadata passed to wnpmb's release scorer
        so album/year hints from upstream (e.g. EarShot) influence which release
        is picked.  The recording cache is keyed only on recording_id, so the
        first call's hint determines the cached pick for the TTL period.
        """
        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        async def fetch_func():
            return await self._recordingid_uncached(recordingid, track_data=track_data)

        data = await nowplaying.datacache.cached_fetch(
            provider="musicbrainz",
            artist_name="recording",
            endpoint=f"recording/{recordingid}",
            fetch_func=fetch_func,
            ttl_seconds=_MB_TTL,
            negative_ttl=5 * 60,  # 5 min for "not in MB" — matches wnpmb not_found TTL
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

        Results are cached per entity in their own datacache entries so that
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
                    return None
                except ResponseError as err:
                    if "404" in str(err):
                        # No cover art exists for this release — stable negative result
                        logger.debug("CAA 404 for %s/%s", entity_type, entity_id)
                        return {}
                    # Timeout, connection error, 5xx — transient, do not cache
                    logger.debug("CAA transient error for %s/%s: %s", entity_type, entity_id, err)
                    return None
                except Exception:  # pylint: disable=broad-except
                    logger.debug("CAA unexpected error for %s/%s", entity_type, entity_id)
                    return None

            result = await nowplaying.datacache.cached_fetch(
                provider="musicbrainz_caa",
                artist_name=entity_type,
                endpoint=f"front/{entity_id}",
                fetch_func=_do_fetch,
                ttl_seconds=_MB_TTL,
                negative_ttl=24 * 3600,  # 24h for "no cover art" — art may be added later
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

    async def _recordingid_uncached(
        self, recordingid, track_data: dict | None = None
    ) -> dict | None:
        """uncached version of recordingid lookup.

        track_data: optional original metadata (e.g. EarShot's Shazam result)
        whose 'album', 'year', 'date' fields wnpmb uses as release-scoring hints.

        Returns None on rate-limit / MusicBrainzError so the caller does not
        cache a poisoned empty result for the 7-day TTL.  Returns {} when the
        lookup succeeded but MusicBrainz genuinely has no recording — caching
        that negative result is desirable.
        """
        self._setemail()

        async def _fetch() -> dict:
            async with self.mb_client:
                mb_data = await self.mb_client.get_recording_by_id(recordingid)
                if not mb_data:
                    return {}

                enriched = await self.mb_client.process_recording_data(
                    mb_data, recordingid, original_track_data=track_data
                )

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

        return await self._mb_op_with_retry(_fetch, "get_recording_by_id", None)

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
