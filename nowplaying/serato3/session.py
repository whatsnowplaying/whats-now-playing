#!/usr/bin/env python3
"""
Serato Session Reader

Original SeratoSessionReader class extracted from the monolithic serato.py file.
This preserves all the original functionality and complexity that was
developed and tested over time.
"""

import logging
import pathlib
import struct
import typing as t
from collections.abc import Callable

from .base import SeratoBaseReader


class SeratoSessionReader(SeratoBaseReader):
    """read a Serato session file"""

    def __init__(self) -> None:
        # Initialize base class with dummy filename
        super().__init__("/dev/null")

        # Extend base decode functions with session-specific decoders
        self.decode_func_full.update(
            {
                "adat": self._decode_adat,
                "oent": self._decode_struct,
            }
        )

        # Session-specific ADAT field mapping
        self._adat_func: dict[int, list[str | Callable[[bytes], t.Any]]] = {
            2: ["pathstr", self._decode_unicode],
            3: ["location", self._decode_unicode],
            4: ["filename", self._decode_unicode],
            6: ["title", self._decode_unicode],
            7: ["artist", self._decode_unicode],
            8: ["album", self._decode_unicode],
            9: ["genre", self._decode_unicode],
            10: ["duration", self._decode_unicode],
            11: ["filesize", self._decode_unicode],
            13: ["bitrate", self._decode_unicode],
            14: ["frequency", self._decode_unicode],
            15: ["bpm", self._decode_unsigned],
            16: ["field16", self._decode_hex],
            17: ["comments", self._decode_unicode],
            18: ["lang", self._decode_unicode],
            19: ["grouping", self._decode_unicode],
            20: ["remixer", self._decode_unicode],
            21: ["label", self._decode_unicode],
            22: ["composer", self._decode_unicode],
            23: ["date", self._decode_unicode],
            28: ["starttime", self._decode_timestamp],
            29: ["endtime", self._decode_timestamp],
            31: ["deck", self._decode_unsigned],
            45: ["playtime", self._decode_unsigned],
            48: ["sessionid", self._decode_unsigned],
            50: ["played", self._decode_bool],
            51: ["key", self._decode_unicode],
            52: ["added", self._decode_bool],
            53: ["updatedat", self._decode_timestamp],
            63: ["playername", self._decode_unicode],
            64: ["commentname", self._decode_unicode],
        }

        self.sessiondata: list[dict[str, t.Any]] = []

    def _decode_adat(self, data: bytes) -> dict[str, t.Any]:
        ret: dict[str, t.Any] = {}
        # i = 0
        # tag = struct.unpack('>I', data[0:i + 4])[0]
        # length = struct.unpack('>I', data[i + 4:i + 8])[0]
        i = 8
        while i < len(data) - 8:
            tag = struct.unpack(">I", data[i + 4 : i + 8])[0]
            length = struct.unpack(">I", data[i + 8 : i + 12])[0]
            value = data[i + 12 : i + 12 + length]
            try:
                field = self._adat_func[tag][0]
                value = self._adat_func[tag][1](value)
            except KeyError:
                field = f"unknown{tag}"
                value = self._noop(value)
            ret[field] = value
            i += 8 + length
        if not ret.get("filename"):
            ret["filename"] = ret.get("pathstr")
        return ret

    async def loadsessionfile(self, filename: str | pathlib.Path) -> None:
        """load/extend current session"""
        self.filepath = pathlib.Path(filename)
        await self.loadfile()
        self.sessiondata.extend(self.data)

    def condense(self) -> None:
        """shrink to just adats"""
        adatdata: list[dict[str, t.Any]] = []
        if not self.sessiondata:
            logging.error("session has not been loaded")
            return
        for sessiontuple in self.sessiondata:
            if sessiontuple[0] == "oent":
                adatdata.extend(
                    oentdata[1] for oentdata in sessiontuple[1] if oentdata[0] == "adat"
                )

        self.sessiondata = adatdata

    def sortsession(self) -> None:
        """sort them by starttime"""
        records = sorted(self.sessiondata, key=lambda x: x.get("starttime"))
        self.sessiondata = records

    def getadat(self) -> t.Generator[dict[str, t.Any], None, None]:
        """get the filenames from this session"""
        if not self.sessiondata:
            logging.error("session has not been loaded")
            return
        yield from self.sessiondata

    def getreverseadat(self) -> t.Generator[dict[str, t.Any], None, None]:
        """same as getadat, but reversed order"""
        if not self.sessiondata:
            logging.error("session has not been loaded")
            return
        yield from reversed(self.sessiondata)
