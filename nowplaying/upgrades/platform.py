#!/usr/bin/env python3
"""Platform detection for upgrades"""

import logging
import platform
import sys
import typing as t


class PlatformDetector:
    """Detect user's platform for passing to the update check API"""

    @staticmethod
    def get_platform_info() -> dict[str, t.Any]:
        """
        Get platform information for the update check API query params.

        Returns:
            dict with keys:
                - os: "windows", "macos", or "linux"
                - chipset: "intel", "arm", or None
                - macos_version: int (e.g., 12) or None for non-macOS
        """
        info: dict[str, t.Any] = {"os": None, "chipset": None, "macos_version": None}

        if sys.platform == "win32":
            info["os"] = "windows"

        elif sys.platform == "darwin":
            info["os"] = "macos"

            macos_version_str = platform.mac_ver()[0]  # e.g., "12.6.0"
            try:
                info["macos_version"] = int(macos_version_str.split(".")[0])
            except (ValueError, IndexError):
                logging.warning("Could not parse macOS version: %s", macos_version_str)

            machine = platform.machine()  # "arm64" or "x86_64"
            if machine == "arm64":
                info["chipset"] = "arm"
            elif machine == "x86_64":
                info["chipset"] = "intel"
            else:
                logging.warning("Unknown macOS machine type: %s", machine)

        else:
            info["os"] = "linux"

        return info

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
