#!/usr/bin/env python3
"""
Cross-platform single instance enforcement using Qt's QLockFile.
Much more reliable than PID files - no race conditions, automatic cleanup.
"""

from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths  # pylint: disable=no-name-in-module

# If process dies, lock becomes stale after this many milliseconds
STALE_LOCK_TIMEOUT_MS = 30000


class AlreadyRunningError(Exception):
    """Raised when another instance is already running"""


class SingleInstance:
    """
    Cross-platform single instance lock using Qt's QLockFile.

    Benefits over PID files:
    - No PID reuse race conditions
    - Automatic cleanup on process death
    - Cross-platform consistency
    - Built into Qt (no external dependencies)
    """

    def __init__(self, app_name: str = "nowplaying"):
        # Use Qt's standard temp directory
        temp_dir = Path(QStandardPaths.standardLocations(QStandardPaths.TempLocation)[0])
        lock_path = temp_dir / f"{app_name}.lock"

        self.lock_file = QLockFile(str(lock_path))
        # If process dies, lock becomes stale after timeout
        self.lock_file.setStaleLockTime(STALE_LOCK_TIMEOUT_MS)

    def __enter__(self):
        # Try to lock immediately (0 timeout)
        if not self.lock_file.tryLock(0):
            error = self.lock_file.error()
            if error == QLockFile.LockFailedError:
                raise AlreadyRunningError("Another instance is already running")
            raise AlreadyRunningError(f"Failed to create lock file: {error}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file.isLocked():
            self.lock_file.unlock()
