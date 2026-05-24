#!/usr/bin/env python3
"""Tests for nowplaying.upgrades.background."""

# pylint: disable=protected-access,redefined-outer-name
from unittest import mock

import pytest

from nowplaying.upgrades import background


# ---------------------------------------------------------------------------
# _ThrottledFetcher
# ---------------------------------------------------------------------------


def test_throttled_fetcher_chunk_size():
    """chunk_size is set to _THROTTLE_CHUNK_BYTES, not tufup's 400 KB default."""
    fetcher = background._ThrottledFetcher(bandwidth_kbps=500)
    assert fetcher.chunk_size == background._THROTTLE_CHUNK_BYTES


def test_throttled_fetcher_sleeps_per_chunk():
    """_chunks() sleeps after each chunk to enforce the bandwidth cap."""
    fetcher = background._ThrottledFetcher(bandwidth_kbps=64)

    fake_response = mock.MagicMock()
    chunk = b"x" * 8192
    fake_response.iter_content.return_value = [chunk]

    with mock.patch("nowplaying.upgrades.background.time") as mock_time:
        mock_time.sleep = mock.MagicMock()
        list(fetcher._chunks(fake_response))

    mock_time.sleep.assert_called_once()
    sleep_secs = mock_time.sleep.call_args[0][0]
    expected = len(chunk) / (64 * 1024)
    assert abs(sleep_secs - expected) < 0.001


def test_throttled_fetcher_no_sleep_on_empty_chunk():
    """_chunks() does not sleep when the chunk is empty."""
    fetcher = background._ThrottledFetcher(bandwidth_kbps=64)
    fake_response = mock.MagicMock()
    fake_response.iter_content.return_value = [b""]

    with mock.patch("nowplaying.upgrades.background.time") as mock_time:
        mock_time.sleep = mock.MagicMock()
        list(fetcher._chunks(fake_response))

    mock_time.sleep.assert_not_called()


# ---------------------------------------------------------------------------
# PrefetchWorker — unit tests (no real network)
# ---------------------------------------------------------------------------


@pytest.fixture
def install_dir(tmp_path):
    """Temporary install directory for PrefetchWorker tests."""
    return tmp_path / "install"


def test_prefetch_worker_emits_skipped_when_no_api_update(qtbot, install_dir):
    """Emits prefetch_skipped (not prefetch_failed) when no update is available."""
    worker = background.PrefetchWorker(install_dir=install_dir)

    with mock.patch("nowplaying.upgrades.check_for_update", return_value=None):
        with qtbot.waitSignal(worker.prefetch_skipped, timeout=5000) as spy:
            worker.start()

    worker.wait()
    assert "No update" in spy.args[0]


def test_prefetch_worker_emits_skipped_when_no_channel(qtbot, install_dir):
    """Emits prefetch_skipped when the API response has no tufup_channel."""
    worker = background.PrefetchWorker(install_dir=install_dir)

    with mock.patch(
        "nowplaying.upgrades.check_for_update",
        return_value={"update_available": True, "latest_version": "9.9.9"},
    ):
        with qtbot.waitSignal(worker.prefetch_skipped, timeout=5000) as spy:
            worker.start()

    worker.wait()
    assert "channel" in spy.args[0].lower()


def test_prefetch_worker_emits_skipped_when_tufup_no_update(qtbot, install_dir):
    """Emits prefetch_skipped when tufup's own check finds nothing (API race)."""
    worker = background.PrefetchWorker(install_dir=install_dir)

    fake_client = mock.MagicMock()
    fake_client.check_for_updates.return_value = False

    with (
        mock.patch(
            "nowplaying.upgrades.check_for_update",
            return_value={"tufup_channel": "WhatsNowPlaying_test", "latest_version": "9.9.9"},
        ),
        mock.patch("nowplaying.upgrades.tufup_client.build_client", return_value=fake_client),
    ):
        with qtbot.waitSignal(worker.prefetch_skipped, timeout=5000) as spy:
            worker.start()

    worker.wait()
    assert spy.args[0]


def test_prefetch_worker_emits_complete_on_success(qtbot, install_dir):
    """Emits prefetch_complete after a successful download."""
    worker = background.PrefetchWorker(install_dir=install_dir)

    fake_client = mock.MagicMock()
    fake_client.check_for_updates.return_value = True

    with (
        mock.patch(
            "nowplaying.upgrades.check_for_update",
            return_value={"tufup_channel": "WhatsNowPlaying_test", "latest_version": "9.9.9"},
        ),
        mock.patch("nowplaying.upgrades.tufup_client.build_client", return_value=fake_client),
    ):
        with qtbot.waitSignal(worker.prefetch_complete, timeout=5000):
            worker.start()

    worker.wait()
    fake_client._download_updates.assert_called_once_with(progress_hook=None)


def test_prefetch_worker_emits_failed_on_exception(qtbot, install_dir):
    """Emits prefetch_failed when an unexpected exception occurs."""
    worker = background.PrefetchWorker(install_dir=install_dir)

    with mock.patch(
        "nowplaying.upgrades.check_for_update",
        side_effect=RuntimeError("network gone"),
    ):
        with qtbot.waitSignal(worker.prefetch_failed, timeout=5000) as spy:
            worker.start()

    worker.wait()
    assert "network gone" in spy.args[0]


def test_prefetch_worker_installs_throttled_fetcher(qtbot, install_dir):
    """Sets _ThrottledFetcher on the tufup client when bandwidth_kbps > 0."""
    worker = background.PrefetchWorker(install_dir=install_dir, bandwidth_kbps=256)

    fake_client = mock.MagicMock()
    fake_client.check_for_updates.return_value = True

    with (
        mock.patch(
            "nowplaying.upgrades.check_for_update",
            return_value={"tufup_channel": "WhatsNowPlaying_test", "latest_version": "9.9.9"},
        ),
        mock.patch("nowplaying.upgrades.tufup_client.build_client", return_value=fake_client),
    ):
        with qtbot.waitSignal(worker.prefetch_complete, timeout=5000):
            worker.start()

    worker.wait()
    assert isinstance(fake_client._fetcher, background._ThrottledFetcher)
    assert fake_client._fetcher._bytes_per_sec == 256 * 1024


def test_prefetch_worker_no_throttled_fetcher_when_unlimited(qtbot, install_dir):
    """Does not replace the fetcher when bandwidth_kbps is 0 (unlimited)."""
    worker = background.PrefetchWorker(install_dir=install_dir, bandwidth_kbps=0)

    fake_client = mock.MagicMock()
    fake_client.check_for_updates.return_value = True
    original_fetcher = fake_client._fetcher

    with (
        mock.patch(
            "nowplaying.upgrades.check_for_update",
            return_value={"tufup_channel": "WhatsNowPlaying_test", "latest_version": "9.9.9"},
        ),
        mock.patch("nowplaying.upgrades.tufup_client.build_client", return_value=fake_client),
    ):
        with qtbot.waitSignal(worker.prefetch_complete, timeout=5000):
            worker.start()

    worker.wait()
    assert fake_client._fetcher is original_fetcher
