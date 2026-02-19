#!/usr/bin/env python3
"""test the upgrade check features"""

from unittest.mock import MagicMock, patch

import pytest

import nowplaying.upgrades
import nowplaying.version  # pylint: disable=import-error, no-name-in-module


@pytest.fixture
def update_available_response():
    """A typical update-available API response"""
    return {
        "update_available": True,
        "latest_version": "5.1.0",
        "is_prerelease": False,
        "download_page_url": (
            "https://whatsnowplaying.com/download"
            "?version=5.0.1&os=macos&chipset=arm&macos_version=15"
        ),
        "asset_name": "WhatsNowPlaying-5.1.0-macOS15-AppleSilicon.zip",
        "asset_size_bytes": 26542080,
    }


@pytest.fixture
def up_to_date_response():
    """A typical up-to-date API response"""
    return {
        "update_available": False,
        "latest_version": "5.1.0",
    }


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response"""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = data
    if status_code >= 400:
        mock.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        mock.raise_for_status.return_value = None
    return mock


def test_is_prerelease_stable():
    """stable versions are not prerelease"""
    assert not nowplaying.upgrades._is_prerelease("5.1.0")  # pylint: disable=protected-access


def test_is_prerelease_rc():
    """rc versions are prerelease"""
    assert nowplaying.upgrades._is_prerelease("5.1.0-rc1")  # pylint: disable=protected-access


def test_is_prerelease_preview():
    """preview versions are prerelease"""
    assert nowplaying.upgrades._is_prerelease("5.1.0-preview2")  # pylint: disable=protected-access


def test_is_prerelease_commitnum():
    """dev builds with commit number are prerelease"""
    assert nowplaying.upgrades._is_prerelease("5.1.0+42.gabcdef")  # pylint: disable=protected-access


def test_check_for_update_available(update_available_response):  # pylint: disable=redefined-outer-name
    """returns response dict when update is available"""
    with patch("requests.get", return_value=_mock_response(update_available_response)):
        platform_info = {"os": "macos", "chipset": "arm", "macos_version": 15}
        result = nowplaying.upgrades.check_for_update(platform_info)

    assert result is not None
    assert result["update_available"] is True
    assert result["latest_version"] == "5.1.0"
    assert result["asset_name"] == "WhatsNowPlaying-5.1.0-macOS15-AppleSilicon.zip"
    assert result["asset_size_bytes"] == 26542080
    assert "download_page_url" in result


def test_check_for_update_up_to_date(up_to_date_response):  # pylint: disable=redefined-outer-name
    """returns None when already up to date"""
    with patch("requests.get", return_value=_mock_response(up_to_date_response)):
        platform_info = {"os": "macos", "chipset": "arm", "macos_version": 15}
        result = nowplaying.upgrades.check_for_update(platform_info)

    assert result is None


def test_check_for_update_api_error():
    """returns None on HTTP error"""
    with patch("requests.get", return_value=_mock_response({}, status_code=500)):
        platform_info = {"os": "macos", "chipset": "arm", "macos_version": 15}
        result = nowplaying.upgrades.check_for_update(platform_info)

    assert result is None


def test_check_for_update_network_failure():
    """returns None on network failure"""
    with patch("requests.get", side_effect=ConnectionError("network down")):
        platform_info = {"os": "macos", "chipset": "arm", "macos_version": 15}
        result = nowplaying.upgrades.check_for_update(platform_info)

    assert result is None


@pytest.mark.parametrize(
    "platform_info,expected_params",
    [
        (
            {"os": "macos", "chipset": "arm", "macos_version": 15},
            {"os": "macos", "chipset": "arm", "macos_version": 15},
        ),
        (
            {"os": "macos", "chipset": "intel", "macos_version": 13},
            {"os": "macos", "chipset": "intel", "macos_version": 13},
        ),
        (
            {"os": "windows", "chipset": None, "macos_version": None},
            {"os": "windows"},
        ),
    ],
)
def test_check_for_update_sends_correct_params(
    up_to_date_response, platform_info, expected_params
):  # pylint: disable=redefined-outer-name
    """correct query params are sent for each platform"""
    with patch("requests.get", return_value=_mock_response(up_to_date_response)) as mock_get:
        nowplaying.upgrades.check_for_update(platform_info)
        _, kwargs = mock_get.call_args
        sent_params = kwargs.get("params", {})

    for key, value in expected_params.items():
        assert sent_params.get(key) == value
    if "chipset" not in expected_params:
        assert "chipset" not in sent_params
    if "macos_version" not in expected_params:
        assert "macos_version" not in sent_params


def test_check_for_update_prerelease_sends_track_param(monkeypatch, up_to_date_response):  # pylint: disable=redefined-outer-name
    """prerelease builds send track=prerelease and the correct version"""
    monkeypatch.setattr(nowplaying.version, "__VERSION__", "5.1.0-rc1", raising=False)  # pylint: disable=no-member

    with patch("requests.get", return_value=_mock_response(up_to_date_response)) as mock_get:
        platform_info = {"os": "macos", "chipset": "arm", "macos_version": 15}
        nowplaying.upgrades.check_for_update(platform_info)
        _, kwargs = mock_get.call_args
        sent_params = kwargs.get("params", {})

    assert sent_params.get("version") == "5.1.0-rc1"
    assert sent_params.get("track") == "prerelease"
