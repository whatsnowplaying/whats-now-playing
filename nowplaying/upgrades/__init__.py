#!/usr/bin/env python3
"""non-UI utility code for upgrade"""

import copy
import logging
import re
import typing as t

import requests

import nowplaying.version  # pylint: disable=import-error, no-name-in-module

UPDATE_CHECK_URL = "https://whatsnowplaying.com/api/v1/check-version"

_PRERELEASE_MARKERS = ("-rc", "-preview", "+")

# regex that support's git describe --tags as well as many semver-type strings
# based upon the now deprecated distutils version code
VERSION_REGEX = re.compile(
    r"""
        ^
        (?P<major>0|[1-9]\d*)
        \.
        (?P<minor>0|[1-9]\d*)
        \.
        (?P<micro>0|[1-9]\d*)
        (?:-(?:rc(?P<rc>(?:0|\d*))|preview(?P<preview>\d*)|(?P<prerelease>[a-zA-Z]+\d*)))?
        (?:[-+](?P<commitnum>
            (?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)
            (?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*
        ))?
        (?:\.(?P<identifier>
            [0-9a-zA-Z-]+
            (?:\.[0-9a-zA-Z-]+)*
        ))?
        $
        """,
    re.VERBOSE,
)


class Version:
    """process a version"""

    def __init__(self, version: str):
        self.textversion = version
        vermatch = VERSION_REGEX.match(version.replace(".dirty", ""))
        if not vermatch:
            raise ValueError(f"cannot match {version}")
        self.pre = False
        self.chunk = vermatch.groupdict()
        self._calculate()

    def _calculate(self) -> None:
        olddict = copy.copy(self.chunk)
        for key, value in olddict.items():
            if isinstance(value, str) and value.isdigit():
                self.chunk[key] = int(value)

        if (
            self.chunk.get("rc")
            or self.chunk.get("preview")
            or self.chunk.get("prerelease")
            or self.chunk.get("commitnum")
        ):
            self.pre = True

    def is_prerelease(self) -> bool:
        """if a pre-release, return True"""
        return self.pre

    def __str__(self) -> str:
        return self.textversion

    def __lt__(  # pylint: disable=too-many-return-statements
        self, other: t.Any
    ) -> bool:
        """version compare
        do the easy stuff, major > minor > micro"""
        for key in ["major", "minor", "micro"]:
            if self.chunk.get(key) == other.chunk.get(key):
                continue
            return self.chunk.get(key) < other.chunk.get(key)

        # rc/preview/prerelease < no rc/preview/prerelease
        self_has_pre = (
            self.chunk.get("rc") or self.chunk.get("preview") or self.chunk.get("prerelease")
        )
        other_has_pre = (
            other.chunk.get("rc") or other.chunk.get("preview") or other.chunk.get("prerelease")
        )

        if self_has_pre:
            if not other_has_pre:
                return True

            # Compare rc numbers if both have rc
            if (
                self.chunk.get("rc")
                and other.chunk.get("rc")
                and self.chunk.get("rc") != other.chunk.get("rc")
            ):
                return self.chunk.get("rc") < other.chunk.get("rc")
            # Compare preview numbers if both have preview
            if (
                self.chunk.get("preview")
                and other.chunk.get("preview")
                and self.chunk.get("preview") != other.chunk.get("preview")
            ):
                return self.chunk.get("preview") < other.chunk.get("preview")
            # Compare prerelease strings if both have prerelease
            if (
                self.chunk.get("prerelease")
                and other.chunk.get("prerelease")
                and self.chunk.get("prerelease") != other.chunk.get("prerelease")
            ):
                return self.chunk.get("prerelease") < other.chunk.get("prerelease")

        # but commitnum > no commitnum at this point
        if self.chunk.get("commitnum") and not other.chunk.get("commitnum"):
            return False

        if (
            self.chunk.get("commitnum")
            and other.chunk.get("commitnum")
            and self.chunk.get("commitnum") != other.chunk.get("commitnum")
        ):
            return self.chunk.get("commitnum") < other.chunk.get("commitnum")

        return False

    def __le__(self, other: t.Any) -> bool:
        """version less than or equal"""
        return self == other or self < other

    def __eq__(self, other: t.Any) -> bool:
        """version equality"""
        if not isinstance(other, Version):
            return False
        return (
            self.chunk.get("major") == other.chunk.get("major")
            and self.chunk.get("minor") == other.chunk.get("minor")
            and self.chunk.get("micro") == other.chunk.get("micro")
            and self.chunk.get("rc") == other.chunk.get("rc")
            and self.chunk.get("preview") == other.chunk.get("preview")
            and self.chunk.get("prerelease") == other.chunk.get("prerelease")
            and self.chunk.get("commitnum") == other.chunk.get("commitnum")
        )

    def __ne__(self, other: t.Any) -> bool:
        """version not equal"""
        return not self == other

    def __hash__(self) -> int:
        """version hash"""
        return hash(
            (
                self.chunk.get("major"),
                self.chunk.get("minor"),
                self.chunk.get("micro"),
                self.chunk.get("rc"),
                self.chunk.get("preview"),
                self.chunk.get("prerelease"),
                self.chunk.get("commitnum"),
            )
        )

    def __gt__(self, other: t.Any) -> bool:
        """version greater than"""
        return not (self < other or self == other)

    def __ge__(self, other: t.Any) -> bool:
        """version greater than or equal"""
        return not self < other


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
        logging.debug("Update check failed", exc_info=True)
        return None
