#!/usr/bin/env python3
"""
Configuration import/export utilities for JSON format.

Provides functions to export Qt settings to JSON and import JSON back to Qt settings,
with proper filtering of runtime/cache data and cross-platform compatibility.
"""

import json
import logging
import os
import pathlib
import time

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication,
    QSettings,
)

import nowplaying.version  # pylint: disable=no-name-in-module,import-error

HOME_TOKEN = "{HOME}"

IGNORE_KEYS = [
    "settings/lastsavedate",
    "control/paused",
    "testmode/",
    "cache/",
    "db/",
    "artistextras/cachedbfile",
]

# Settings keys whose values are filesystem paths for non-plugin processes.
# Plugin-owned path keys are declared via WNPBasePlugin.get_path_keys() and
# collected at export/import time via ConfigFile.get_path_keys().
# On export, the user's home directory is replaced with HOME_TOKEN for portability.
# On import, HOME_TOKEN is expanded to the current home directory; paths whose
# parent directory does not exist on this system are logged, reported in a
# warnings file next to the import file, and skipped.
PATH_KEYS: frozenset[str] = frozenset(
    {
        "discord/template",
        "kick/announce",
        "obsws/template",
        "twitchbot/announce",
        "weboutput/artistbannertemplate",
        "weboutput/artistfanarttemplate",
        "weboutput/artistlogotemplate",
        "weboutput/artistthumbnailtemplate",
        "weboutput/gifwordstemplate",
        "weboutput/htmltemplate",
        "weboutput/requestertemplate",
    }
)


def export_config(
    export_path: pathlib.Path,
    settings: QSettings,
    extra_path_keys: frozenset[str] | None = None,
) -> bool:
    """
    Export configuration to JSON file.

    WARNING: Exported file contains sensitive data including API keys,
    tokens, passwords, and system paths. Store securely and do not share.

    Args:
        export_path: Path where to save the exported configuration
        extra_path_keys: Additional filesystem path keys collected from plugins

    Returns:
        True if export successful, False otherwise
    """

    try:
        # Sync to ensure we have latest settings

        # Use childGroups() and childKeys() to avoid system preferences contamination
        # that can occur with allKeys() on macOS
        config_data = {}

        home = str(pathlib.Path.home())
        effective_path_keys = PATH_KEYS | (extra_path_keys or frozenset())

        # Get keys from each configuration group (avoids system preferences)
        for group in settings.childGroups():
            settings.beginGroup(group)
            group_keys = settings.childKeys()

            for key in group_keys:
                full_key = f"{group}/{key}"

                # Skip excluded settings
                if any(full_key.startswith(pattern) for pattern in IGNORE_KEYS):
                    continue

                value = settings.value(key)

                # Convert QSettings types to JSON-serializable types
                if (
                    isinstance(value, bool)
                    or value is not None
                    and isinstance(value, (int, float, str))
                ):
                    pass  # bools are fine
                elif value is None:
                    value = None
                elif isinstance(value, list):
                    # Convert list items to strings
                    value = [str(item) for item in value]
                else:
                    # Convert everything else to string
                    value = str(value)

                # Replace a leading home directory prefix with HOME_TOKEN in path keys.
                # Only replaces at the start of the value to avoid corrupting values
                # where the home path appears elsewhere (e.g. embedded in another dir).
                if (
                    full_key in effective_path_keys
                    and isinstance(value, str)
                    and home
                    and (value == home or value.startswith(home + os.sep))
                ):
                    value = HOME_TOKEN + value[len(home) :]

                config_data[full_key] = value

            settings.endGroup()

        # Add metadata about the export
        export_metadata = {
            "_export_info": {
                "version": nowplaying.version.__VERSION__,  # pylint: disable=no-member
                "export_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                "application": QCoreApplication.applicationName(),
                "organization": QCoreApplication.organizationName(),
                "warning": "This file contains sensitive data including API keys and passwords",
            }
        }

        # Combine metadata and config
        full_export = export_metadata | config_data

        # Write to file with restrictive permissions
        _ = export_path.write_text(json.dumps(full_export, indent=2, sort_keys=True))

        # Set restrictive file permissions (user read/write only)
        # On Windows, this may not work as expected but won't fail
        try:
            export_path.chmod(0o600)
        except (OSError, NotImplementedError):
            # Windows may not support Unix-style permissions, but file is still created
            logging.debug("Could not set restrictive file permissions (platform limitation)")

        logging.info("Configuration exported to: %s", export_path)
        return True

    except (OSError, TypeError, ValueError) as error:
        logging.error("Failed to export configuration: %s", error)
        return False


def import_config(
    import_path: pathlib.Path,
    settings: QSettings,
    extra_path_keys: frozenset[str] | None = None,
) -> QSettings | None:
    """
    Import configuration from JSON file.

    This will overwrite current settings with imported values.
    Runtime state, cache settings, and paths that are inaccessible on this
    system are automatically excluded.

    Args:
        import_path: Path to the JSON configuration file
        extra_path_keys: Additional filesystem path keys collected from plugins

    Returns:
        True if import successful, False otherwise
    """

    if not import_path.exists():
        logging.error("Import file does not exist: %s", import_path)
        return None

    try:
        # Load the JSON data
        import_data: dict[str, str | dict[str, str]] = json.loads(import_path.read_text())
    except json.JSONDecodeError as error:
        logging.error("Invalid JSON in import file: %s", error)
        return None
    except (OSError, KeyError, ValueError) as error:
        logging.error("Failed to import configuration: %s", error)
        return None

    # Check if this looks like a valid export
    if "_export_info" not in import_data:
        logging.warning("Import file may not be a valid configuration export")

    # Log import info
    if "_export_info" in import_data:
        export_info: dict[str, str] = import_data["_export_info"]
        logging.info(
            "Importing config from version %s, exported on %s",
            export_info.get("version", "unknown"),
            export_info.get("export_date", "unknown"),
        )
        # Remove metadata before processing
        del import_data["_export_info"]

    home = str(pathlib.Path.home())
    effective_path_keys = PATH_KEYS | (extra_path_keys or frozenset())
    skipped_paths: list[tuple[str, str]] = []

    # Import all settings from the file
    for key, value in import_data.items():
        if any(key.startswith(pattern) for pattern in IGNORE_KEYS):
            continue

        if key in effective_path_keys and isinstance(value, str) and value:
            # Expand the home directory token to this system's home
            if HOME_TOKEN in value:
                value = value.replace(HOME_TOKEN, home)
            # Normalize Windows-style separators so cross-OS detection works on Unix.
            # On Unix, "C:\foo\bar" is treated as a single filename by pathlib (parent="."),
            # but after replacing "\" with "/" it becomes "C:/foo/bar" which is NOT absolute
            # on Unix (no leading "/"), so is_absolute() correctly rejects it.
            normalized = value.replace("\\", "/")
            path_obj = pathlib.Path(normalized)
            # Skip paths that are not absolute on this system, or whose parent doesn't exist
            # (catches Windows paths on Unix and vice versa, and paths from other users/machines)
            if not path_obj.is_absolute() or not path_obj.parent.exists():
                logging.warning("Skipping path not accessible on this system: %s = %s", key, value)
                skipped_paths.append((key, value))
                continue

        settings.setValue(key, value)

    if skipped_paths:
        _write_import_warnings(import_path, skipped_paths)

    logging.info("Configuration imported successfully from: %s", import_path)
    return settings


def _write_import_warnings(
    import_path: pathlib.Path, skipped_paths: list[tuple[str, str]]
) -> None:
    """Write a human-readable warnings file listing paths that could not be imported."""
    warnings_path = import_path.with_name(import_path.stem + "_import_warnings.txt")
    lines = [
        "WhatsNowPlaying - Configuration Import Warnings",
        "=" * 50,
        "",
        "The following path settings could not be imported because they do not",
        "exist on this system (likely exported from a different operating system).",
        "Please reconfigure these settings manually after starting the application.",
        "",
    ]
    for key, value in skipped_paths:
        lines.append(f"  {key}")
        lines.append(f"    skipped value: {value}")
        lines.append("")

    try:
        warnings_path.write_text("\n".join(lines))
        logging.info("Import warnings written to: %s", warnings_path)
    except OSError as error:
        logging.warning("Could not write import warnings file: %s", error)
