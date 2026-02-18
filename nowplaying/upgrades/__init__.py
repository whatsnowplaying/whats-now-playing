#!/usr/bin/env python3
"""non-UI utility code for upgrade"""

import logging
import typing as t

import requests

import nowplaying.version  # pylint: disable=import-error, no-name-in-module

UPDATE_CHECK_URL = "https://whatsnowplaying.com/api/v1/check-version"

_PRERELEASE_MARKERS = ("-rc", "-preview", "+")


def _is_prerelease(version: str) -> bool:
    """Return True if the version string indicates a pre-release"""
    return any(marker in version for marker in _PRERELEASE_MARKERS)


def check_for_update(platform_info: dict[str, t.Any]) -> dict[str, t.Any] | None:
    """Check for updates via whatsnowplaying.com API.

    Sends current version and platform info to the API.
    Returns the response dict if an update is available, None otherwise.
    """
    current_version = nowplaying.version.__VERSION__  # pylint: disable=no-member

    params: dict[str, t.Any] = {
        "version": current_version,
        "os": platform_info.get("os", "unknown"),
    }

    if chipset := platform_info.get("chipset"):
        params["chipset"] = chipset
    if macos_version := platform_info.get("macos_version"):
        params["macos_version"] = macos_version
    if _is_prerelease(current_version):
        params["track"] = "prerelease"

    try:
        response = requests.get(UPDATE_CHECK_URL, params=params, timeout=10)
        response.raise_for_status()
        data: dict[str, t.Any] = response.json()
        if data.get("update_available"):
            return data
        return None
    except Exception:  # pylint: disable=broad-except
        logging.debug("Update check failed")
        return None
