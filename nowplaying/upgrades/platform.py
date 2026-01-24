#!/usr/bin/env python3
"""Platform detection and asset matching for upgrades"""

import logging
import platform
import re
import sys
import typing as t


class PlatformDetector:
    """Detect user's platform and match to available release assets"""

    @staticmethod
    def get_platform_info() -> dict[str, t.Any]:
        """
        Get detailed platform information for matching against release assets.

        Returns:
            dict with keys:
                - os: "windows", "macos", or "linux"
                - chipset: "intel", "arm", or None
                - macos_version: int (e.g., 12) or None for non-macOS
        """
        info: dict[str, t.Any] = {"os": None, "chipset": None, "macos_version": None}

        if sys.platform == "win32":
            info["os"] = "windows"
            info["chipset"] = None

        elif sys.platform == "darwin":
            info["os"] = "macos"

            # Get macOS version
            macos_version_str = platform.mac_ver()[0]  # e.g., "12.6.0"
            try:
                info["macos_version"] = int(macos_version_str.split(".")[0])
            except (ValueError, IndexError):
                logging.warning("Could not parse macOS version: %s", macos_version_str)
                info["macos_version"] = None

            # Get chipset
            machine = platform.machine()  # "arm64" or "x86_64"
            if machine == "arm64":
                info["chipset"] = "arm"
            elif machine == "x86_64":
                info["chipset"] = "intel"
            else:
                logging.warning("Unknown macOS machine type: %s", machine)
                info["chipset"] = None

        else:
            info["os"] = "linux"

        return info

    @staticmethod
    def find_best_matching_asset(
        release_data: dict[str, t.Any], platform_info: dict[str, t.Any]
    ) -> dict[str, t.Any] | None:
        """
        Find the best matching asset from a GitHub release for this platform.

        Strategy:
        - Windows: Match "Windows" in filename
        - macOS Intel: Match "Intel" in filename (any macOS version, forward compatible)
        - macOS ARM: Prefer "AppleSilicon" build, fall back to "Intel" (Rosetta 2)

        Args:
            release_data: GitHub release dict with "assets" list
            platform_info: Dict from get_platform_info()

        Returns:
            Dict with "name", "download_url", "size", "sha256" or None if no match
        """
        assets = release_data.get("assets", [])
        if not assets:
            return None

        os_type = platform_info.get("os")

        if os_type == "windows":
            return PlatformDetector._find_windows_asset(assets)

        if os_type == "macos":
            return PlatformDetector._find_macos_asset(assets, platform_info)

        # Linux or unknown
        return None

    @staticmethod
    def _find_windows_asset(assets: list[dict[str, t.Any]]) -> dict[str, t.Any] | None:
        """Find Windows asset (match on 'Windows' in name)"""
        for asset in assets:
            name = asset.get("name", "")
            # Match: WhatsNowPlaying-X.X.X-Windows.zip
            if "Windows" in name and name.endswith(".zip"):
                return PlatformDetector._build_asset_dict(asset)
        return None

    @staticmethod
    def _classify_macos_assets(assets: list[dict[str, t.Any]]) -> tuple[
        list[tuple[dict[str, t.Any], int | None]], list[tuple[dict[str, t.Any], int | None]]
    ]:
        """
        Classify macOS assets into ARM and Intel lists with version info.

        Args:
            assets: List of GitHub asset dicts

        Returns:
            Tuple of (arm_assets, intel_assets) where each is a list of (asset, version) tuples
        """
        arm_assets = []
        intel_assets = []

        for asset in assets:
            name = asset.get("name", "")

            if not name.endswith(".zip"):
                continue

            # Extract macOS version from filename (e.g., "macOS12" -> 12)
            macos_version = PlatformDetector._extract_macos_version(name)

            # Match new naming: WhatsNowPlaying-X.X.X-macOS##-AppleSilicon.zip
            # Also support old naming: WhatsNowPlaying-X.X.X-macos##_arm.zip
            if (
                "AppleSilicon" in name
                or "_arm" in name
                or "macos" in name.lower()
                and "arm" in name
            ):
                arm_assets.append((asset, macos_version))
            elif "Intel" in name or "_intel" in name:
                intel_assets.append((asset, macos_version))

        return arm_assets, intel_assets

    @staticmethod
    def _find_macos_asset(
        assets: list[dict[str, t.Any]], platform_info: dict[str, t.Any]
    ) -> dict[str, t.Any] | None:
        """
        Find best macOS asset based on chipset and OS version.

        Strategy:
        - Pick the highest macOS version build that is <= user's macOS version
        - ARM Macs: Prefer ARM build, fall back to Intel (Rosetta 2 compatibility)
        - Intel Macs: Use Intel builds only (cannot run ARM)
        """
        chipset = platform_info.get("chipset")
        user_macos_version = platform_info.get("macos_version")

        if not chipset:
            logging.error("Cannot determine macOS chipset")
            return None

        # Classify assets into ARM and Intel lists with version info
        arm_assets, intel_assets = PlatformDetector._classify_macos_assets(assets)

        # Filter to compatible versions (build version <= user version)
        # If user_macos_version is None, include all versions
        if user_macos_version is not None:
            arm_assets = [
                (asset, ver)
                for asset, ver in arm_assets
                if ver is None or ver <= user_macos_version
            ]
            intel_assets = [
                (asset, ver)
                for asset, ver in intel_assets
                if ver is None or ver <= user_macos_version
            ]

        # Sort by version (highest first), None versions go last
        arm_assets.sort(key=lambda x: x[1] if x[1] is not None else -1, reverse=True)
        intel_assets.sort(key=lambda x: x[1] if x[1] is not None else -1, reverse=True)

        # For ARM Macs: prefer ARM, fall back to Intel (Rosetta 2)
        if chipset == "arm":
            if arm_assets:
                asset, version = arm_assets[0]
                logging.info(
                    "Found ARM/AppleSilicon build: %s (macOS %s)",
                    asset["name"],
                    version if version else "unversioned",
                )
                return PlatformDetector._build_asset_dict(asset)
            if intel_assets:
                asset, version = intel_assets[0]
                logging.info(
                    "No ARM build found, using Intel build (Rosetta 2): %s (macOS %s)",
                    asset["name"],
                    version if version else "unversioned",
                )
                return PlatformDetector._build_asset_dict(asset)
            logging.warning("No compatible macOS assets found")

        # For Intel Macs: use Intel only (cannot run ARM)
        elif chipset == "intel":
            if intel_assets:
                asset, version = intel_assets[0]
                logging.info(
                    "Found Intel build: %s (macOS %s)",
                    asset["name"],
                    version if version else "unversioned",
                )
                return PlatformDetector._build_asset_dict(asset)
            logging.warning("No compatible Intel macOS assets found")

        return None

    @staticmethod
    def _extract_macos_version(filename: str) -> int | None:
        """
        Extract macOS version number from filename.

        Examples:
            WhatsNowPlaying-5.1.0-macOS12-AppleSilicon.zip -> 12
            WhatsNowPlaying-5.0.0-macos10_intel.zip -> 10
            WhatsNowPlaying-4.0.0-AppleSilicon.zip -> None

        Returns:
            int version or None if not found
        """
        # Match "macOS##" or "macos##" (case insensitive)
        match = re.search(r"macos(\d+)", filename, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        return None

    @staticmethod
    def _build_asset_dict(asset: dict[str, t.Any]) -> dict[str, t.Any]:
        """Extract relevant fields from GitHub asset dict"""
        return {
            "name": asset["name"],
            "download_url": asset["browser_download_url"],
            "size": asset["size"],
            "sha256": asset.get("digest", "").replace("sha256:", ""),
        }

    @staticmethod
    def get_platform_display_string() -> str:
        """Get a human-readable string describing the user's platform"""
        info = PlatformDetector.get_platform_info()

        if info["os"] == "windows":
            return "Windows (64-bit)"

        if info["os"] == "macos":
            chipset_name = "Apple Silicon" if info["chipset"] == "arm" else "Intel"
            version = info.get("macos_version")
            if version:
                return f"macOS {version} ({chipset_name})"
            return f"macOS ({chipset_name})"

        if info["os"] == "linux":
            return "Linux (no pre-built binaries available)"

        return "Unknown platform"
