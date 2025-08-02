#!/usr/bin/env python3
"""
Serato Base Classes

Original SeratoBaseReader class extracted from the monolithic serato.py file.
This preserves all the original functionality and complexity that was
developed and tested over time.
"""

import datetime
import pathlib
import struct
import typing as t
from collections.abc import Callable

import aiofiles


class SeratoRuleMatchingMixin:  # pylint: disable=too-few-public-methods
    """Mixin class for Serato smart rule matching functionality"""

    @staticmethod
    def _get_field_type(field_name: str) -> str:
        """Determine the data type for a field based on field name"""
        # Based on serato-tools reference implementation
        text_fields = {
            "artist",
            "album",
            "song",
            "title",
            "genre",
            "comment",
            "composer",
            "grouping",
            "label",
            "remixer",
            "filename",
            "key",
        }
        numeric_fields = {"bpm", "plays", "year", "length", "bitrate", "samplerate"}
        date_fields = {"added", "date", "first_played", "last_played"}

        if field_name in text_fields:
            return "text"
        if field_name in numeric_fields:
            return "numeric"
        if field_name in date_fields:
            return "date"
        return "text"  # Default to text

    @staticmethod
    def _get_operator_name(operator_code: int) -> str:
        """Map Serato operator codes to operator names"""
        # Enhanced mapping based on serato-tools reference
        operator_map = {
            # Text operators
            0: "contains",
            1: "does_not_contain",
            2: "is",
            3: "is_not",
            # Numeric operators
            4: "contains",  # For text fields
            5: "greater_than_equal",
            6: "less_than_equal",
            # Date operators
            7: "date_before",
            8: "date_after",
            # Additional operators found in practice
            9: "contains",
            10: "is",
        }

        return operator_map.get(operator_code, "contains")

    @staticmethod
    def _apply_text_operator(operator: str, content: str, value: str) -> bool:
        """Apply text-based operators"""
        if operator == "contains":
            return value in content
        if operator == "does_not_contain":
            return value not in content
        if operator == "is":
            return content == value
        if operator == "is_not":
            return content != value
        return value in content

    @staticmethod
    def _apply_numeric_operator(operator: str, track_value: t.Any, rule_value: t.Any) -> bool:
        """Apply numeric operators"""
        try:
            track_num = float(track_value)
            rule_num = float(rule_value)

            if operator == "greater_than_equal":
                return track_num >= rule_num
            if operator == "less_than_equal":
                return track_num <= rule_num
            if operator == "is":
                return track_num == rule_num
            if operator == "is_not":
                return track_num != rule_num
            return True
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _apply_date_operator(operator: str, track_value: t.Any, rule_value: t.Any) -> bool:
        """Apply date-based operators"""
        try:
            # For now, treat dates as unix timestamps
            track_date = int(track_value) if track_value else 0
            rule_date = int(rule_value) if rule_value else 0

            if operator == "date_before":
                return track_date < rule_date
            if operator == "date_after":
                return track_date > rule_date
            return True
        except (ValueError, TypeError):
            return False


class SeratoBaseReader:  # pylint: disable=too-few-public-methods
    """Base class for reading Serato binary files with common parsing functionality"""

    def __init__(self, filename: str | pathlib.Path) -> None:
        # Default decode functions - subclasses can override/extend
        self.decode_func_full: dict[str | None, Callable[[bytes], t.Any]] = {
            None: self._decode_struct,
            "vrsn": self._decode_unicode,
            "sbav": self._noop,
            "rart": self._noop,
            "rlut": self._noop,
            "rurt": self._noop,
        }

        self.decode_func_first: dict[str, Callable[[bytes], t.Any]] = {
            "b": lambda x: struct.unpack("?", x)[0],
            "o": self._decode_struct_sync,
            "p": lambda x: x.decode("utf-16-be", errors="replace"),
            "r": self._decode_struct_sync,
            "s": lambda x: struct.unpack(">H", x)[0],
            "t": lambda x: x.decode("utf-16-be", errors="replace"),
            "u": self._decode_unsigned,  # Keep our error handling
        }

        self.filepath: pathlib.Path = pathlib.Path(filename)
        self.data: list[tuple[str, t.Any]] | None = None

    def _decode_struct(self, data: bytes) -> list[tuple[str, t.Any]]:
        """decode the structures of the file"""
        ret: list[tuple[str, t.Any]] = []
        i = 0
        while i < len(data):
            tag = data[i : i + 4].decode("ascii")
            length = struct.unpack(">I", data[i + 4 : i + 8])[0]
            value = data[i + 8 : i + 8 + length]
            value = self._datadecode(value, tag=tag)
            ret.append((tag, value))
            i += 8 + length
        return ret

    @staticmethod
    def _decode_timestamp(data: bytes) -> datetime.datetime:
        """decode timestamp from bytes"""
        try:
            timestamp = struct.unpack(">I", data)[0]
        except struct.error:
            timestamp = struct.unpack(">Q", data)[0]
        return datetime.datetime.fromtimestamp(timestamp)

    @staticmethod
    def _decode_hex(data: bytes) -> str:
        """read a string, then encode as hex"""
        return data.hex()

    @staticmethod
    def _decode_bool(data: bytes) -> bool:
        """true/false handling"""
        return bool(struct.unpack("b", data)[0])

    @staticmethod
    def _decode_unicode(data: bytes) -> str:
        return data.decode("utf-16-be")[:-1]

    @staticmethod
    def _decode_unsigned(data: bytes) -> int:
        try:
            field = struct.unpack(">I", data)[0]
        except struct.error:
            field = struct.unpack(">Q", data)[0]
        return field

    @staticmethod
    def _noop(data: bytes) -> bytes:
        return data

    def _decode_struct_sync(self, data: bytes) -> tuple[tuple[str, t.Any], ...]:
        """Synchronous wrapper for struct decoding - fallback to old method"""
        return self._decode_struct(data)

    def _datadecode(self, data: bytes, tag: str | None = None) -> t.Any:
        if tag in self.decode_func_full:
            decode_func = self.decode_func_full[tag]
        else:
            decode_func = self.decode_func_first[tag[0]]

        return decode_func(data)

    async def loadfile(self) -> None:
        """load/overwrite current data"""
        async with aiofiles.open(self.filepath, "rb") as filefhin:
            self.data = self._datadecode(await filefhin.read())
