#!/usr/bin/env python3
"""Tests for platform detection in upgrades"""

import subprocess
import sys
from unittest.mock import patch, MagicMock

import pytest

from nowplaying.upgrades.platform import (
    PlatformDetector,
    _macos_running_under_rosetta,
)


@pytest.fixture(autouse=True)
def _clear_rosetta_cache():
    """`_macos_running_under_rosetta()` uses lru_cache; clear it between
    tests so each test's subprocess.run mock actually gets invoked
    rather than the cache returning the previous test's result."""
    _macos_running_under_rosetta.cache_clear()
    yield
    _macos_running_under_rosetta.cache_clear()


def test_platform_detection_returns_valid_data():
    """platform detection returns a dict with the expected keys"""
    info = PlatformDetector.get_platform_info()
    assert "os" in info
    assert "chipset" in info
    assert "macos_version" in info
    assert info["os"] in ["windows", "macos", "linux", None]


def test_platform_display_string_is_nonempty():
    """display string is a non-empty string"""
    display = PlatformDetector.get_platform_display_string()
    assert isinstance(display, str)
    assert len(display) > 0


@pytest.mark.parametrize(
    "machine,expected_chipset,expected_display",
    [
        ("x86_64", "x86_64", "Linux (x86_64)"),
        ("aarch64", "aarch64", "Linux (aarch64)"),
        ("riscv64", "riscv64", "Linux (riscv64)"),
        ("", None, "Linux (unknown)"),
    ],
)
def test_linux_platform_detection(machine, expected_chipset, expected_display):
    """Linux platform detection maps architecture to chipset and display string"""
    with patch.object(sys, "platform", "linux"), patch("platform.machine", return_value=machine):
        info = PlatformDetector.get_platform_info()
        display = PlatformDetector.get_platform_display_string()

    assert info["os"] == "linux"
    assert info["chipset"] == expected_chipset
    assert display == expected_display


def _macos_sysctl_run_result(stdout: str = "0\n", returncode: int = 0) -> MagicMock:
    """Return a fake CompletedProcess for the sysctl.proc_translated probe."""
    fake = MagicMock(spec=subprocess.CompletedProcess)
    fake.returncode = returncode
    fake.stdout = stdout
    return fake


@pytest.mark.parametrize(
    "machine,sysctl_stdout,sysctl_returncode,"
    "expected_chipset,expected_translated,expected_display",
    [
        # Apple Silicon native: machine arm64, no translation
        ("arm64", "0\n", 0, "arm", False, "macOS 15 (Apple Silicon)"),
        # Intel native: machine x86_64, sysctl reports 0
        ("x86_64", "0\n", 0, "intel", False, "macOS 15 (Intel)"),
        # Intel binary running under Rosetta on Apple Silicon:
        # machine x86_64, sysctl reports 1.  We override chipset to "arm"
        # so the API serves the native build, and flag translated=True
        # so the display string explains the override.
        (
            "x86_64",
            "1\n",
            0,
            "arm",
            True,
            "macOS 15 (Apple Silicon (running Intel under Rosetta))",
        ),
        # sysctl returns non-zero (e.g. ENOENT on pre-Big Sur, or any
        # unknown error): treat as non-translated, keep reported chipset.
        ("x86_64", "", 1, "intel", False, "macOS 15 (Intel)"),
    ],
)
def test_macos_rosetta_detection(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    machine,
    sysctl_stdout,
    sysctl_returncode,
    expected_chipset,
    expected_translated,
    expected_display,
):
    """macOS chipset detection respects sysctl.proc_translated for Rosetta."""
    fake_run = _macos_sysctl_run_result(stdout=sysctl_stdout, returncode=sysctl_returncode)
    with (
        patch.object(sys, "platform", "darwin"),
        patch("platform.machine", return_value=machine),
        patch("platform.mac_ver", return_value=("15.0", ("", "", ""), "")),
        patch("nowplaying.upgrades.platform.subprocess.run", return_value=fake_run),
    ):
        info = PlatformDetector.get_platform_info()
        display = PlatformDetector.get_platform_display_string()

    assert info["os"] == "macos"
    assert info["chipset"] == expected_chipset
    assert info["translated"] is expected_translated
    assert info["macos_version"] == 15
    assert display == expected_display


def test_macos_rosetta_subprocess_error_returns_not_translated():
    """A subprocess.run exception during the Rosetta probe must not crash;
    the chipset falls back to whatever platform.machine() reported."""
    with (
        patch.object(sys, "platform", "darwin"),
        patch("platform.machine", return_value="x86_64"),
        patch("platform.mac_ver", return_value=("15.0", ("", "", ""), "")),
        patch(
            "nowplaying.upgrades.platform.subprocess.run",
            side_effect=OSError("sysctl not found"),
        ),
    ):
        info = PlatformDetector.get_platform_info()
    assert info["chipset"] == "intel"
    assert info["translated"] is False


# ---------------------------------------------------------------------------
# Real-runner smoke tests.  PlatformDetector is called on every upgrade
# check on every platform, so we want a mock-free assertion that
# importing + invoking it works on each runner testing.yaml schedules
# (ubuntu, windows, macos).  Each test is platform-gated; whichever
# matches the runner executes.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_real_macos_platform_detection():
    """Live PlatformDetector run on macOS.

    Validates sysctl actually exists, executes, and emits parseable
    output.  CI runners are native (no Rosetta) regardless of arm vs
    intel runner type.
    """
    info = PlatformDetector.get_platform_info()
    print(f"live macOS info: {info}")  # surfaces actual values in CI logs

    assert info["os"] == "macos"
    assert info["chipset"] in ("arm", "intel")
    assert isinstance(info["macos_version"], int)
    assert isinstance(info["translated"], bool)
    # CI runners are native, not under Rosetta — if this flips True
    # something surprising is happening with sysctl output.
    assert info["translated"] is False
    assert PlatformDetector.get_platform_display_string().startswith("macOS")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux only")
def test_real_linux_platform_detection():
    """Live PlatformDetector run on Linux."""
    info = PlatformDetector.get_platform_info()
    print(f"live Linux info: {info}")

    assert info["os"] == "linux"
    # platform.machine() returns the arch string; non-empty.
    assert info["chipset"]
    assert info["macos_version"] is None
    assert info["translated"] is False
    assert PlatformDetector.get_platform_display_string().startswith("Linux")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_real_windows_platform_detection():
    """Live PlatformDetector run on Windows.

    The current implementation doesn't probe chipset on Windows
    (the upgrade-check API treats unset chipset as "default x86_64"),
    so we just assert os + the always-False / always-None fields.
    """
    info = PlatformDetector.get_platform_info()
    print(f"live Windows info: {info}")

    assert info["os"] == "windows"
    assert info["macos_version"] is None
    assert info["translated"] is False
    assert PlatformDetector.get_platform_display_string().startswith("Windows")
