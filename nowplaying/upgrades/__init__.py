#!/usr/bin/env python3
"""non-UI utility code for upgrade"""

import copy
import logging
import os
import re
import traceback
import typing as t

import requests

import nowplaying.version  # pylint: disable=import-error, no-name-in-module

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
        (?:-rc(?P<rc>(?:0|\d*)))?
        (?:[-+](?P<commitnum>
            (?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)
            (?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*
        ))?
        (?:-(?P<identifier>
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

        if self.chunk.get("rc") or self.chunk.get("commitnum"):
            self.pre = True

    def is_prerelease(self) -> bool:
        """if a pre-release, return True"""
        return self.pre

    def __str__(self) -> str:
        return self.textversion

    def __lt__(self, other: t.Any) -> bool:
        """version compare
        do the easy stuff, major > minor > micro"""
        for key in ["major", "minor", "micro"]:
            if self.chunk.get(key) == other.chunk.get(key):
                continue
            return self.chunk.get(key) < other.chunk.get(key)

        # rc < no rc
        if self.chunk.get("rc") and not other.chunk.get("rc"):
            return True

        if (
            self.chunk.get("rc")
            and other.chunk.get("rc")
            and self.chunk.get("rc") != other.chunk.get("rc")
        ):
            return self.chunk.get("rc") < other.chunk.get("rc")

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
                self.chunk.get("commitnum"),
            )
        )

    def __gt__(self, other: t.Any) -> bool:
        """version greater than"""
        return not (self < other or self == other)

    def __ge__(self, other: t.Any) -> bool:
        """version greater than or equal"""
        return not self < other


class UpgradeBinary:
    """routines to determine if the binary is out of date"""

    def __init__(self, testmode: bool = False):
        self.myversion = Version(nowplaying.version.__VERSION__)  # pylint: disable=no-member
        self.prerelease = Version("0.0.0-rc0")
        self.stable = Version("0.0.0")
        self.predata = None
        self.stabledata = None
        if not testmode:
            self.get_versions()

    def get_versions(self, testdata: list[dict[str, t.Any]] | None = None):  # pylint: disable=too-many-branches
        """ask github about current versions"""
        try:
            if not testdata:
                headers = {
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "What's Now Playing/{nowplaying.version.__VERSION__}",
                }
                if token := os.getenv("GITHUB_TOKEN"):
                    logging.debug("Using GITHUB_TOKEN")
                    headers["Authorization"] = f"Bearer {token}"
                req = requests.get(
                    "https://api.github.com/repos/whatsnowplaying/whats-now-playing/releases",
                    headers=headers,
                    timeout=100,
                )
                req.raise_for_status()
                jsonreldata: list[dict[str, t.Any]] = req.json()
            else:
                jsonreldata = testdata

            if not jsonreldata:
                logging.error("No data from Github. Aborting.")
                return

            for rel in jsonreldata:
                if not isinstance(rel, dict):
                    logging.error(rel)
                    break

                if rel.get("draft"):
                    continue

                tagname = Version(rel["tag_name"])
                if rel.get("prerelease"):
                    if self.prerelease < tagname:
                        self.prerelease = tagname
                        self.predata = rel
                elif self.stable < tagname:
                    self.stable = tagname
                    self.stabledata = rel

            if self.stable > self.prerelease:
                self.prerelease = self.stable
                self.predata = self.stabledata

        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)

    def get_upgrade_data(self) -> dict[str, t.Any] | None:
        """compare our version to fetched version data"""
        if self.myversion.is_prerelease():
            if self.myversion < self.prerelease:
                return self.predata
        elif self.myversion < self.stable:
            return self.stabledata
        return None
