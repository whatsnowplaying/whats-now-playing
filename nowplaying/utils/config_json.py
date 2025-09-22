#!/usr/bin/env python3
"""
Configuration import/export utilities for JSON format.

Provides functions to export Qt settings to JSON and import JSON back to Qt settings,
with proper filtering of runtime/cache data and cross-platform compatibility.
"""

import json
import logging
import pathlib
import time

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication,
    QSettings,
)

import nowplaying.version  # pylint: disable=no-name-in-module,import-error

IGNORE_KEYS = [
    "settings/lastsavedate",
    "control/paused",
    "testmode/",
    "cache/",
    "db/",
    "artistextras/cachedbfile",
]


def export_config(export_path: pathlib.Path, settings: QSettings) -> bool:
    """
    Export configuration to JSON file.

    WARNING: Exported file contains sensitive data including API keys,
    tokens, passwords, and system paths. Store securely and do not share.

    Args:
        export_path: Path where to save the exported configuration

    Returns:
        True if export successful, False otherwise
    """

    try:
        # Sync to ensure we have latest settings

        # Use childGroups() and childKeys() to avoid system preferences contamination
        # that can occur with allKeys() on macOS
        config_data = {}

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


def import_config(import_path: pathlib.Path, settings: QSettings) -> QSettings | None:
    """
    Import configuration from JSON file.

    This will overwrite current settings with imported values.
    Runtime state and cache settings are automatically excluded.

    Args:
        import_path: Path to the JSON configuration file

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

    # Import all settings from the file
    for key, value in import_data.items():
        if not any(key.startswith(pattern) for pattern in IGNORE_KEYS):
            settings.setValue(key, value)

    logging.info("Configuration imported successfully from: %s", import_path)
    return settings
