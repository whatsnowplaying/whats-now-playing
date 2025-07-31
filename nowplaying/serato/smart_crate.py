#!/usr/bin/env python3
"""
Serato Smart Crate Reader

Original SeratoSmartCrateReader class extracted from the monolithic serato.py file.
This preserves all the original functionality and complexity that was
developed and tested over time.
"""

import logging
import pathlib
import struct
import typing as t

from .base import SeratoBaseReader, SeratoRuleMatchingMixin
from .database import SeratoDatabaseV2Reader


class SeratoSmartCrateReader(SeratoRuleMatchingMixin, SeratoBaseReader):
    """read a Serato smart crate (.scrate) file and execute its rules"""

    def __init__(self, filename: str | pathlib.Path, serato_lib_path: str | pathlib.Path) -> None:
        super().__init__(filename)
        # Add smart crate specific decoders
        self.decode_func_full.update(
            {
                "trft": self._decode_struct,  # Filter conditions
                "osrt": self._decode_struct,  # Sort conditions
            }
        )

        self.serato_lib_path: pathlib.Path = pathlib.Path(serato_lib_path)
        self.smart_crate: list[tuple[str, t.Any]] | None = None
        self.rules: list[dict[str, t.Any]] = []

    async def loadsmartcrate(self) -> None:
        """load/overwrite current smart crate"""
        await self.loadfile()
        self.smart_crate = self.data
        self._parse_rules()

    def _parse_rules(self) -> None:
        """Parse smart crate rules from loaded data"""
        if not self.smart_crate:
            return

        self.rules = []
        for tag, value in self.smart_crate:
            if tag == "trft":  # Filter condition
                if rule := self._parse_filter_condition(value):
                    self.rules.append(rule)

    def _parse_filter_condition(
        self, condition_data: list[tuple[str, t.Any]]
    ) -> dict[str, t.Any] | None:
        """Parse individual filter condition from trft section"""
        rule = {"field": None, "operator": None, "value": None, "field_type": None}

        for tag, value in condition_data:
            if tag == "tvcn":  # Field name (artist, song, etc.)
                field_name = value.lower()
                rule["field"] = field_name
                rule["field_type"] = self._get_field_type(field_name)
            elif tag == "tvcw":  # Search value
                rule["value"] = value
            elif tag == "urkt":  # Operator type (contains, equals, etc.)
                operator_code = struct.unpack(">I", value)[0] if len(value) >= 4 else 0
                rule["operator"] = self._get_operator_name(operator_code)

        return rule if rule["field"] and rule["value"] and rule["operator"] else None

    async def getfilenames(self) -> list[str] | None:
        """Get filenames by executing smart crate rules against Serato database"""
        if not self.smart_crate:
            logging.error("smart crate has not been loaded")
            return None

        # Try to use Serato database V2 for accurate filtering
        try:
            db_reader = SeratoDatabaseV2Reader(self.serato_lib_path)
            await db_reader.loaddatabase()

            if db_reader.tracks:
                # Use database for accurate smart crate filtering
                return db_reader.apply_smart_crate_rules(self.rules)
            logging.warning(
                "No tracks loaded from Serato database, falling back to directory scan"
            )
            return await self._scan_music_directory()

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.warning(
                "Failed to load Serato database V2: %s, falling back to directory scan", err
            )
            return await self._scan_music_directory()

    async def _scan_music_directory(self) -> list[str]:
        """Scan music directory for files matching smart crate rules"""
        if not self.rules:
            return []

        # Get music directory (parent of _Serato_ folder)
        music_dir = self.serato_lib_path.parent

        # Get all audio files first
        all_files = []
        for ext in ["*.mp3", "*.m4a", "*.flac", "*.wav", "*.aiff"]:
            all_files.extend(music_dir.rglob(ext))

        # Filter files based on rules
        matching_files = []
        matching_files.extend(
            str(file_path) for file_path in all_files if self._file_matches_rules(file_path)
        )
        return matching_files

    def _file_matches_rules(self, file_path: pathlib.Path) -> bool:
        """Check if a file path matches all smart crate rules"""
        # For directory-based matching, we primarily match on filename/path content
        file_str = str(file_path).lower()
        file_name = file_path.stem.lower()

        return all(self._rule_matches_file(rule, file_str, file_name) for rule in self.rules)

    def _rule_matches_file(self, rule: dict[str, t.Any], file_str: str, file_name: str) -> bool:
        """Check if a single rule matches the file"""
        field = rule["field"]
        operator = rule["operator"]
        value = rule["value"].lower() if isinstance(rule["value"], str) else rule["value"]
        field_type = rule["field_type"]

        # Get field content to check against
        if field in ["artist", "song", "title", "album", "genre"]:
            # For directory-based matching, search in the full path
            search_content = file_str
        elif field == "filename":
            search_content = file_name
        else:
            # For fields we can't extract from filename, skip the rule
            return True

        # Apply operator based on field type
        if field_type == "text":
            return self._apply_text_operator(operator, search_content, value)
        # For numeric fields, we can't easily extract from filenames
        # so we'll be permissive and return True
        return True
