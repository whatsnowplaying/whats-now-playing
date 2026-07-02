#!/usr/bin/env python3
"""non-UI utility code for upgrade"""

import copy
import functools
import logging
import re
import typing as t

import requests

import nowplaying.version  # pylint: disable=import-error, no-name-in-module
from nowplaying.upgrades.platform import PlatformDetector

if t.TYPE_CHECKING:
    import nowplaying.config

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


@functools.total_ordering
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

        if self.chunk.get("commitnum"):
            commit_str = str(self.chunk["commitnum"])
            leading = commit_str.split(".", maxsplit=1)[0]
            self.chunk["commitnum_number"] = int(leading) if leading.isdigit() else 0

        if (
            self.chunk.get("rc") is not None
            or self.chunk.get("preview") is not None
            or self.chunk.get("prerelease") is not None
            or self.chunk.get("commitnum")
        ):
            self.pre = True

    def _sort_key(self) -> tuple[int, int, int, int, int]:
        """Canonical sort key for total ordering.

        Tiers (ascending):
          0 — pre-release (rc, preview, or generic prerelease); rc and preview
              are treated as equivalent — only the number distinguishes them.
          1 — stable release
          2 — dev build (commit on top of a release tag)
        """
        if self.chunk.get("commitnum"):
            commitnum = int(self.chunk.get("commitnum_number") or 0)
            return (self.major, self.minor, self.micro, 2, commitnum)
        if not self.pre:
            return (self.major, self.minor, self.micro, 1, 0)
        # rc and preview share tier 0; the number is the sub-key.
        # Use explicit None checks — rc0/preview0 are valid and int(0) is falsy.
        # Generic prerelease strings (e.g. "alpha") have no number and all sort equally at 0;
        # WNP only uses rc/preview so this is intentional.
        rc = self.chunk.get("rc")
        preview = self.chunk.get("preview")
        if rc is not None:
            pre_num = int(rc)
        elif preview is not None:
            pre_num = int(preview)
        else:
            pre_num = 0
        return (self.major, self.minor, self.micro, 0, pre_num)

    @property
    def major(self) -> int:
        """major version number"""
        return int(self.chunk.get("major") or 0)

    @property
    def minor(self) -> int:
        """minor version number"""
        return int(self.chunk.get("minor") or 0)

    @property
    def micro(self) -> int:
        """micro version number"""
        return int(self.chunk.get("micro") or 0)

    def is_prerelease(self) -> bool:
        """if a pre-release, return True"""
        return self.pre

    def __str__(self) -> str:
        return self.textversion

    def __lt__(self, other: t.Any) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def __eq__(self, other: t.Any) -> bool:
        if not isinstance(other, Version):
            return False
        return self._sort_key() == other._sort_key()

    def __hash__(self) -> int:
        return hash(self._sort_key())


def _is_prerelease(version: str) -> bool:
    """Return True if the version string indicates a pre-release"""
    return any(marker in version for marker in _PRERELEASE_MARKERS)


def _build_version_params(
    platform_info: dict[str, t.Any],
    prefer_prerelease: bool = False,
) -> dict[str, t.Any]:
    """Build query params for the version-check API from platform info.

    prefer_prerelease: opt-in flag from settings.  Sends `track=prerelease`
    even when the user is currently on a stable build, so stable users
    can subscribe to the prerelease track via the settings checkbox.
    Auto-detection via Version.is_prerelease() still applies: a user
    already running a prerelease keeps getting prereleases regardless
    of the setting.
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
    if Version(current_version).is_prerelease() or prefer_prerelease:
        params["track"] = "prerelease"

    return params


def ping_version(config: "nowplaying.config.ConfigFile") -> None:
    """Ping the version-check endpoint with the charts key.

    Fire-and-forget: called at startup when a charts key already exists so the
    server can correlate the running version with a known user account.

    If the charts key is missing or empty, this function returns without
    making a request.
    """
    charts_key: str = config.cparser.value("charts/charts_key", defaultValue="", type=str)

    if not charts_key:
        return

    params = _build_version_params(PlatformDetector.get_platform_info())

    try:
        response = requests.get(
            UPDATE_CHECK_URL,
            params=params,
            headers={"X-API-Key": charts_key},
            timeout=1,
        )
        logging.debug("Version ping succeeded: HTTP %s", response.status_code)
    except requests.RequestException:
        logging.debug("Version ping failed", exc_info=True)


def check_for_update(
    platform_info: dict[str, t.Any],
    prefer_prerelease: bool = False,
) -> dict[str, t.Any] | None:
    """Check for updates via whatsnowplaying.com API.

    Sends current version and platform info to the API.
    Returns the response dict if an update is available, None otherwise.

    prefer_prerelease: opt-in flag from settings; see _build_version_params.
    """
    params = _build_version_params(platform_info, prefer_prerelease=prefer_prerelease)

    try:
        response = requests.get(UPDATE_CHECK_URL, params=params, timeout=10)
        response.raise_for_status()
        data: dict[str, t.Any] = response.json()
        if data.get("update_available"):
            if not data.get("latest_version"):
                logging.warning(
                    "Update check: update_available=True but latest_version missing/empty; "
                    "treating as no update (malformed API response)"
                )
                return None
            return data
        return None
    except Exception:  # pylint: disable=broad-except
        logging.debug("Update check failed", exc_info=True)
        return None
