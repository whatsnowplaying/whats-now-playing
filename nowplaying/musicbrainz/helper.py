#!/usr/bin/env python3
# pylint: disable=invalid-name
"""support for musicbrainz"""

import asyncio
import contextlib
import logging
import os
import sys
from typing import Any

import nowplaying.apicache
import nowplaying.bootstrap
import nowplaying.config
from wnpmb import (
    MusicBrainzClient,
    MusicBrainzError,
    WNPCacheAdapter,
    extract_artist_urls,
)
from wnpmb.client._base import RetrySettings
from wnpmb.normalization import normalize, select_best_release


logger = logging.getLogger(__name__)


class MusicBrainzHelper:
    """handler for NowPlaying"""

    def __init__(self, config=None):
        if config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()

        self.emailaddressset = False
        self.mb_client = MusicBrainzClient(
            retry_settings=RetrySettings(max_retries=2, wait=0.5),
        )

    def _setemail(self):
        """make sure the musicbrainz fetch has an email address set
        according to their requirements"""
        if not self.emailaddressset:
            emailaddress = (
                self.config.cparser.value("musicbrainz/emailaddress")
                or "aw+wnp@effectivemachines.com"
            )
            self.mb_client.set_useragent("whats-now-playing", self.config.version, emailaddress)
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
        try:
            async with self.mb_client:
                mbid = await self.mb_client.find_recording(
                    title=title,
                    artist=artist,
                    album=album,
                )
        except MusicBrainzError:
            logger.exception("MusicBrainz error during find_recording")
            return None
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
        elif metadata.get("isrc"):
            logger.debug("Preprocessing with musicbrainz isrc")
            addmeta = await self.isrc(metadata["isrc"])
        elif metadata.get("musicbrainzartistid"):
            logger.debug("Preprocessing with musicbrainz artistid")
            addmeta = await self.artistids(metadata["musicbrainzartistid"])
        elif metadata.get("artist") and metadata.get("title"):
            logger.debug("Attempting lastditcheffort lookup")
            addmeta = await self.lastditcheffort(metadata)
        return addmeta

    async def isrc(self, isrclist):
        """lookup musicbrainz information based upon isrc"""
        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        self._setemail()

        try:
            async with self.mb_client:
                mbid = await self.mb_client.resolve_recording_by_isrc(isrclist)
        except MusicBrainzError:
            logger.exception("MusicBrainz error during ISRC lookup")
            return None

        if mbid:
            return await self.recordingid(mbid)
        return None

    async def recordingid(self, recordingid):
        """lookup the musicbrainz information based upon recording id"""
        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            return None

        async def fetch_func():
            return await self._recordingid_uncached(recordingid)

        return await nowplaying.apicache.cached_fetch(
            provider="musicbrainz",
            artist_name="recording",
            endpoint=f"recording/{recordingid}",
            fetch_func=fetch_func,
            ttl_seconds=7 * 24 * 60 * 60,
        )

    async def _recordingid_uncached(self, recordingid) -> dict:
        """uncached version of recordingid lookup"""
        self._setemail()

        newdata: dict[str, Any] = {}
        try:
            async with self.mb_client:
                mb_data = await self.mb_client.get_recording_by_id(recordingid)
                if not mb_data:
                    return {}

                enriched = await self.mb_client.process_recording_data(mb_data, recordingid)

                # Map wnpmb key names to WNP TrackMetadata key names
                newdata = {
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

                # Cover art
                best_release = select_best_release(mb_data.get("releases", []))
                if best_release:
                    if best_release.get("cover-art-archive", {}).get("artwork") is True:
                        with contextlib.suppress(Exception):
                            newdata["coverimageraw"] = await self.mb_client.get_image_front(
                                best_release["id"]
                            )

                    if not newdata.get("coverimageraw") and best_release.get(
                        "release-group", {}
                    ).get("id"):
                        with contextlib.suppress(Exception):
                            newdata["coverimageraw"] = await self.mb_client.get_image_front(
                                best_release["release-group"]["id"], "release-group"
                            )
        except MusicBrainzError:
            logger.exception("MusicBrainz error fetching recording %s", recordingid)
            return {}

        if newdata.get("musicbrainzartistid"):
            newdata["artistwebsites"] = await self._websites(newdata["musicbrainzartistid"])

        return newdata

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
                    if src == "discogs" and self.config.cparser.value(
                        "musicbrainz/discogs", type=bool
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
