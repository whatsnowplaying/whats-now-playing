#!/usr/bin/env python3
"""Tests for platform detection in upgrades"""

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
