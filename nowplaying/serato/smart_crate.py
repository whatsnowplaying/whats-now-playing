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

        if rule["field"] and rule["value"] and rule["operator"]:
            return rule
        else:
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
