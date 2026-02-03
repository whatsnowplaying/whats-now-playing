#!/usr/bin/env python3
"""Unified checksum utility for template files"""

import logging
import hashlib
import os
import pathlib

# Files and directories that should be excluded from template processing
EXCLUDED_FILES = {".gitignore", ".DS_Store", "Thumbs.db", ".git"}


def checksum(filename: str | pathlib.Path):
    """
    Generate SHA512 hash, normalizing line endings for text files.

    This function is shared between tools/updateshas.py and
    nowplaying/upgrades/templates.py to ensure consistent hashing
    across platforms and use cases.

    Returns None if the file cannot be read or processed.
    """
    try:
        hashfunc = hashlib.sha512()

        # Check if file is likely a text file based on extension
        text_extensions = {
            ".htm",
            ".html",
            ".css",
            ".js",
            ".txt",
            ".md",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
        }
        file_ext = os.path.splitext(str(filename))[1].lower()

        if file_ext in text_extensions:
            # Text file: normalize line endings and path separators
            try:
                with open(filename, "r", encoding="utf-8") as fileh:
                    content = (
                        fileh.read().replace("\r\n", "\n").replace("\r", "\n").replace("\\", "/")
                    )
                    hashfunc.update(content.encode("utf-8"))
                    logging.debug("checksum: %s read as UTF-8 text", filename)
            except UnicodeDecodeError as e:
                # Fall back to binary mode if UTF-8 fails
                logging.debug("checksum: %s failed UTF-8, using binary: %s", filename, e)
                with open(filename, "rb") as fileh:
                    while chunk := fileh.read(128 * hashfunc.block_size):
                        hashfunc.update(chunk)
        else:
            # Binary file: hash as-is
            with open(filename, "rb") as fileh:
                while chunk := fileh.read(128 * hashfunc.block_size):
                    hashfunc.update(chunk)

        return hashfunc.hexdigest()

    except (OSError, IOError, PermissionError) as error:
        logging.warning("Failed to checksum file %s: %s", filename, error)
        return None
