#!/usr/bin/env python3
"""test the upgrade check features"""

from unittest.mock import MagicMock, patch

import pytest

import requests

import nowplaying.upgrades
import nowplaying.version  # pylint: disable=import-error, no-name-in-module
from nowplaying.upgrades import Version


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lesser,greater",
    [
        # major/minor/micro ordering
        ("1.0.0", "2.0.0"),
        ("1.0.0", "1.1.0"),
        ("1.0.0", "1.0.1"),
        ("5.2.0", "5.2.1"),
        ("5.1.9", "5.2.0"),
        ("4.9.9", "5.0.0"),
        # pre-release < stable (same base)
        ("5.2.1-rc1", "5.2.1"),
        ("5.2.1-preview1", "5.2.1"),
        # higher pre-release number (same type)
        ("5.2.1-rc1", "5.2.1-rc2"),
        ("5.2.1-preview1", "5.2.1-preview2"),
        # rc and preview are the same tier — number still orders them
        ("5.2.1-rc1", "5.2.1-preview2"),
        ("5.2.1-preview1", "5.2.1-rc2"),
        # stable < dev build (same base)
        ("5.2.1", "5.2.1+10.gf95bd3f6"),
        # pre-release < dev build (same base)
        ("5.2.1-rc1", "5.2.1+10.gf95bd3f6"),
        ("5.2.1-preview1", "5.2.1+10.gf95bd3f6"),
        # dev build commit count ordering
        ("5.2.1+5.gabcdef0", "5.2.1+10.gf95bd3f6"),
        # cross-version: pre of next > stable of current
        ("5.2.1", "5.2.2-preview1"),
        # cross-version: same pre number, different base
        ("5.2.1-preview1", "5.2.2-preview1"),
        # cross-version: dev build of old < pre-release of next
        ("5.2.0+10.gf95bd3f6", "5.2.1-preview1"),
        # cross-version: dev build of old < stable of next
        ("5.2.0+99.gabcdef0", "5.2.1"),
        # rc0/preview0 are valid pre-releases, lower than rc1/preview1
        ("5.2.1-rc0", "5.2.1-rc1"),
        ("5.2.1-preview0", "5.2.1-preview1"),
        # rc0/preview0 are pre-releases, lower than stable
        ("5.2.1-rc0", "5.2.1"),
        ("5.2.1-preview0", "5.2.1"),
    ],
)
def test_version_lt(lesser, greater):
    """lesser is strictly less than greater, and not the reverse"""
    assert Version(lesser) < Version(greater)
    assert Version(greater) >= Version(lesser)


@pytest.mark.parametrize(
    "left,right",
    [
        # identical stable
        ("5.2.1", "5.2.1"),
        # rc == preview at same number
        ("5.2.1-rc1", "5.2.1-preview1"),
        ("5.2.1-rc2", "5.2.1-preview2"),
        # identical dev builds
        ("5.2.1+10.gf95bd3f6", "5.2.1+10.gf95bd3f6"),
        # rc0 == preview0
        ("5.2.1-rc0", "5.2.1-preview0"),
    ],
)
def test_version_eq(left, right):
    """equal versions compare as equal and neither is less than the other"""
    assert Version(left) == Version(right)
    assert Version(left) >= Version(right)
    assert Version(right) >= Version(left)


def test_version_hash_equal_versions_same_hash():
    """equal versions must have the same hash (set/dict contract)"""
    assert hash(Version("5.2.1-rc1")) == hash(Version("5.2.1-preview1"))
    assert hash(Version("5.2.1")) == hash(Version("5.2.1"))


def test_version_hash_unequal_versions_coexist_in_set():
    """unequal versions must be distinguishable as distinct set members"""
    assert len({Version("5.2.1"), Version("5.2.1-rc1")}) == 2
    assert len({Version("5.2.1"), Version("5.2.1+10.gf95bd3f6")}) == 2


def test_version_sortable():
    """sorted() produces a consistent total ordering across all types"""
    versions = [
        "5.2.1+10.gf95bd3f6",
        "5.2.1",
        "5.2.1-preview2",
        "5.2.1-rc1",
        "5.2.0",
    ]
    result = [str(v) for v in sorted(Version(v) for v in versions)]
    assert result == [
        "5.2.0",
        "5.2.1-rc1",
        "5.2.1-preview2",
        "5.2.1",
        "5.2.1+10.gf95bd3f6",
    ]


def test_version_in_set():
    """rc and preview at the same number are deduplicated in a set"""
    s = {Version("5.2.1-rc1"), Version("5.2.1-preview1")}
    assert len(s) == 1


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
        (
            {"os": "linux", "chipset": "x86_64", "macos_version": None},
            {"os": "linux", "chipset": "x86_64"},
        ),
        (
            {"os": "linux", "chipset": "aarch64", "macos_version": None},
            {"os": "linux", "chipset": "aarch64"},
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


def test_ping_version_sends_key(bootstrap, monkeypatch):
    """ping_version sends version, os, and X-API-Key header to the update check URL"""
    monkeypatch.setattr(nowplaying.version, "__VERSION__", "5.2.0", raising=False)  # pylint: disable=no-member
    bootstrap.cparser.setValue("charts/charts_key", "testkey1234")

    with patch("requests.get") as mock_get:
        nowplaying.upgrades.ping_version(bootstrap)
        _, kwargs = mock_get.call_args
        sent_params = kwargs.get("params", {})
        sent_headers = kwargs.get("headers", {})

    assert sent_params.get("version") == "5.2.0"
    assert "os" in sent_params
    assert sent_headers.get("X-API-Key") == "testkey1234"


def test_ping_version_network_failure(bootstrap, monkeypatch):
    """ping_version silently ignores network failures but still attempts the call"""
    monkeypatch.setattr(nowplaying.version, "__VERSION__", "5.2.0", raising=False)  # pylint: disable=no-member
    bootstrap.cparser.setValue("charts/charts_key", "testkey1234")

    with patch("requests.get", side_effect=requests.RequestException("network down")) as mock_get:
        nowplaying.upgrades.ping_version(bootstrap)  # should not raise

    mock_get.assert_called_once()


def test_ping_version_no_key_skips_request(bootstrap, monkeypatch):
    """ping_version makes no request when charts key is absent"""
    monkeypatch.setattr(nowplaying.version, "__VERSION__", "5.2.0", raising=False)  # pylint: disable=no-member

    with patch("requests.get") as mock_get:
        nowplaying.upgrades.ping_version(bootstrap)

    mock_get.assert_not_called()


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


def test_check_for_update_stable_no_track_by_default(monkeypatch, up_to_date_response):  # pylint: disable=redefined-outer-name
    """stable builds with no prefer_prerelease opt-in do not send track param"""
    monkeypatch.setattr(nowplaying.version, "__VERSION__", "5.2.0", raising=False)  # pylint: disable=no-member

    with patch("requests.get", return_value=_mock_response(up_to_date_response)) as mock_get:
        platform_info = {"os": "macos", "chipset": "arm", "macos_version": 15}
        nowplaying.upgrades.check_for_update(platform_info)
        _, kwargs = mock_get.call_args
        sent_params = kwargs.get("params", {})

    assert "track" not in sent_params


def test_check_for_update_stable_with_prefer_prerelease_sends_track(
    monkeypatch, up_to_date_response
):  # pylint: disable=redefined-outer-name
    """stable users who opt into prereleases via settings get track=prerelease"""
    monkeypatch.setattr(nowplaying.version, "__VERSION__", "5.2.0", raising=False)  # pylint: disable=no-member

    with patch("requests.get", return_value=_mock_response(up_to_date_response)) as mock_get:
        platform_info = {"os": "macos", "chipset": "arm", "macos_version": 15}
        nowplaying.upgrades.check_for_update(platform_info, prefer_prerelease=True)
        _, kwargs = mock_get.call_args
        sent_params = kwargs.get("params", {})

    assert sent_params.get("track") == "prerelease"


def test_check_for_update_prerelease_running_ignores_setting(monkeypatch, up_to_date_response):  # pylint: disable=redefined-outer-name
    """already-on-prerelease users keep track=prerelease regardless of setting"""
    monkeypatch.setattr(nowplaying.version, "__VERSION__", "5.1.0-rc1", raising=False)  # pylint: disable=no-member

    with patch("requests.get", return_value=_mock_response(up_to_date_response)) as mock_get:
        platform_info = {"os": "macos", "chipset": "arm", "macos_version": 15}
        nowplaying.upgrades.check_for_update(platform_info, prefer_prerelease=False)
        _, kwargs = mock_get.call_args
        sent_params = kwargs.get("params", {})

    assert sent_params.get("track") == "prerelease"
