#!/usr/bin/env python3
"""
Rekordbox Type Definitions

This module contains type definitions and data structures used throughout
the Rekordbox plugin implementation.
"""

import pathlib
from dataclasses import dataclass

from nowplaying.types import TrackMetadata


class RekordboxError(Exception):
    """Base exception for Rekordbox-related errors"""


@dataclass
class RekordboxTrack:  # pylint: disable=too-many-instance-attributes
    """Track data structure from Rekordbox database"""

    identifier: str
    title: str | None
    artist: str | None
    album: str | None
    genre: str | None
    bpm: float | None
    duration: int | None
    track_no: int | None
    disc_no: int | None
    year: int | None
    bitrate: int | None
    bit_depth: int | None
    sample_rate: int | None
    file_name: str | None
    folder_path: str | None
    image_path: str | None
    rating: int | None
    play_count: int | None
    comments: str | None
    key: str | None
    label: str | None
    composer: str | None
    lyricist: str | None
    isrc: str | None
    file_size: int | None
    file_type: int | None

    def to_metadata(self) -> TrackMetadata:  # pylint: disable=too-many-branches
        """Convert to standard metadata format"""
        metadata: TrackMetadata = {}

        # Basic track information
        if self.title:
            metadata["title"] = self.title
        if self.artist:
            metadata["artist"] = self.artist
        if self.album:
            metadata["album"] = self.album
        if self.genre:
            metadata["genre"] = self.genre
        if self.year:
            metadata["year"] = str(self.year)
        if self.duration:
            metadata["duration"] = self.duration

        # Track/disc numbers
        if self.track_no:
            metadata["track"] = str(self.track_no)
        if self.disc_no:
            metadata["disc"] = str(self.disc_no)

        # Musical metadata
        if self.bpm:
            metadata["bpm"] = f"{self.bpm:g}"
        if self.key:
            metadata["key"] = self.key
        if self.label:
            metadata["label"] = self.label
        if self.composer:
            metadata["composer"] = self.composer
        if self.lyricist:
            metadata["lyricist"] = self.lyricist

        # Technical metadata
        if self.folder_path and self.file_name:
            metadata["filename"] = str(pathlib.Path(self.folder_path) / self.file_name)
        elif self.file_name:
            metadata["filename"] = self.file_name
        if self.bitrate:
            metadata["bitrate"] = str(self.bitrate)

        # Comments
        if self.comments:
            metadata["comments"] = self.comments

        # ISRC
        if self.isrc:
            metadata["isrc"] = [self.isrc]

        # Cover image
        if self.image_path:
            if cover_data := self._load_cover_image():
                metadata["coverimageraw"] = cover_data

        return metadata

    def _load_cover_image(self) -> bytes | None:
        """Load cover image data if available"""
        if not self.image_path:
            return None
        try:
            with open(self.image_path, "rb") as fhin:
                return fhin.read()
        except (OSError, IOError):
            return None
