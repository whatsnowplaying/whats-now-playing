"""Background update pre-fetch worker.

Downloads the update archive silently in the background so the next
launch's upgrade() + run_auto_install() can skip the download step.
tufup's find_cached_target() verifies length + hash — a cache hit means
no re-download; a missing or partial file is re-downloaded from scratch.
"""

import logging
import pathlib
import time
from typing import Iterator

from PySide6.QtCore import QThread, Signal  # pylint: disable=no-name-in-module
import tufup.client

import nowplaying.upgrades
import nowplaying.upgrades.tufup_client
from nowplaying.upgrades.platform import PlatformDetector

logger = logging.getLogger(__name__)

# Chunk size used when bandwidth throttling is active.  Smaller than tufup's
# 400 KB default so the sleep granularity produces a smooth cap.
_THROTTLE_CHUNK_BYTES = 8 * 1024

# How long cleanquit() waits for the worker before terminating it (ms).
_SHUTDOWN_TIMEOUT_MS = 5_000


class _ThrottledFetcher(tufup.client.AuthRequestsFetcher):
    """RequestsFetcher that caps download speed to bandwidth_kbps KB/s.

    Calls super()._chunks() so the parent's progress hook still fires,
    then sleeps after each chunk to stay within the configured rate.
    chunk_size is reduced to 8 KB for smooth pacing at low caps.
    """

    def __init__(self, bandwidth_kbps: int) -> None:
        super().__init__()
        self._bytes_per_sec = bandwidth_kbps * 1024
        self.chunk_size = _THROTTLE_CHUNK_BYTES

    def _chunks(self, response) -> Iterator[bytes]:  # type: ignore[override]
        for chunk in super()._chunks(response):
            yield chunk
            if self._bytes_per_sec > 0 and chunk:
                time.sleep(len(chunk) / self._bytes_per_sec)


class PrefetchWorker(QThread):  # pylint: disable=too-few-public-methods
    """Check for an update via the charts API then download the archive.

    Step 1: HTTP API check (nowplaying.upgrades.check_for_update) to get
            the tufup_channel for this platform.
    Step 2: Build a tufup Client for that channel and call
            _download_updates() to cache the archive in target_dir.

    If bandwidth_kbps > 0 the download is throttled to that many KB/s by
    replacing the client's fetcher with _ThrottledFetcher before downloading.

    On the next launch upgrade() + run_auto_install() call
    download_and_apply_update(), which calls _download_updates() first.
    That inner call hits find_cached_target() — if the archive is present
    with the correct hash it is reused, so the visible download step is
    skipped and the install proceeds immediately.

    Signals:
        prefetch_complete()  — archive downloaded and cached successfully.
        prefetch_skipped(str) — no update found (normal/common case).
        prefetch_failed(str)  — unexpected error during check or download.
    """

    prefetch_complete = Signal()
    prefetch_skipped = Signal(str)
    prefetch_failed = Signal(str)

    def __init__(
        self,
        parent=None,
        *,
        install_dir: pathlib.Path,
        prefer_prerelease: bool = False,
        bandwidth_kbps: int = 0,
    ):
        super().__init__(parent)
        self.install_dir = install_dir
        self.prefer_prerelease = prefer_prerelease
        self.bandwidth_kbps = bandwidth_kbps

    def run(self) -> None:  # pylint: disable=missing-function-docstring
        try:
            platform_info = PlatformDetector.get_platform_info()
            data = nowplaying.upgrades.check_for_update(
                platform_info, prefer_prerelease=self.prefer_prerelease
            )
            if not data:
                logger.debug("prefetch: no update available")
                self.prefetch_skipped.emit("No update available.")
                return

            channel = data.get("tufup_channel")
            if not channel:
                # Common during rollout: charts API sees an update but no
                # tufup bundle exists for this platform yet.
                logger.debug("prefetch: no tufup_channel in API response")
                self.prefetch_skipped.emit("No tufup channel for this platform.")
                return

            client = nowplaying.upgrades.tufup_client.build_client(
                self.install_dir, channel=channel
            )
            if not client.check_for_updates():
                # Possible TUF/charts API propagation race — not an error.
                logger.debug("prefetch: tufup reports no update on channel %s", channel)
                self.prefetch_skipped.emit("No update available via tufup.")
                return

            if self.bandwidth_kbps > 0:
                logger.debug("prefetch: throttling to %d KB/s", self.bandwidth_kbps)
                client._fetcher = _ThrottledFetcher(self.bandwidth_kbps)  # pylint: disable=protected-access

            client._download_updates(progress_hook=None)  # pylint: disable=protected-access
            logger.info("prefetch: download complete for channel %s", channel)
            self.prefetch_complete.emit()
        except Exception as error:  # pylint: disable=broad-except
            logger.exception("prefetch: download failed")
            self.prefetch_failed.emit(str(error))
