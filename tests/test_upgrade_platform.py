#!/usr/bin/env python3
"""Tests for platform detection in upgrades"""

import sys
from unittest.mock import patch

import pytest

from nowplaying.upgrades.platform import PlatformDetector


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
