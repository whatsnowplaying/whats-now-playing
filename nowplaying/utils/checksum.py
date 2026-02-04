#!/usr/bin/env python3
"""Unified checksum utility for template files"""

import logging
import hashlib
import os
import pathlib

# Files and directories that should be excluded from template processing
EXCLUDED_FILES = {".gitignore", ".DS_Store", "Thumbs.db", ".git"}


def checksum(filename: str | pathlib.Path, treat_as_extension: str | None = None):
    """
    Generate SHA512 hash, normalizing line endings for text files.

    This function is shared between tools/updateshas.py and
    nowplaying/upgrades/templates.py to ensure consistent hashing
    across platforms and use cases.

    Args:
        filename: Path to the file to checksum
        treat_as_extension: Optional extension to use for determining file type.
                          Can be with or without leading dot (e.g., ".htm" or "htm").
                          Used for .new files that should be treated as their base type.

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
        # Use explicitly provided extension, or detect from filename
        if treat_as_extension:
            file_ext = treat_as_extension.lower()
            # Normalize to ensure leading dot
            if not file_ext.startswith("."):
                file_ext = f".{file_ext}"
        else:
            file_ext = os.path.splitext(str(filename))[1].lower()

        if file_ext in text_extensions:
            # Text file: normalize line endings and path separators
            try:
                with open(filename, "r", encoding="utf-8") as fileh:
                    content = (
                        fileh.read().replace("\r\n", "\n").replace("\r", "\n").replace("\\", "/")
                    )
                    hashfunc.update(content.encode("utf-8"))
                    if treat_as_extension:
                        logging.debug(
                            "checksum: %s read as UTF-8 text (treated as %s)", filename, file_ext
                        )
                    else:
                        logging.debug("checksum: %s read as UTF-8 text", filename)
            except UnicodeDecodeError as err:
                # Fall back to binary mode if UTF-8 fails
                logging.debug("checksum: %s failed UTF-8, using binary: %s", filename, err)
                with open(filename, "rb") as fileh:
                    while chunk := fileh.read(128 * hashfunc.block_size):
                        hashfunc.update(chunk)
        else:
            # Binary file: hash as-is
            with open(filename, "rb") as fileh:
                while chunk := fileh.read(128 * hashfunc.block_size):
                    hashfunc.update(chunk)

        return hashfunc.hexdigest()

    except (OSError, IOError) as error:
        logging.warning("Failed to checksum file %s: %s", filename, error)
        return None
