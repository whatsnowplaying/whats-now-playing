#!/usr/bin/env python3
"""TinyTag-based audio file metadata extraction"""

import base64
import binascii
import contextlib
import json
import logging
import pathlib
from typing import TYPE_CHECKING

import puremagic

from nowplaying.types import TrackMetadata
from nowplaying.vendor import tinytag  # pylint: disable=no-name-in-module

# File extension constants for video/audio detection
AUDIO_EXTENSIONS = frozenset([".mp3", ".flac", ".m4a", ".f4a", ".aac", ".ogg", ".wav", ".wma"])
VIDEO_EXTENSIONS = frozenset(
    [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".vob", ".ogv"]
)
AUDIO_CONTAINER_EXCLUSIONS = frozenset([".m4a", ".f4a"])

if TYPE_CHECKING:
    import nowplaying.imagecache


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
        return gooddate
    return None


class TinyTagRunner:  # pylint: disable=too-few-public-methods
    """tinytag manager"""

    def __init__(self, imagecache: "nowplaying.imagecache.ImageCache | None" = None):
        self.imagecache: nowplaying.imagecache.ImageCache | None = imagecache
        self.metadata: TrackMetadata = {}
        self.datedata: dict[str, str] = {}

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
        except OSError as error:
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
        # Handle null-byte separation (ID3 multi-value encoding), stripping BOMs
        if "\x00" in value:
            return [part.strip("\ufeff") for part in value.split("\x00") if part.strip("\ufeff")]
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
    def _detect_video_content(file_path: pathlib.Path) -> bool:  # pylint: disable=too-many-return-statements,too-many-branches
        """Detect if file contains video content using puremagic and file extension analysis.

        Args:
            file_path: Path to the file to analyze

        Returns:
            True if file contains video content, False if audio-only or detection fails
        """
        try:
            # Short-circuit: Check file extension first to avoid expensive puremagic call
            file_extension = file_path.suffix.lower()

            # If file has known audio-only extension, it's definitely not video
            if file_extension in AUDIO_EXTENSIONS:
                logging.debug("Video detection for %s: False (audio extension)", file_path)
                return False

            # If file has known video extension, it's likely video
            # (but we'll verify with puremagic for containers)
            if file_extension in VIDEO_EXTENSIONS:
                # For most video extensions, we can confidently assume video content
                # Only use puremagic for ambiguous containers that could be audio-only
                ambiguous_containers = {".mp4", ".m4v", ".mov"}
                if file_extension not in ambiguous_containers:
                    logging.debug("Video detection for %s: True (video extension)", file_path)
                    return True

            # Only call expensive puremagic detection for unknown or ambiguous extensions
            file_types = puremagic.magic_file(str(file_path))

            # Analyze file types to determine video content
            if file_extension in VIDEO_EXTENSIONS:
                # For ambiguous containers, check the detected types
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
                if not has_video and not has_audio_indicator:
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

        except OSError as error:
            # File system errors - file doesn't exist, can't read, permission issues
            logging.warning(
                "Video detection failed due to file system error for %s: %s", file_path, error
            )
            return False  # Default to audio when file can't be accessed
        except ValueError as error:
            # puremagic raises ValueError for empty files or invalid content
            logging.info(
                "Video detection failed due to invalid file content for %s: %s", file_path, error
            )
            return False  # Default to audio for invalid/empty files
        except puremagic.PureError as error:
            # puremagic-specific errors (not regular file, etc.)
            logging.info(
                "Video detection failed due to puremagic error for %s: %s", file_path, error
            )
            return False  # Default to audio for puremagic-specific issues
        except Exception as error:  # pylint: disable=broad-except
            # Unexpected errors that should be investigated
            logging.error(
                "Unexpected error in video detection for %s: %s", file_path, error, exc_info=True
            )
            return False  # Still default to audio, but log as error for investigation

    @staticmethod
    def _decode_musical_key(key_value) -> str | None:
        """Decode musical key field, handling JSON structures from MixedInKey."""
        if not key_value:
            return None

        key_str = str(key_value).strip()

        # Check if it looks like base64 encoded JSON
        with contextlib.suppress(binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
            # Try to decode as base64 first
            decoded_bytes = base64.b64decode(key_str)
            decoded_str = decoded_bytes.decode("utf-8")

            # Try to parse as JSON
            key_data = json.loads(decoded_str)
            if isinstance(key_data, dict) and "key" in key_data and key_data["key"] is not None:
                return key_data["key"]
        # If not base64/JSON, try direct JSON parsing
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            key_data = json.loads(key_str)
            if isinstance(key_data, dict) and "key" in key_data and key_data["key"] is not None:
                return key_data["key"]
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
        if "key" not in self.metadata and hasattr(tag, "key") and tag.key:
            self.metadata["key"] = self._decode_musical_key(tag.key)

        if self.metadata.get("comment") and not self.metadata.get("comments"):
            self.metadata["comments"] = self.metadata["comment"]
            del self.metadata["comment"]

        if getattr(tag, "other", None):
            other = tag.other

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
