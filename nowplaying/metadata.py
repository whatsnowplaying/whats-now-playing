#!/usr/bin/env python3
"""pull out metadata"""

import asyncio
import base64
import binascii
import copy
import json
import logging
import os
import pathlib
import re
import string
import sys
import textwrap
from typing import TYPE_CHECKING

import tinytag
import url_normalize
import puremagic

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.hostmeta
import nowplaying.musicbrainz
import nowplaying.tinytag_fixes
import nowplaying.utils
from nowplaying.types import TrackMetadata

# File extension constants for video/audio detection
AUDIO_EXTENSIONS = frozenset([".mp3", ".flac", ".m4a", ".f4a", ".aac", ".ogg", ".wav", ".wma"])
VIDEO_EXTENSIONS = frozenset(
    [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".vob", ".ogv"]
)
AUDIO_CONTAINER_EXCLUSIONS = frozenset([".m4a", ".f4a"])

if TYPE_CHECKING:
    import nowplaying.imagecache

# Apply tinytag patches - will be called after logging is set up

NOTE_RE = re.compile("N(?i:ote):")
YOUTUBE_MATCH_RE = re.compile("^https?://[www.]*youtube.com/watch.v=")


def _date_calc(datedata: dict[str, str]) -> str | None:
    if (
        datedata.get("originalyear")
        and datedata.get("date")
        and datedata["originalyear"] in datedata["date"]
    ):
        del datedata["originalyear"]

    if (
        datedata.get("originalyear")
        and datedata.get("year")
        and datedata["originalyear"] in datedata["year"]
    ):
        del datedata["originalyear"]

    datelist = list(datedata.values())
    gooddate = None
    datelist = sorted(datelist)
    if len(datelist) > 2:
        if datelist[0] in datelist[1]:
            gooddate = datelist[1]
    elif datelist:
        gooddate = datelist[0]

    if gooddate:
        # logging.debug("realdate: %s rest: %s", gooddate, gooddate)
        return gooddate
    return None


class MetadataProcessors:  # pylint: disable=too-few-public-methods
    """Run through a bunch of different metadata processors"""

    def __init__(self, config: nowplaying.config.ConfigFile | None = None):
        self.metadata: TrackMetadata = {}
        self.imagecache: "nowplaying.imagecache.ImageCache | None" = None
        if config:
            self.config: nowplaying.config.ConfigFile = config
        else:
            self.config = nowplaying.config.ConfigFile()

        self.extraslist: dict[int, list[str]] = self._sortextras()
        # logging.debug("%s %s", type(self.extraslist), self.extraslist)

    def _sortextras(self) -> dict[int, list[str]]:
        extras = {}
        for plugin in self.config.plugins["artistextras"]:
            priority = self.config.pluginobjs["artistextras"][plugin].priority
            if not extras.get(priority):
                extras[priority] = []
            extras[priority].append(plugin)
        return dict(reversed(list(extras.items())))

    async def getmoremetadata(
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

        if self.config.cparser.value("settings/stripextras", type=bool) and self.metadata.get(
            "title"
        ):
            self.metadata["title"] = nowplaying.utils.titlestripper_advanced(
                title=self.metadata["title"], title_regex_list=self.config.getregexlist()
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
            tempdata = TinyTagRunner(imagecache=self.imagecache).process(
                metadata=copy.copy(self.metadata)
            )
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

        # Check if we already have key MusicBrainz data to avoid unnecessary lookups
        if (
            self.metadata.get("musicbrainzartistid")
            and self.metadata.get("musicbrainzrecordingid")
            and self.metadata.get("isrc")
        ):
            logging.debug("Skipping MusicBrainz lookup - already have key identifiers")
            return

        try:
            musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(config=self.config)
            addmeta = await musicbrainz.recognize(copy.copy(self.metadata))
            self.metadata = recognition_replacement(
                config=self.config, metadata=self.metadata, addmeta=addmeta
            )
        except Exception as error:  # pylint: disable=broad-except
            logging.error("MusicBrainz recognition failed: %s", error)

    async def _mb_fallback(self) -> None:
        """at least see if album can be found"""

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

        musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(config=self.config)
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
        addmeta2 = copy.deepcopy(self.metadata)
        artist, title = self.metadata["title"].split(" - ")
        addmeta2["artist"] = artist.strip()
        addmeta2["title"] = title.strip()

        logging.debug("Youtube video fallback with %s and %s", artist, title)

        try:
            if addmeta := await musicbrainz.lastditcheffort(addmeta2):
                self.metadata["artist"] = artist
                self.metadata["title"] = title
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

    async def _artist_extras(self) -> None:  # pylint: disable=too-many-branches
        """Efficiently process artist extras plugins using native async calls"""
        tasks: list[tuple[str, asyncio.Task]] = []

        # Calculate dynamic timeout based on delay setting
        # With apicache integration, we need more time for cache misses but still be responsive
        base_delay = self.config.cparser.value("settings/delay", type=float, defaultValue=10.0)
        timeout = min(max(base_delay * 1.2, 5.0), 15.0)  # 5-15 second range

        # Start all plugin tasks concurrently using native async methods
        for _, plugins in self.extraslist.items():
            for plugin in plugins:
                try:
                    plugin_obj = self.config.pluginobjs["artistextras"][plugin]
                    # All artist extras plugins now have async support
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
            # Use asyncio.wait with timeout instead of sleep + cancel
            done, pending = await asyncio.wait(
                [task for _, task in tasks], timeout=timeout, return_when=asyncio.ALL_COMPLETED
            )

            # Process completed tasks immediately
            for plugin, task in tasks:
                if task in done:
                    try:
                        addmeta = await task
                        if addmeta:
                            self.metadata = recognition_replacement(
                                config=self.config, metadata=self.metadata, addmeta=addmeta
                            )
                            logging.debug("%s plugin completed successfully", plugin)
                        else:
                            logging.debug("%s plugin returned no data", plugin)
                    except Exception as error:  # pylint: disable=broad-except
                        logging.error("%s plugin failed: %s", plugin, error, exc_info=True)

                elif task in pending:
                    logging.debug("%s plugin timed out after %ss", plugin, timeout)
                    task.cancel()

            # Wait for cancelled tasks to clean up properly
            if pending:
                try:
                    await asyncio.gather(*pending, return_exceptions=True)
                except Exception as cleanup_error:  # pylint: disable=broad-except
                    logging.error("Exception during task cleanup: %s", cleanup_error)

        except Exception as error:  # pylint: disable=broad-except
            logging.error("Artist extras processing failed: %s", error)
            # Cancel any remaining tasks and wait for cleanup
            remaining_tasks = [task for _, task in tasks if not task.done()]
            for task in remaining_tasks:
                task.cancel()
            if remaining_tasks:
                try:
                    await asyncio.gather(*remaining_tasks, return_exceptions=True)
                except Exception as cleanup_error:  # pylint: disable=broad-except
                    logging.error(
                        "Exception during task cleanup in exception handler: %s", cleanup_error
                    )

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


class TinyTagRunner:  # pylint: disable=too-few-public-methods
    """tinytag manager"""

    _patches_applied: bool = False

    def __init__(self, imagecache: "nowplaying.imagecache.ImageCache | None" = None):
        self.imagecache: "nowplaying.imagecache.ImageCache | None" = imagecache
        self.metadata: TrackMetadata = {}
        self.datedata: dict[str, str] = {}

        # Apply tinytag patches once after logging is set up
        if not TinyTagRunner._patches_applied:
            _ = nowplaying.tinytag_fixes.apply_tinytag_patches()
            TinyTagRunner._patches_applied = True

    @staticmethod
    def tt_date_calc(tag: object) -> str | None:
        """deal with tinytag dates"""
        datedata = {}
        other = getattr(tag, "other", {})
        for datetype in ["originaldate", "tdor", "originalyear", "tory", "date", "year"]:
            if hasattr(tag, datetype) and getattr(tag, datetype):
                datedata[datetype] = getattr(tag, datetype)
            elif other.get(datetype):
                # Convert lists to strings for date fields
                value = other[datetype]
                if isinstance(value, list) and value:
                    datedata[datetype] = str(value[0])
                else:
                    datedata[datetype] = value
        return _date_calc(datedata)

    def process(self, metadata: TrackMetadata) -> TrackMetadata:  # pylint: disable=too-many-branches
        """given a chunk of metadata, try to fill in more"""
        self.metadata = metadata

        if not metadata or not metadata.get("filename"):
            return metadata

        # Create pathlib Path object for tinytag processing
        try:
            file_path = pathlib.Path(self.metadata["filename"])
        except (ValueError, OSError) as error:
            logging.debug("Cannot create Path object for %s: %s", self.metadata["filename"], error)
            return metadata

        # Detect if file contains video content
        self.metadata["has_video"] = self._detect_video_content(file_path)

        try:
            # Pass pathlib Path directly to tinytag - it will handle the path conversion
            tag = tinytag.TinyTag.get(file_path, image=True)
        except tinytag.TinyTagException as error:
            logging.error("tinytag could not process %s: %s", file_path, error)
            return metadata
        except (FileNotFoundError, OSError, PermissionError) as error:
            logging.debug("Cannot access file for tinytag processing %s: %s", file_path, error)
            return metadata

        if tag:
            self._got_tag(tag)

        return self.metadata

    def _ufid(self, extra: dict[str, object]) -> None:
        if ufid := extra.get("ufid"):
            # Handle both string and list cases from tinytag 2.1.1
            ufid_str = ufid[0] if isinstance(ufid, list) and ufid else ufid
            if isinstance(ufid_str, bytes):
                ufid_str = ufid_str.decode("utf-8", errors="replace")
            if isinstance(ufid_str, str) and "\x00" in ufid_str:
                key, value = ufid_str.split("\x00")
                if key == "http://musicbrainz.org":
                    self.metadata["musicbrainzrecordingid"] = value

    def _split_delimited_string(self, value: str) -> list[str]:  # pylint: disable=no-self-use
        """Split a string on common delimiters."""
        if "/" in value:
            return value.split("/")
        if ";" in value:
            return value.split(";")
        return [value]

    def _process_list_field(self, value, newkey: str) -> None:
        """Process fields that should be stored as lists."""
        if isinstance(value, list):
            # Handle lists that might contain strings needing splitting
            result_list = []
            for item in value:
                item_str = str(item)
                result_list.extend(self._split_delimited_string(item_str))
            self.metadata[newkey] = result_list
        elif isinstance(value, str):
            self.metadata[newkey] = self._split_delimited_string(value)
        else:
            self.metadata[newkey] = [str(value)]

    def _process_single_field(self, value, newkey: str) -> None:
        """Process fields that should be stored as single values."""
        if isinstance(value, list) and value:
            self.metadata[newkey] = str(value[0])
        else:
            self.metadata[newkey] = value

    @staticmethod
    def _detect_video_content(file_path: pathlib.Path) -> bool:
        """Detect if file contains video content using puremagic and file extension analysis.

        Args:
            file_path: Path to the file to analyze

        Returns:
            True if file contains video content, False if audio-only or detection fails
        """
        try:
            file_types = puremagic.magic_file(str(file_path))
            # More precise video detection - prioritize actual file extension over detected types
            file_extension = file_path.suffix.lower()

            # If file has known audio-only extension, it's definitely not video
            if file_extension in AUDIO_EXTENSIONS:
                has_video = False
            # If file has known video extension, check if it's actually video content
            elif file_extension in VIDEO_EXTENSIONS:
                # For ambiguous containers like MP4, check the detected types
                has_video = False
                has_audio_indicator = False

                for file_type in file_types:
                    file_type_str = str(file_type).lower()
                    # Look for video indicators that aren't specifically audio
                    if (
                        "video" in file_type_str
                        and "audio" not in file_type_str
                        and file_type.extension not in AUDIO_CONTAINER_EXCLUSIONS
                    ):
                        has_video = True
                        break
                    # Check for explicit audio indicators
                    if "audio" in file_type_str:
                        has_audio_indicator = True

                # Default to True for known video extensions if no clear audio indication
                if (
                    not has_video
                    and not has_audio_indicator
                    and file_extension in VIDEO_EXTENSIONS
                ):
                    has_video = True
            else:
                # Unknown extension, use puremagic detection
                has_video = any(
                    "video" in str(file_type).lower() and "audio" not in str(file_type).lower()
                    for file_type in file_types
                )

            logging.debug(
                "Video detection for %s: %s (types: %s)", file_path, has_video, file_types
            )
            return has_video

        except Exception as error:  # pylint: disable=broad-except
            logging.debug("Video detection failed for %s: %s", file_path, error)
            return False  # Default to audio if detection fails

    @staticmethod
    def _decode_musical_key(key_value) -> str | None:
        """Decode musical key field, handling JSON structures from MixedInKey."""
        if not key_value:
            return None

        key_str = str(key_value).strip()

        # Check if it looks like base64 encoded JSON
        try:
            # Try to decode as base64 first
            decoded_bytes = base64.b64decode(key_str)
            decoded_str = decoded_bytes.decode("utf-8")

            # Try to parse as JSON
            key_data = json.loads(decoded_str)
            if isinstance(key_data, dict) and "key" in key_data and key_data["key"] is not None:
                return key_data["key"]
        except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
            pass

        # If not base64/JSON, try direct JSON parsing
        try:
            key_data = json.loads(key_str)
            if isinstance(key_data, dict) and "key" in key_data and key_data["key"] is not None:
                return key_data["key"]
        except (json.JSONDecodeError, TypeError):
            pass

        # If all else fails, return the string as-is
        return key_str

    def _process_extra(self, extra: dict[str, object]) -> None:
        extra_mapping = {
            "acoustid id": "acoustidid",
            "bpm": "bpm",
            "isrc": "isrc",
            "key": "key",
            "composer": "composer",
            "lyricist": "lyricist",
            "musicbrainz album id": "musicbrainzalbumid",
            "musicbrainz artist id": "musicbrainzartistid",
            "musicbrainz_trackid": "musicbrainzrecordingid",
            "musicbrainz track id": "musicbrainzrecordingid",
            "musicbrainz_albumid": "musicbrainzalbumid",
            "musicbrainz_artistid": "musicbrainzartistid",
            "publisher": "publisher",
            "label": "label",
            "website": "artistwebsites",
            "set_subtitle": "discsubtitle",
        }

        list_fields = {"isrc", "musicbrainz_artistid", "musicbrainz artist id", "website"}

        for key, newkey in extra_mapping.items():
            if not extra.get(key) or self.metadata.get(newkey):
                continue

            if key in list_fields:
                self._process_list_field(extra[key], newkey)
            elif key == "key":
                # Special handling for musical key field
                self.metadata[newkey] = self._decode_musical_key(extra[key])
            else:
                self._process_single_field(extra[key], newkey)

    def _got_tag(self, tag: tinytag.TinyTag) -> None:
        if not self.metadata.get("date"):
            if calcdate := self.tt_date_calc(tag):
                self.metadata["date"] = calcdate

        for key in [
            "album",
            "albumartist",
            "artist",
            "bitrate",
            "bpm",
            "comment",
            "comments",
            "composer",
            "disc",
            "disc_total",
            "duration",
            "genre",
            "lang",
            "lyricist",
            "publisher",
            "title",
            "track",
            "track_total",
            "label",
        ]:
            if key not in self.metadata and hasattr(tag, key) and getattr(tag, key) is not None:
                self.metadata[key] = str(getattr(tag, key))

        # Handle the 'key' field separately to decode JSON if needed
        if "key" not in self.metadata and hasattr(tag, "key") and getattr(tag, "key"):
            self.metadata["key"] = self._decode_musical_key(getattr(tag, "key"))

        if self.metadata.get("comment") and not self.metadata.get("comments"):
            self.metadata["comments"] = self.metadata["comment"]
            del self.metadata["comment"]

        if getattr(tag, "other", None):
            other = getattr(tag, "other")

            self._ufid(other)
            self._process_extra(other)

        if getattr(tag, "other", {}).get("url") and not self.metadata.get("artistwebsites"):
            urls = tag.other["url"]
            if isinstance(urls, str) and urls.lower().count("http") == 1:
                self.metadata["artistwebsites"] = [urls]
            else:
                self.metadata["artistwebsites"] = urls

        if isinstance(self.metadata.get("artistwebsites"), str):
            self.metadata["artistwebsites"] = [self.metadata["artistwebsites"]]

        # logging.debug(tag)
        # logging.debug(tag.extra)

        self._images(tag.images)

    def _images(self, images: tinytag.Images) -> None:
        if "coverimageraw" not in self.metadata and images.front_cover:
            self.metadata["coverimageraw"] = images.front_cover.data

        if self.metadata.get("album") and self.metadata.get("artist") and self.imagecache:
            identifier = f"{self.metadata['artist']}_{self.metadata['album']}"

            # Get all images using as_dict() for tinytag 2.1.1 compatibility
            images_dict = images.as_dict()

            # Process all cover images (tinytag 2.1.1 stores multiple covers under 'cover' key)
            all_covers = images_dict.get("cover", [])
            if not all_covers and images_dict.get("front_cover"):
                # Fallback to front_cover if no cover images found
                all_covers = images_dict.get("front_cover", [])

            for index, cover in enumerate(all_covers):
                logging.debug("Placing audiofile_tt%s front cover", index)
                _ = self.imagecache.put_db_cachekey(
                    identifier=identifier,
                    srclocation=f"{identifier}_audiofile_tt{index}",
                    imagetype="front_cover",
                    content=cover.data,
                )


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
            if config.cparser.value(f"recognition/replace{meta}", type=bool) and addmeta.get(meta):
                metadata[meta] = addmeta[meta]
            elif not metadata.get(meta) and addmeta.get(meta):
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
