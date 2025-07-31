#!/usr/bin/env python3
"""
Serato Crate Reader

Original SeratoCrateReader class extracted from the monolithic serato.py file.
This preserves all the original functionality and complexity that was
developed and tested over time.
"""

import logging
import pathlib
import typing as t

from .base import SeratoBaseReader


class SeratoCrateReader(SeratoBaseReader):
    """read a Serato crate (not smart crate) -
    based on https://gist.github.com/kerrickstaley/8eb04988c02fa7c62e75c4c34c04cf02"""

    def __init__(self, filename: str | pathlib.Path) -> None:
        super().__init__(filename)
        self.crate: list[tuple[str, t.Any]] | None = None
        self._cached_file_count: int | None = None

    async def loadcrate(self) -> None:
        """load/overwrite current crate"""
        await self.loadfile()
        self.crate = self.data
        self._cached_file_count = None  # Clear cache when reloading

    def getfilenames(self) -> list[str] | None:
        """get the filenames from this crate"""
        if not self.crate:
            logging.error("crate has not been loaded")
            return None
        filelist: list[str] = []
        anchor = self.filepath.anchor
        for tag in self.crate:
            if tag[0] != "otrk":
                continue
            otrk = tag[1]
            for subtag in otrk:
                if subtag[0] != "ptrk":
                    continue
                for filepart in subtag[1:]:
                    filename = str(pathlib.Path(anchor) / filepart)
                    filelist.append(filename)
        return filelist

    def count_files(self) -> int:
        """count the number of files in this crate (cached after first call)"""
        if not self.crate:
            logging.error("crate has not been loaded")
            return 0

        # Return cached count if available
        if self._cached_file_count is not None:
            return self._cached_file_count

        # Calculate and cache count
        count = 0
        for tag in self.crate:
            if tag[0] != "otrk":
                continue
            otrk = tag[1]
            for subtag in otrk:
                if subtag[0] != "ptrk":
                    continue
                count += len(subtag[1:])

        self._cached_file_count = count
        return count

    def get_file_at_index(self, index: int) -> str | None:
        """get the filename at a specific index without loading all files"""
        if not self.crate:
            logging.error("crate has not been loaded")
            return None
        current_index = 0
        anchor = self.filepath.anchor
        for tag in self.crate:
            if tag[0] != "otrk":
                continue
            otrk = tag[1]
            for subtag in otrk:
                if subtag[0] != "ptrk":
                    continue
                for filepart in subtag[1:]:
                    if current_index == index:
                        return str(pathlib.Path(anchor) / filepart)
                    current_index += 1
        return None
