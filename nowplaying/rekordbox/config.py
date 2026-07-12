#!/usr/bin/env python3
"""
Rekordbox Configuration Reader

This module handles reading and parsing Rekordbox configuration files
to extract database encryption keys and other settings.
"""

import base64
import json
import logging
import os
import pathlib

from Crypto.Cipher import Blowfish


# RB6: Blowfish ECB magic key for decrypting the 'dp' field in options.json
_XOR_KEY = b"wnp_rb_secret_key"
_RB6_MAGIC_BLOB = "LSEHCh43BSoUBks3EDJdDw=="


def _decode_secret(blob: str) -> str:
    """Decode an obfuscated secret from its stored blob form."""
    data = base64.b64decode(blob)
    return bytes(b ^ _XOR_KEY[i % len(_XOR_KEY)] for i, b in enumerate(data)).decode()


def _decrypt_rb6_dp(dp_b64: str) -> str:
    """Decrypt the Blowfish-encrypted 'dp' field from Rekordbox options.json."""
    magic = _decode_secret(_RB6_MAGIC_BLOB).encode()
    cipher = Blowfish.new(magic, Blowfish.MODE_ECB)
    encrypted = base64.b64decode(dp_b64)
    decrypted = cipher.decrypt(encrypted)
    # PKCS5 unpadding: remove trailing pad bytes
    pad_len = decrypted[-1]
    if pad_len < 1 or pad_len > 8:
        pad_len = 0
    return decrypted[: len(decrypted) - pad_len].decode("utf-8").strip()


def _get_options_path() -> pathlib.Path:
    """Return the path to Rekordbox's options.json file."""
    if os.name != "nt":
        return (
            pathlib.Path.home()
            / "Library"
            / "Application Support"
            / "Pioneer"
            / "rekordboxAgent"
            / "storage"
            / "options.json"
        )
    if appdata := os.getenv("APPDATA"):
        return pathlib.Path(appdata) / "Pioneer" / "rekordboxAgent" / "storage" / "options.json"
    return (
        pathlib.Path.home()
        / "AppData"
        / "Roaming"
        / "Pioneer"
        / "rekordboxAgent"
        / "storage"
        / "options.json"
    )


def _parse_options_json(path: pathlib.Path) -> dict[str, str]:
    """Parse options.json and return a flat key→value dict."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {entry[0]: entry[1] for entry in data.get("options", [])}


class ConfigReader:
    """Reads Rekordbox configuration files and extracts settings"""

    def __init__(self):
        self.home_dir = pathlib.Path.home()

    def get_data_path(self) -> pathlib.Path:
        """Get the Rekordbox data directory path (RB7 default location)."""
        if os.name != "nt":
            return self.home_dir / "Library" / "Pioneer" / "rekordbox"
        if appdata := os.getenv("APPDATA"):
            return pathlib.Path(appdata) / "Pioneer" / "rekordbox"
        return self.home_dir / "AppData" / "Roaming" / "Pioneer" / "rekordbox"

    def get_database_path(self) -> pathlib.Path:
        """Get the path to the Rekordbox master database.

        Reads the actual path from options.json when available; falls back to
        the default RB7 location.
        """
        options_path = _get_options_path()
        if options_path.exists():
            try:
                options = _parse_options_json(options_path)
                db_path = options.get("db-path", "")
                if db_path:
                    return pathlib.Path(db_path)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Could not read db-path from options.json; using default")
        return self.get_data_path() / "master.db"

    @staticmethod
    def get_password() -> str:
        """Return the database decryption password, if one can be auto-detected.

        The password is Blowfish-encrypted in the 'dp' field of
        options.json.  This field is present on RB6 installs and also on
        RB7 installs that were upgraded from RB6, but is not guaranteed
        on a fresh RB7 install (Pioneer's own docs suggest RB7 has no
        embedded key). Callers must independently validate any key this
        returns actually opens the database before trusting it, and fall
        back to the custom_key setting if it doesn't.
        """
        options_path = _get_options_path()
        if options_path.exists():
            try:
                options = _parse_options_json(options_path)
                dp = options.get("dp", "")
                if dp:
                    logging.debug("Decrypting database password from options.json")
                    return _decrypt_rb6_dp(dp)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Could not extract database password from options.json")

        return ""

    def get_image_path(self, image_path: str) -> pathlib.Path:  # pylint: disable=no-self-use
        """Convert a relative image path from the database to an absolute path.

        Artwork is always stored under the Rekordbox data root share/ directory,
        regardless of whether master.db was relocated via the db-path option.
        """
        return self.get_data_path() / "share" / image_path
