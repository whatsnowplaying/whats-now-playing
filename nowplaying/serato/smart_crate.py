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
                "rurt": self._noop,  # Rule data - keep as raw bytes for manual parsing
            }
        )

        # Add handlers for null-byte prefixed data (UTF-16 strings in smart crates)
        self.decode_func_first.update(
            {
                "\x00": lambda x: x.decode("utf-16-be", errors="replace").rstrip(
                    "\x00"
                ),  # UTF-16 string, strip null terminator
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
        unsupported_rules = []
        logging.debug("Parsing smart crate data with %d entries", len(self.smart_crate))
        for tag, value in self.smart_crate:
            logging.debug("Processing smart crate tag: %s", tag)
            if tag == "rurt":  # Rule data - contains trft inside
                if rule := self._parse_rule_from_rurt(value):
                    if self._is_rule_supported(rule):
                        self.rules.append(rule)
                    else:
                        unsupported_rules.append(rule)
                        logging.info(
                            "Skipping unsupported smart crate rule: "
                            "%s (field '%s' not available in Serato database)",
                            rule,
                            rule.get("field"),
                        )
            elif tag == "trft":  # Direct filter condition (backup)
                if rule := self._parse_filter_condition(value):
                    if self._is_rule_supported(rule):
                        self.rules.append(rule)
                    else:
                        unsupported_rules.append(rule)
                        logging.info(
                            "Skipping unsupported smart crate rule: "
                            "%s (field '%s' not available in Serato database)",
                            rule,
                            rule.get("field"),
                        )

        logging.debug(
            "Total rules parsed: %d supported, %d unsupported",
            len(self.rules),
            len(unsupported_rules),
        )
        if unsupported_rules:
            supported_fields = list(self._get_supported_fields())
            logging.info(
                "Note: What's Now Playing smart crates support only these fields: %s",
                ", ".join(supported_fields),
            )

    @staticmethod
    def _get_supported_fields() -> set[str]:
        """Get the set of fields supported by What's Now Playing smart crates

        Based on fields available in Serato database V2 format:
        ['filepath', 'filename', 'title', 'artist', 'album', 'bpm', 'composer', 'key']
        """
        return {
            # Text fields that can be searched
            "filename",
            "title",
            "artist",
            "album",
            "composer",
            "key",
            # Numeric fields (though most smart crates use text-style searches)
            "bpm",
            # Note: 'filepath' excluded as it's internal path format
        }

    @staticmethod
    def _is_rule_supported(rule: dict[str, t.Any]) -> bool:
        """Check if a smart crate rule can be supported with available database fields"""
        field = rule.get("field")
        if not field:
            return False

        # Map Serato smart crate field names to our database field names
        field_mapping = {
            "filename": "filename",
            "song": "title",  # Serato calls it 'song', we have 'title'
            "title": "title",
            "artist": "artist",
            "album": "album",
            "bpm": "bpm",
            "composer": "composer",
            "key": "key",
            # Unsupported fields that Serato smart crates might reference:
            # 'year', 'genre', 'length', 'bitrate', 'comment', 'grouping',
            # 'label', 'remixer', 'plays', 'added', 'last_played'
        }

        if mapped_field := field_mapping.get(field):
            # Update the rule to use our database field name
            rule["field"] = mapped_field
            return True

        return False

    def _parse_rule_from_rurt(  # pylint: disable=too-many-branches
        self, rurt_data: bytes
    ) -> dict[str, t.Any] | None:
        """Parse rule from rurt binary data that contains embedded trft"""
        try:
            logging.debug("Parsing rurt data: %d bytes", len(rurt_data))

            # Manual parsing of the rurt structure based on hex analysis
            rule = {"field": None, "operator": None, "value": None, "field_type": None}
            condition_type = None

            i = 0
            while i < len(rurt_data):
                if i + 8 > len(rurt_data):
                    break

                tag = rurt_data[i : i + 4].decode("ascii", errors="replace")
                length = int.from_bytes(rurt_data[i + 4 : i + 8], "big")
                data = rurt_data[i + 8 : i + 8 + length]

                if tag == "trft":
                    # This should be a UTF-16 string describing the condition type
                    condition_type = data.decode("utf-16-be", errors="replace").rstrip("\x00")

                    # Map condition types to field names (but don't set operator yet)
                    if "con_str" in condition_type:
                        rule["field"] = "filename"  # Contains string in filename
                        rule["field_type"] = "text"
                    elif "aft_str" in condition_type:
                        rule["field"] = "year"
                        rule["field_type"] = "numeric"
                    elif "bef_str" in condition_type:
                        rule["field"] = "year"
                        rule["field_type"] = "numeric"

                elif tag == "urkt":
                    # Operator code
                    if len(data) >= 4:
                        operator_code = int.from_bytes(data[:4], "big")
                        # Use existing operator mapping
                        rule["operator"] = self._get_operator_name(operator_code)

                elif tag == "trpt":
                    # Value - could be UTF-16 string or numeric
                    if len(data) > 0:
                        try:
                            # Try as UTF-16 first
                            value = data.decode("utf-16-be", errors="replace").rstrip("\x00")
                            rule["value"] = value
                        except (UnicodeDecodeError, UnicodeError):
                            # If that fails, try as raw bytes
                            rule["value"] = data.decode("ascii", errors="replace")

                i += 8 + length

            # Override operator based on condition type for date/numeric fields
            if rule["field"] == "year" and rule["field_type"] == "numeric":
                if condition_type and "aft_str" in condition_type:
                    rule["operator"] = "greater_than_equal"
                elif condition_type and "bef_str" in condition_type:
                    rule["operator"] = "less_than_equal"

            # Validate rule has all required fields
            if rule["field"] and rule["value"] and rule["operator"]:
                return rule
            missing = [k for k in ("field", "value", "operator") if not rule[k]]
            logging.warning(
                "Ignoring malformed smart crate rule due to missing: %s", ", ".join(missing)
            )
            return None

        except (struct.error, UnicodeDecodeError, IndexError, ValueError) as err:
            logging.warning("Failed to parse rule from rurt data: %s", err)
            logging.debug("Exception details:", exc_info=True)
            return None

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

        if rule["field"] and rule["value"] and rule["operator"]:
            return rule
        missing = [k for k in ("field", "value", "operator") if not rule[k]]
        logging.warning(
            "Ignoring malformed smart crate rule due to missing: %s", ", ".join(missing)
        )
        return None

    async def getfilenames(self) -> list[str] | None:
        """Get filenames by executing smart crate rules against Serato database"""
        if not self.smart_crate:
            logging.error("smart crate has not been loaded")
            return None

        # Use Serato database V2 for accurate filtering
        try:
            db_reader = SeratoDatabaseV2Reader(self.serato_lib_path)
            await db_reader.loaddatabase()

            if db_reader.tracks:
                return db_reader.apply_smart_crate_rules(self.rules)
            logging.error(
                "No tracks loaded from Serato database - Serato DJ installation may be corrupted"
            )
            return None

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error(
                "Failed to load Serato database V2: %s - Serato DJ installation may be corrupted",
                err,
            )
            return None

    async def getfilenames_from_multiple_paths(self, all_libpaths: list[str]) -> list[str] | None:
        """Get filenames by executing smart crate rules against multiple Serato databases"""
        if not self.smart_crate:
            logging.error("smart crate has not been loaded")
            return None

        if not all_libpaths:
            return await self.getfilenames()  # Fallback to single path

        all_matching_files = []

        # Process each database path separately to keep memory usage low
        for libpath in all_libpaths:
            try:
                logging.debug("Checking smart crate rules against database: %s", libpath)
                db_reader = SeratoDatabaseV2Reader(libpath)
                await db_reader.loaddatabase()

                if db_reader.tracks:
                    logging.debug(
                        "Database %s loaded with %d tracks", libpath, len(db_reader.tracks)
                    )
                    if matches := db_reader.apply_smart_crate_rules(self.rules):
                        logging.debug("Found %d matches in database %s", len(matches), libpath)
                        all_matching_files.extend(matches)
                    else:
                        logging.debug("No matches found in database %s", libpath)
                else:
                    logging.warning("No tracks found in database %s", libpath)

                # Clear db_reader to free memory before next iteration
                del db_reader

            except Exception as err:  # pylint: disable=broad-exception-caught
                logging.error("Failed to load Serato database %s: %s", libpath, err)
                continue

        logging.debug(
            "Smart crate found total %d matching files across all databases",
            len(all_matching_files),
        )
        return all_matching_files if all_matching_files else None
