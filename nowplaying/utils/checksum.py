#!/usr/bin/env python3
"""Unified checksum utility for template files"""

import hashlib
import os
import pathlib


def checksum(filename: str | pathlib.Path):
    """
    Generate SHA512 hash, normalizing line endings for text files.

    This function is shared between tools/updateshas.py and
    nowplaying/upgrades/templates.py to ensure consistent hashing
    across platforms and use cases.
    """
    hashfunc = hashlib.sha512()

    # Check if file is likely a text file based on extension
    text_extensions = {".htm", ".html", ".css", ".js", ".txt", ".md", ".json", ".xml", ".yaml", ".yml"}
    file_ext = os.path.splitext(str(filename))[1].lower()

    if file_ext in text_extensions:
        # Text file: normalize line endings
        try:
            with open(filename, "r", encoding="utf-8") as fileh:
                content = fileh.read().replace("\r\n", "\n").replace("\r", "\n")
                hashfunc.update(content.encode("utf-8"))
        except UnicodeDecodeError:
            # Fall back to binary mode if UTF-8 fails
            with open(filename, "rb") as fileh:
                while chunk := fileh.read(128 * hashfunc.block_size):
                    hashfunc.update(chunk)
    else:
        # Binary file: hash as-is
        with open(filename, "rb") as fileh:
            while chunk := fileh.read(128 * hashfunc.block_size):
                hashfunc.update(chunk)

    return hashfunc.hexdigest()
