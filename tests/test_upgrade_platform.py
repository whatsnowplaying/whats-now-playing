#!/usr/bin/env python3
"""Tests for platform detection and asset matching in upgrades"""

import pytest

from nowplaying.upgrades.platform import PlatformDetector


def test_platform_detection_exists():
    """Test that platform detection returns valid data"""
    info = PlatformDetector.get_platform_info()
    assert "os" in info
    assert "chipset" in info
    assert "macos_version" in info
    assert info["os"] in ["windows", "macos", "linux", None]


def test_platform_display_string():
    """Test that display string is generated"""
    display = PlatformDetector.get_platform_display_string()
    assert isinstance(display, str)
    assert len(display) > 0


def test_windows_asset_matching():
    """Test Windows asset matching"""
    mock_release = {
        "assets": [
            {
                "name": "WhatsNowPlaying-5.0.0-Windows.zip",
                "browser_download_url": "https://example.com/windows.zip",
                "size": 127902140,
                "digest": "sha256:abc123",
            },
            {
                "name": "WhatsNowPlaying-5.0.0-macOS11-Intel.zip",
                "browser_download_url": "https://example.com/macos.zip",
                "size": 124212035,
                "digest": "sha256:def456",
            },
        ]
    }

    platform_info = {"os": "windows", "chipset": None, "macos_version": None}
    asset = PlatformDetector.find_best_matching_asset(mock_release, platform_info)

    assert asset is not None
    assert "Windows" in asset["name"]
    assert asset["download_url"] == "https://example.com/windows.zip"
    assert asset["size"] == 127902140
    assert asset["sha256"] == "abc123"


@pytest.mark.parametrize("macos_version", [11, 12, 13, 14, 15])
def test_macos_intel_asset_matching(macos_version):
    """Test macOS Intel asset matching across different macOS versions"""
    mock_release = {
        "assets": [
            {
                "name": "WhatsNowPlaying-5.0.0-Windows.zip",
                "browser_download_url": "https://example.com/windows.zip",
                "size": 127902140,
                "digest": "sha256:abc123",
            },
            {
                "name": "WhatsNowPlaying-5.0.0-macOS11-Intel.zip",
                "browser_download_url": "https://example.com/macos-intel.zip",
                "size": 124212035,
                "digest": "sha256:def456",
            },
            {
                "name": "WhatsNowPlaying-5.0.0-macOS12-AppleSilicon.zip",
                "browser_download_url": "https://example.com/macos-arm.zip",
                "size": 121664509,
                "digest": "sha256:ghi789",
            },
        ]
    }

    platform_info = {"os": "macos", "chipset": "intel", "macos_version": macos_version}
    asset = PlatformDetector.find_best_matching_asset(mock_release, platform_info)

    assert asset is not None
    assert "Intel" in asset["name"]
    assert asset["download_url"] == "https://example.com/macos-intel.zip"


def test_macos_arm_asset_matching_prefers_arm():
    """Test macOS ARM prefers ARM build when available"""
    mock_release = {
        "assets": [
            {
                "name": "WhatsNowPlaying-5.0.0-macOS11-Intel.zip",
                "browser_download_url": "https://example.com/macos-intel.zip",
                "size": 124212035,
                "digest": "sha256:def456",
            },
            {
                "name": "WhatsNowPlaying-5.0.0-macOS12-AppleSilicon.zip",
                "browser_download_url": "https://example.com/macos-arm.zip",
                "size": 121664509,
                "digest": "sha256:ghi789",
            },
        ]
    }

    platform_info = {"os": "macos", "chipset": "arm", "macos_version": 14}
    asset = PlatformDetector.find_best_matching_asset(mock_release, platform_info)

    assert asset is not None
    assert "AppleSilicon" in asset["name"]
    assert asset["download_url"] == "https://example.com/macos-arm.zip"


def test_macos_arm_fallback_to_intel():
    """Test macOS ARM falls back to Intel (Rosetta 2) when no ARM build"""
    mock_release = {
        "assets": [
            {
                "name": "WhatsNowPlaying-5.0.0-Windows.zip",
                "browser_download_url": "https://example.com/windows.zip",
                "size": 127902140,
                "digest": "sha256:abc123",
            },
            {
                "name": "WhatsNowPlaying-5.0.0-macOS11-Intel.zip",
                "browser_download_url": "https://example.com/macos-intel.zip",
                "size": 124212035,
                "digest": "sha256:def456",
            },
            # No ARM build in this release
        ]
    }

    platform_info = {"os": "macos", "chipset": "arm", "macos_version": 14}
    asset = PlatformDetector.find_best_matching_asset(mock_release, platform_info)

    assert asset is not None
    assert "Intel" in asset["name"]
    assert asset["download_url"] == "https://example.com/macos-intel.zip"


@pytest.mark.parametrize(
    "chipset,expected_substring",
    [
        ("intel", "_intel"),
        ("arm", "_arm"),
    ],
)
def test_old_naming_convention_compatibility(chipset, expected_substring):
    """Test that old naming convention (macos11_intel, macos12_arm) still works"""
    mock_release = {
        "assets": [
            {
                "name": "WhatsNowPlaying-5.0.0-preview6-macos11_intel.zip",
                "browser_download_url": "https://example.com/macos-intel.zip",
                "size": 124212035,
                "digest": "sha256:def456",
            },
            {
                "name": "WhatsNowPlaying-5.0.0-preview6-macos12_arm.zip",
                "browser_download_url": "https://example.com/macos-arm.zip",
                "size": 121664509,
                "digest": "sha256:ghi789",
            },
        ]
    }

    platform_info = {"os": "macos", "chipset": chipset, "macos_version": 12}
    asset = PlatformDetector.find_best_matching_asset(mock_release, platform_info)
    assert asset is not None
    assert expected_substring in asset["name"]


def test_no_matching_assets():
    """Test behavior when no matching assets are found"""
    mock_release = {
        "assets": [
            {
                "name": "source-code.tar.gz",
                "browser_download_url": "https://example.com/source.tar.gz",
                "size": 1000,
            }
        ]
    }

    platform_info = {"os": "windows", "chipset": None, "macos_version": None}
    asset = PlatformDetector.find_best_matching_asset(mock_release, platform_info)

    assert asset is None


def test_linux_returns_none():
    """Test that Linux platforms return None (no binaries available)"""
    mock_release = {
        "assets": [
            {
                "name": "WhatsNowPlaying-5.0.0-Windows.zip",
                "browser_download_url": "https://example.com/windows.zip",
                "size": 127902140,
            }
        ]
    }

    platform_info = {"os": "linux", "chipset": None, "macos_version": None}
    asset = PlatformDetector.find_best_matching_asset(mock_release, platform_info)

    assert asset is None
