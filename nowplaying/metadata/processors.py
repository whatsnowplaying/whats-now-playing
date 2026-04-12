#!/usr/bin/env python3
"""MetadataProcessors: orchestrate all metadata sources for a track"""

import asyncio
import copy
import datetime
import logging
import os
import pathlib
import re
import string
import sys
import textwrap
from typing import TYPE_CHECKING

import url_normalize

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.hostmeta
import nowplaying.metadata.biohistory
import nowplaying.metadata.tinytag_runner
import nowplaying.musicbrainz
import nowplaying.utils
import nowplaying.utils.artists
import nowplaying.utils.filters
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    import nowplaying.imagecache

NOTE_RE = re.compile("N(?i:ote):")
YOUTUBE_MATCH_RE = re.compile("^https?://[www.]*youtube.com/watch.v=")


class MetadataProcessors:  # pylint: disable=too-few-public-methods
    """Run through a bunch of different metadata processors"""

    def __init__(
        self, config: nowplaying.config.ConfigFile | None = None, test_mode: bool = False
    ):
        self.metadata: TrackMetadata = {}
        self.imagecache: nowplaying.imagecache.ImageCache | None = None
        self.test_mode = test_mode
        if config:
            self.config: nowplaying.config.ConfigFile = config
        else:
            self.config = nowplaying.config.ConfigFile()

        self.extraslist: dict[int, list[str]] = self._sortextras()
        self._bio_session_id: str = datetime.datetime.now().isoformat()
        if self.config.cparser.value("artistextras/bio_dedup", type=bool):
            self._biohistory: nowplaying.metadata.biohistory.ArtistBioHistory | None = (
                nowplaying.metadata.biohistory.ArtistBioHistory(self._bio_session_id)
            )
        else:
            self._biohistory = None

    def _sortextras(self) -> dict[int, list[str]]:
        extras = {}
        for plugin in self.config.plugins["artistextras"]:
            priority = self.config.pluginobjs["artistextras"][plugin].priority
            if not extras.get(priority):
                extras[priority] = []
            extras[priority].append(plugin)
        return dict(reversed(list(extras.items())))

    async def getmoremetadata(  # pylint: disable=too-many-branches
        self,
        metadata: TrackMetadata | None = None,
        imagecache: "nowplaying.imagecache.ImageCache | None" = None,
        skipplugins: bool = False,
    ) -> TrackMetadata:
        """take metadata and process it"""
        if metadata:
            self.metadata = metadata
        else:
            self.metadata = {}
        self.imagecache = imagecache

        if "artistfanarturls" not in self.metadata:
            self.metadata["artistfanarturls"] = []

        if (
            self.metadata.get("coverimageraw")
            and self.imagecache
            and self.metadata.get("album")
            and self.metadata.get("artist")
        ):
            identifier = f"{self.metadata['artist']}_{self.metadata['album']}"
            logging.debug("Placing provided front cover")
            _ = self.imagecache.put_db_cachekey(
                identifier=identifier,
                srclocation=f"{identifier}_provided_0",
                imagetype="front_cover",
                content=self.metadata["coverimageraw"],
            )

        try:
            for processor in "hostmeta", "tinytag", "image2png":
                logging.debug("running %s", processor)
                func = getattr(self, f"_process_{processor}")
                func()
        except Exception:  # pylint: disable=broad-except
            logging.exception("Ignoring sub-metaproc failure.")

        self._fix_filename_stem()
        self._fix_artist_in_title()

        await self._process_plugins(skipplugins)

        if "publisher" in self.metadata:
            if "label" not in self.metadata:
                self.metadata["label"] = self.metadata["publisher"]
            del self.metadata["publisher"]

        self._fix_dates()

        if self.metadata.get("artistlongbio") and not self.metadata.get("artistshortbio"):
            self._generate_short_bio()

        if not self.metadata.get("artistlongbio") and self.metadata.get("artistshortbio"):
            self.metadata["artistlongbio"] = self.metadata["artistshortbio"]

        self._uniqlists()

        self._strip_identifiers()
        self._fix_duration()
        return self.metadata

    def _fix_filename_stem(self) -> None:
        """if no title, derive it (and possibly artist) from the filename stem"""
        if not self.metadata.get("filename") or self.metadata.get("title"):
            return
        logging.debug("No title, so setting to filename stem")
        self.metadata["title"] = pathlib.Path(self.metadata["filename"]).stem
        if not self.metadata.get("artist"):
            for sep in (" \u2013 ", " - "):
                if sep in self.metadata.get("title", ""):
                    parts = self.metadata["title"].split(sep, 1)
                    if len(parts) == 2:
                        logging.debug("Splitting out filename stem to artist - title")
                        self.metadata["artist"] = parts[0].strip()
                        self.metadata["title"] = parts[1].strip()
                        break

    def _fix_artist_in_title(self) -> None:
        """strip redundant 'Artist - ' prefix from title field"""
        if " - " not in self.metadata.get("title", "") or not self.metadata.get("artist"):
            return
        artist = self.metadata["artist"]
        title = self.metadata["title"]
        parts = title.split(" - ", 1)
        prefix = parts[0].strip()
        translated_artist = artist.translate(nowplaying.utils.CUSTOM_TRANSLATE)
        # Only strip when the title prefix exactly equals the artist name or
        # starts with it followed by a space (feat. patterns).  This avoids
        # false positives where the artist name appears elsewhere in the title.
        prefix_lower = prefix.lower()
        if not any(
            prefix_lower == cand.lower() or prefix_lower.startswith(cand.lower() + " ")
            for cand in (artist, translated_artist)
        ):
            return
        logging.debug("Removing extra artist - from title")
        self.metadata["title"] = parts[1].strip()
        # If the prefix has a feat. component, append it to the current
        # artist so MB search can match all credited artists.
        # Preserve the existing (possibly non-ASCII) artist name so that
        # wnpmb's arid-based Pass 0 still fires for non-Latin scripts.
        for sep in [" feat.", " ft.", " featuring", " with "]:
            idx = prefix.lower().find(sep)
            if idx != -1:
                feat_part = prefix[idx:]
                logging.debug("Appending feat. to artist: %s", artist + feat_part)
                self.metadata["artist"] = artist + feat_part
                break

    def _fix_dates(self) -> None:
        """take care of year / date cleanup"""
        if not self.metadata:
            return

        if "year" in self.metadata:
            if "date" not in self.metadata:
                self.metadata["date"] = self.metadata["year"]
            del self.metadata["year"]

        if "date" in self.metadata and (not self.metadata["date"] or self.metadata["date"] == "0"):
            del self.metadata["date"]

        if date := self.metadata.get("date"):
            date = str(date)
            if len(date) == 8 and date.isdigit():
                self.metadata["date"] = f"{date[:4]}-{date[4:6]}-{date[6:]}"
            elif len(date) == 6 and date.isdigit():
                self.metadata["date"] = f"{date[:4]}-{date[4:]}"

    def _fix_duration(self) -> None:
        if not self.metadata or not self.metadata.get("duration"):
            return

        try:
            duration = int(float(self.metadata["duration"]))
        except ValueError:
            logging.debug("Cannot convert duration = %s", self.metadata["duration"])
            del self.metadata["duration"]
            return

        self.metadata["duration"] = duration

    def _strip_identifiers(self) -> None:
        if not self.metadata:
            return

        if self.metadata.get("title"):
            self.metadata["title"] = nowplaying.utils.filters.titlestripper(
                config=self.config, title=self.metadata["title"]
            )

    def _uniqlists(self) -> None:
        if not self.metadata:
            return

        if self.metadata.get("artistwebsites"):
            newlist = []
            for url in self.metadata["artistwebsites"]:
                try:
                    newlist.append(url_normalize.url_normalize(url))
                except ValueError as error:
                    logging.warning("Cannot normalize URL '%s': %s", url, error)
                    newlist.append(url)  # Keep original URL if normalization fails
                except Exception as error:  # pylint: disable=broad-except
                    logging.error(
                        "Unexpected error normalizing URL '%s': %s", url, error, exc_info=True
                    )
                    newlist.append(url)  # Keep original URL if normalization fails
            self.metadata["artistwebsites"] = newlist

        lists = ["artistwebsites", "isrc", "musicbrainzartistid"]
        for listname in lists:
            if self.metadata.get(listname):
                newlist = sorted(set(self.metadata[listname]))
                self.metadata[listname] = newlist

        if self.metadata.get("artistwebsites"):
            newlist = []
            for url in self.metadata["artistwebsites"]:
                if "wikidata" in url:
                    continue
                if "http:" not in url:
                    newlist.append(url)
                    continue

                testurl = url.replace("http:", "https:")
                if testurl not in self.metadata.get("artistwebsites"):
                    newlist.append(url)
            self.metadata["artistwebsites"] = newlist

    def _process_hostmeta(self) -> None:
        """add the host metadata so other subsystems can use it"""
        if self.metadata is None:
            self.metadata = {}

        if self.config.cparser.value("weboutput/httpenabled", type=bool):
            self.metadata["httpport"] = self.config.cparser.value("weboutput/httpport", type=int)
        hostmeta = nowplaying.hostmeta.gethostmeta()
        for key, value in hostmeta.items():
            self.metadata[key] = value

        # Add streaming platform channel information
        if twitchchannel := self.config.cparser.value("twitchbot/channel"):
            self.metadata["twitchchannel"] = twitchchannel
        if kickchannel := self.config.cparser.value("kick/channel"):
            self.metadata["kickchannel"] = kickchannel
        # Discord guild (server) information - captured dynamically by bot
        if discordguild := self.config.cparser.value("discord/guild"):
            self.metadata["discordguild"] = discordguild

    def _process_tinytag(self) -> None:
        try:
            tempdata = nowplaying.metadata.tinytag_runner.TinyTagRunner(
                imagecache=self.imagecache
            ).process(metadata=copy.copy(self.metadata))
            self.metadata = recognition_replacement(
                config=self.config, metadata=self.metadata, addmeta=tempdata
            )
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("TinyTag crashed: %s", err)

    def _process_image2png(self) -> None:
        # always convert to png

        if (
            not self.metadata
            or "coverimageraw" not in self.metadata
            or not self.metadata["coverimageraw"]
        ):
            return

        self.metadata["coverimageraw"] = nowplaying.utils.image2png(self.metadata["coverimageraw"])
        self.metadata["coverimagetype"] = "png"
        self.metadata["coverurl"] = "cover.png"

    async def _musicbrainz(self) -> None:
        if not self.metadata:
            return None

        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            logging.debug("Skipping MusicBrainz lookup - disabled")
            return

        # Check if we already have key MusicBrainz data to avoid unnecessary lookups
        if (
            self.metadata.get("musicbrainzartistid")
            and self.metadata.get("musicbrainzrecordingid")
            and self.metadata.get("isrc")
        ):
            logging.debug("Skipping MusicBrainz lookup - already have key identifiers")
            return

        try:
            musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(
                config=self.config, test_mode=self.test_mode
            )
            addmeta = await musicbrainz.recognize(copy.copy(self.metadata))
            self.metadata = recognition_replacement(
                config=self.config, metadata=self.metadata, addmeta=addmeta
            )

        except Exception as error:  # pylint: disable=broad-except
            logging.error("MusicBrainz recognition failed: %s", error)

    async def _mb_fallback(self) -> None:
        """at least see if album can be found"""

        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            logging.debug("Skipping MusicBrainz fallback lookup - disabled")
            return

        addmeta = {}
        # user does not want fallback support
        if not self.metadata or not self.config.cparser.value("musicbrainz/fallback", type=bool):
            return

        # either missing key data or has already been processed
        if (
            self.metadata.get("isrc")
            or self.metadata.get("musicbrainzartistid")
            or self.metadata.get("musicbrainzrecordingid")
            or not self.metadata.get("artist")
            or not self.metadata.get("title")
        ):
            return

        logging.debug("Attempting musicbrainz fallback")

        musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(
            config=self.config, test_mode=self.test_mode
        )
        addmeta = await musicbrainz.lastditcheffort(copy.copy(self.metadata))
        self.metadata = recognition_replacement(
            config=self.config, metadata=self.metadata, addmeta=addmeta
        )

        # handle the youtube download case special
        if (not addmeta or not addmeta.get("album")) and " - " in self.metadata["title"]:
            if comments := self.metadata.get("comments"):
                if YOUTUBE_MATCH_RE.match(comments):
                    await self._mb_youtube_fallback(musicbrainz)

    async def _mb_youtube_fallback(
        self, musicbrainz: "nowplaying.musicbrainz.MusicBrainzHelper"
    ) -> None:
        if not self.metadata:
            return

        if not self.config.cparser.value("musicbrainz/enabled", type=bool):
            logging.debug("Skipping youtube fallback lookup - disabled")
            return None

        addmeta2 = copy.deepcopy(self.metadata)
        artist, title = self.metadata["title"].split(" - ")
        addmeta2["artist"] = artist.strip()

        # Strip common video suffixes from title before MusicBrainz lookup
        clean_title = title.strip()
        if self.config.cparser.value("settings/stripextras", type=bool):
            clean_title = nowplaying.utils.filters.titlestripper(
                config=self.config, title=clean_title
            )
        addmeta2["title"] = clean_title

        logging.debug("Youtube video fallback with %s and %s", artist, clean_title)

        try:
            if addmeta := await musicbrainz.lastditcheffort(addmeta2):
                self.metadata["artist"] = artist
                self.metadata["title"] = clean_title  # Use the cleaned title
                self.metadata = recognition_replacement(
                    config=self.config, metadata=self.metadata, addmeta=addmeta
                )
        except Exception:  # pylint: disable=broad-except
            logging.error("Ignoring fallback failure.")

    async def _process_plugins(self, skipplugins: bool) -> None:
        await self._musicbrainz()

        for plugin in self.config.plugins["recognition"]:
            metalist = self.config.pluginobjs["recognition"][plugin].providerinfo()
            provider = any(meta not in self.metadata for meta in metalist)
            if provider:
                try:
                    if addmeta := await self.config.pluginobjs["recognition"][plugin].recognize(
                        metadata=self.metadata
                    ):
                        self.metadata = recognition_replacement(
                            config=self.config, metadata=self.metadata, addmeta=addmeta
                        )
                except Exception as error:  # pylint: disable=broad-except
                    logging.error("%s threw exception %s", plugin, error, exc_info=True)

        await self._mb_fallback()

        if self.metadata and self.metadata.get("artist"):
            self.metadata["imagecacheartist"] = nowplaying.utils.normalize_text(
                self.metadata["artist"]
            )

        if skipplugins:
            return

        if self.config.cparser.value("artistextras/enabled", type=bool):
            await self._artist_extras()

    async def _select_bio_artist(self) -> tuple[str | None, str | None]:
        """Return (artist_name, mbid) for the first artist whose bio has not yet been shown.

        Returns (None, None) when all artists in the track have already had their bio shown
        this session — the caller should suppress bio output in that case.
        """
        if not self._biohistory:
            return (self.metadata.get("artist"), None)

        artist_str = self.metadata.get("artist")
        if not artist_str:
            return (None, None)

        artists = nowplaying.utils.artists.split_artist_string(artist_str)
        mbids = self.metadata.get("musicbrainzartistid") or []
        if isinstance(mbids, str):
            mbids = [mbids]

        track = (self.metadata.get("artist") or "", self.metadata.get("title") or "")

        for i, artist in enumerate(artists):
            mbid = mbids[i] if i < len(mbids) else None
            if not await self._biohistory.has_been_shown(artist, mbid, track):
                return (artist, mbid)

        # Check extra MBIDs beyond the count of named artists (e.g. featured artist MBIDs)
        for extra_mbid in mbids[len(artists) :]:
            if not await self._biohistory.has_been_shown(extra_mbid, extra_mbid, track):
                return (None, extra_mbid)

        return (None, None)

    async def _bio_dedup_setup(
        self,
    ) -> tuple[str | None, str | None, bool, str | None, list[str] | str | None]:
        """Determine which artist to fetch bio for and temporarily swap metadata if needed.

        Returns (bio_artist, bio_mbid, suppress_bio, original_artist, original_mbids).
        When suppress_bio is True, all artists in the track have already had bios shown
        this session — plugins still run (for images) but bio fields are stripped afterward.
        """
        original_artist: str | None = self.metadata.get("artist")
        original_mbids: list[str] | str | None = self.metadata.get("musicbrainzartistid")

        if not self._biohistory:
            return (original_artist, None, False, original_artist, original_mbids)

        # Nothing to track against — let bio through without dedup
        if not original_artist and not original_mbids:
            logging.debug("Bio dedup: no artist or MBID to track, passing through")
            return (original_artist, None, False, original_artist, original_mbids)

        bio_artist, bio_mbid = await self._select_bio_artist()
        if bio_artist is None:
            if bio_mbid is None:
                logging.debug(
                    "Bio dedup: suppressing bio for %s (all artists seen)", original_artist
                )
                return (bio_artist, bio_mbid, True, original_artist, original_mbids)
            # bio_mbid is set but no artist name = extra MBID (featured artist) mode
            logging.debug(
                "Bio dedup: using extra MBID %s for %s (featured artist)",
                bio_mbid,
                original_artist,
            )
            self.metadata["artist"] = ""
            self.metadata["musicbrainzartistid"] = [bio_mbid]
            return (bio_artist, bio_mbid, False, original_artist, original_mbids)

        if bio_artist != original_artist:
            logging.debug(
                "Bio dedup: using substitute artist %s for %s", bio_artist, original_artist
            )
            self.metadata["artist"] = bio_artist
            if bio_mbid:
                self.metadata["musicbrainzartistid"] = [bio_mbid]
            else:
                self.metadata.pop("musicbrainzartistid", None)

        return (bio_artist, bio_mbid, False, original_artist, original_mbids)

    async def _bio_dedup_restore(  # pylint: disable=too-many-arguments
        self,
        bio_artist: str | None,
        bio_mbid: str | None,
        suppress_bio: bool,
        original_artist: str | None,
        original_mbids: list[str] | str | None,
    ) -> None:
        """Record bio as shown and restore original artist metadata fields."""
        if not self._biohistory:
            return

        track = (original_artist or "", self.metadata.get("title") or "")
        if not suppress_bio and bio_artist:
            bio_text = self.metadata.get("artistlongbio")
            await self._biohistory.record_shown(bio_artist, bio_mbid, bio_text, track)
            logging.debug("Bio dedup: recorded bio shown for %s", bio_artist)
        elif not suppress_bio and bio_mbid:
            # Extra MBID (featured artist) mode: record by MBID as identifier
            bio_text = self.metadata.get("artistlongbio")
            await self._biohistory.record_shown(bio_mbid, bio_mbid, bio_text, track)
            logging.debug("Bio dedup: recorded extra MBID bio shown for %s", bio_mbid)

        if original_artist != self.metadata.get("artist"):
            if original_artist is not None:
                self.metadata["artist"] = original_artist
            if original_mbids is not None:
                self.metadata["musicbrainzartistid"] = original_mbids
            else:
                self.metadata.pop("musicbrainzartistid", None)

        if suppress_bio:
            self.metadata.pop("artistlongbio", None)
            self.metadata.pop("artistshortbio", None)

    async def _artist_extras(self) -> None:  # pylint: disable=too-many-branches,too-many-nested-blocks
        """Efficiently process artist extras plugins using native async calls"""
        bio_state = await self._bio_dedup_setup()
        tasks: list[tuple[str, asyncio.Task]] = []
        try:
            # Calculate dynamic timeout based on delay setting
            base_delay = self.config.cparser.value("settings/delay", type=float, defaultValue=10.0)
            timeout = min(max(base_delay * 1.2, 5.0), 15.0)  # 5-15 second range

            # Start all plugin tasks concurrently using native async methods
            for _, plugins in self.extraslist.items():
                for plugin in plugins:
                    try:
                        plugin_obj = self.config.pluginobjs["artistextras"][plugin]
                        task = asyncio.create_task(
                            plugin_obj.download_async(self.metadata, self.imagecache)
                        )
                        tasks.append((plugin, task))
                        logging.debug("Started %s plugin task", plugin)
                    except Exception as error:  # pylint: disable=broad-except
                        logging.error(
                            "%s threw exception during setup: %s", plugin, error, exc_info=True
                        )

            if not tasks:
                return

            # Wait for tasks with dynamic timeout and early completion detection
            try:
                done, pending = await asyncio.wait(
                    [task for _, task in tasks],
                    timeout=timeout,
                    return_when=asyncio.ALL_COMPLETED,
                )

                for plugin, task in tasks:
                    if task in done:
                        try:
                            addmeta = await task
                        except Exception as error:  # pylint: disable=broad-except
                            logging.error("%s plugin failed: %s", plugin, error, exc_info=True)
                            continue
                        if addmeta:
                            self.metadata = recognition_replacement(
                                config=self.config, metadata=self.metadata, addmeta=addmeta
                            )
                            logging.debug("%s plugin completed successfully", plugin)
                        else:
                            logging.debug("%s plugin returned no data", plugin)
                    elif task in pending:
                        logging.debug("%s plugin timed out after %ss", plugin, timeout)
                        task.cancel()

                if pending:
                    try:
                        await asyncio.gather(*pending, return_exceptions=True)
                    except Exception as cleanup_error:  # pylint: disable=broad-except
                        logging.error("Exception during task cleanup: %s", cleanup_error)

            except Exception as error:  # pylint: disable=broad-except
                logging.error("Artist extras processing failed: %s", error)
                remaining_tasks = [task for _, task in tasks if not task.done()]
                for task in remaining_tasks:
                    task.cancel()
                if remaining_tasks:
                    try:
                        await asyncio.gather(*remaining_tasks, return_exceptions=True)
                    except Exception as cleanup_error:  # pylint: disable=broad-except
                        logging.error(
                            "Exception during task cleanup in exception handler: %s",
                            cleanup_error,
                        )
        finally:
            await self._bio_dedup_restore(*bio_state)

    def _generate_short_bio(self) -> None:
        if not self.metadata:
            return

        message = self.metadata["artistlongbio"]
        message = message.replace("\n", " ")
        message = message.replace("\r", " ")
        message = str(message).strip()
        text = textwrap.TextWrapper(width=450).wrap(message)[0]
        tokens = nowplaying.utils.tokenize_sentences(text)

        nonotes = [sent for sent in tokens if not NOTE_RE.match(sent)]
        tokens = nonotes

        if tokens[-1][-1] in string.punctuation and tokens[-1][-1] not in [":", ",", ";", "-"]:
            self.metadata["artistshortbio"] = " ".join(tokens)
        else:
            self.metadata["artistshortbio"] = " ".join(tokens[:-1])


def recognition_replacement(
    config: "nowplaying.config.ConfigFile | None" = None,
    metadata: TrackMetadata | None = None,
    addmeta: TrackMetadata | None = None,
) -> TrackMetadata:
    """handle any replacements"""
    # if there is nothing in addmeta, then just bail early
    if not addmeta:
        return metadata or {}

    if not metadata:
        metadata = {}

    for meta in addmeta:
        if meta in ["artist", "title", "artistwebsites"]:
            if (
                config.cparser.value(f"recognition/replace{meta}", type=bool)
                and addmeta.get(meta)
                or not metadata.get(meta)
                and addmeta.get(meta)
            ):
                metadata[meta] = addmeta[meta]
        elif not metadata.get(meta) and addmeta.get(meta):
            metadata[meta] = addmeta[meta]
    return metadata


def main() -> None:
    """entry point as a standalone app"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m nowplaying.metadata <filename>")
        print("  python -m nowplaying.metadata <artist> <title>")
        sys.exit(1)

    logging.basicConfig(
        format="%(asctime)s %(process)d %(threadName)s %(module)s:%(funcName)s:%(lineno)d "
        + "%(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        level=logging.DEBUG,
    )
    logging.captureWarnings(True)

    # Bootstrap Qt for proper configuration
    nowplaying.bootstrap.set_qt_names()

    bundledir = os.path.abspath(os.path.dirname(__file__))
    config = nowplaying.config.ConfigFile(bundledir=bundledir)

    testmeta: TrackMetadata = {}
    # Handle either filename or artist + title
    if len(sys.argv) == 2:
        # Single argument - treat as filename
        testmeta = {"filename": sys.argv[1]}
    elif len(sys.argv) == 3:
        # Two arguments - treat as artist and title
        testmeta = {"artist": sys.argv[1], "title": sys.argv[2]}
    else:
        print("Error: Too many arguments")
        print("Usage:")
        print("  python -m nowplaying.metadata <filename>")
        print("  python -m nowplaying.metadata <artist> <title>")
        sys.exit(1)

    myclass = MetadataProcessors(config=config)
    testdata = asyncio.run(myclass.getmoremetadata(metadata=testmeta))
    if "coverimageraw" in testdata:
        print("got an image")
        del testdata["coverimageraw"]
    print(testdata)


if __name__ == "__main__":
    main()
