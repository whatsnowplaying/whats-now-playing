#!/usr/bin/env python3
"""Platform detection for upgrades"""

import logging
import platform
import subprocess
import sys
import typing as t


def _macos_running_under_rosetta() -> bool:
    """Return True if this Intel process is being translated on Apple Silicon.

    Browsers misdetect chipset at download time often enough that Intel
    builds end up running translated on Apple Silicon hardware.  Without
    this check the upgrade-check API would treat the user as Intel
    forever — even though Rosetta runs the Intel build fine AND a
    native ARM build is available.

    macOS exposes the running process's translation state via
    `sysctl sysctl.proc_translated`:
        0      not translated (native)
        1      translated (running under Rosetta)
        ENOENT pre-Big Sur or non-macOS (treated as not translated)

    We don't ship to pre-Big Sur, so the ENOENT branch is a defensive
    catch.  We also catch subprocess failures generally — anything we
    can't determine confidently should fall back to "not translated"
    so the user stays in their installed channel rather than
    accidentally getting redirected.
    """
    try:
        result = subprocess.run(
            ["sysctl", "-n", "sysctl.proc_translated"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logging.debug("sysctl.proc_translated probe failed: %s", exc)
        return False
    if result.returncode != 0:
        return False
    return result.stdout.strip() == "1"


class PlatformDetector:
    """Detect user's platform for passing to the update check API"""

    @staticmethod
    def get_platform_info() -> dict[str, t.Any]:
        """
        Get platform information for the update check API query params.

        Returns:
            dict with keys:
                - os: "windows", "macos", or "linux"
                - chipset: "intel" or "arm" (macOS), raw arch string e.g. "x86_64" or
                  "aarch64" (Linux), or None
                - macos_version: int (e.g., 12) or None for non-macOS
                - translated: bool, True iff Intel binary running under
                  Rosetta on Apple Silicon (macOS only)
        """
        info: dict[str, t.Any] = {
            "os": None,
            "chipset": None,
            "macos_version": None,
            "translated": False,
        }

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
                # platform.machine() reports the *process* architecture, so an
                # Intel binary running under Rosetta on Apple Silicon will
                # report x86_64 even though the host CPU is ARM.  Probe the
                # translation flag and override the reported chipset so the
                # upgrade-check API offers the native ARM build instead.
                if _macos_running_under_rosetta():
                    info["chipset"] = "arm"
                    info["translated"] = True
                else:
                    info["chipset"] = "intel"
            else:
                logging.warning("Unknown macOS machine type: %s", machine)

        else:
            info["os"] = "linux"
            machine = platform.machine()  # "x86_64" or "aarch64"
            if machine:
                info["chipset"] = machine
            else:
                logging.warning("Could not detect Linux machine architecture")

        return info

    @staticmethod
    def get_platform_display_string() -> str:
        """Get a human-readable string describing the user's platform"""
        info = PlatformDetector.get_platform_info()

        if info["os"] == "windows":
            return "Windows (64-bit)"

        if info["os"] == "macos":
            chipset_name = "Apple Silicon" if info["chipset"] == "arm" else "Intel"
            if info.get("translated"):
                # Native chipset is arm but the running binary is Intel.
                # Flag this so the user understands why they're being
                # offered an Apple Silicon download.
                chipset_name = "Apple Silicon (running Intel under Rosetta)"
            version = info.get("macos_version")
            if version:
                return f"macOS {version} ({chipset_name})"
            return f"macOS ({chipset_name})"

        if info["os"] == "linux":
            arch = info.get("chipset") or "unknown"
            return f"Linux ({arch})"

        return "Unknown platform"
