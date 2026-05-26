#!/usr/bin/env python3
"""Tests for nowplaying.upgrades.background._ThrottledFetcher.

PrefetchWorker (QThread) tests live in tests-qt/test_background_prefetch.py.
"""

# pylint: disable=protected-access
from unittest import mock

from nowplaying.upgrades import background


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
