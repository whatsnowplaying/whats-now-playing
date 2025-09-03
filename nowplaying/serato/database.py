#!/usr/bin/env python3
"""
Serato Database Reader

Handles reading and parsing Serato _database_V2 files which contain
comprehensive track metadata and library information.
"""

import logging
import pathlib
import struct
import typing as t

from .base import SeratoBaseReader, SeratoRuleMatchingMixin


class SeratoDatabaseV2Reader(SeratoRuleMatchingMixin, SeratoBaseReader):
    """read a Serato database V2 file containing all indexed tracks"""

    def __init__(self, serato_lib_path: str | pathlib.Path) -> None:
        db_file = pathlib.Path(serato_lib_path).joinpath("database V2")
        super().__init__(db_file)
        self.serato_lib_path: pathlib.Path = pathlib.Path(serato_lib_path)
        self.database: list[tuple[str, t.Any]] | None = None
        self.tracks: list[dict[str, t.Any]] = []

    async def loaddatabase(self) -> None:
        """load/overwrite current database"""
        if not self.filepath.exists():
            logging.error("Serato database V2 not found at %s", self.filepath)
            return

        await self.loadfile()
        self.database = self.data
        self._parse_tracks()

    def _parse_tracks(self) -> None:
        """Parse all tracks from database V2 format"""
        if not self.database:
            return

        self.tracks = []
        track_count = 0
        parsed_count = 0
        for tag, value in self.database:
            if tag == "otrk":  # Track entry
                track_count += 1
                if track := self._parse_track_data(value):
                    parsed_count += 1
                    self.tracks.append(track)

        logging.debug(
            "Serato database parsing: found %d otrk entries, successfully parsed %d tracks",
            track_count,
            parsed_count,
        )

    @staticmethod
    def _parse_track_data(track_data: list[tuple[str, t.Any]]) -> dict[str, t.Any] | None:
        """Parse individual track metadata from otrk section"""
        track = {}

        # Mapping of Serato tag codes to field processors
        tag_processors = {
            "pfil": lambda v: {"filepath": v, "filename": pathlib.Path(v).name if v else None},
            "tsng": lambda v: {"title": v},
            "tart": lambda v: {"artist": v},
            "talb": lambda v: {"album": v},
            "tgen": lambda v: {"genre": v},
            "tcom": lambda v: {"composer": v},
            "tbpm": lambda v: {"bpm": v},
            "tkey": lambda v: {"key": v},
            "ttim": lambda v: {"length": struct.unpack(">I", v)[0] if len(v) >= 4 else None},
            "tadded": lambda v: {"added": struct.unpack(">I", v)[0] if len(v) >= 4 else None},
            "tgrp": lambda v: {"grouping": v},
            "tlbl": lambda v: {"label": v},
            "trmx": lambda v: {"remixer": v},
            "tyea": lambda v: {"year": struct.unpack(">I", v)[0] if len(v) >= 4 else None},
            "tcmt": lambda v: {"comment": v},
        }

        for tag, value in track_data:
            if tag == "ttyp":  # Track type (usually ignored)
                continue

            if processor := tag_processors.get(tag):
                track |= processor(value)

        # Only return tracks with essential metadata
        return track if track.get("filepath") else None

    def apply_smart_crate_rules(self, rules: list[dict[str, t.Any]]) -> list[str]:
        """Apply smart crate rules to database tracks and return file paths"""
        if not rules:
            logging.debug("No rules provided to apply_smart_crate_rules")
            return []

        logging.debug("Applying %d rules to %d tracks", len(rules), len(self.tracks))
        matching_tracks = [
            track["filepath"]
            for track in self.tracks
            if self._track_matches_rules(track, rules) and track.get("filepath")
        ]
        logging.debug("Rules matched %d tracks", len(matching_tracks))
        return matching_tracks

    def _track_matches_rules(self, track: dict[str, t.Any], rules: list[dict[str, t.Any]]) -> bool:
        """Check if a track matches all smart crate rules (AND logic)"""
        return all(self._rule_matches_track(rule, track) for rule in rules)

    def _rule_matches_track(self, rule: dict[str, t.Any], track: dict[str, t.Any]) -> bool:
        """Check if a single rule matches the track"""
        field = rule["field"]
        operator = rule["operator"]
        value = rule["value"]
        field_type = rule["field_type"]

        # Get track field value
        track_value = track.get(field)
        if track_value is None:
            return False

        # Apply operator based on field type
        if field_type == "text":
            return self._apply_text_operator(
                operator, str(track_value).lower(), str(value).lower()
            )
        if field_type == "numeric":
            return self._apply_numeric_operator(operator, track_value, value)
        if field_type == "date":
            return self._apply_date_operator(operator, track_value, value)
        return True
