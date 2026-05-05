#!/usr/bin/env python3
"""pytest fixtures for Qt tests"""

import gc
import threading
import time

import pytest
from PySide6.QtCore import QThread  # pylint: disable=no-name-in-module


@pytest.fixture(autouse=True)
def detect_stray_threads(request):
    """Fail when a test leaves background threads running after it completes.

    Catches both plain Python threads (threading.enumerate) and Qt threads
    (QThread.isRunning) so that 'QThread: Destroyed while thread is still
    running' crashes in subsequent tests are surfaced at the test that caused
    the leak rather than the test that happened to be running when Qt noticed.
    """
    threads_before = {t.ident for t in threading.enumerate()}
    yield

    # Brief grace period for threads that are legitimately winding down.
    time.sleep(0.15)

    # Check for leaked plain Python threads.
    stray_python = [
        t
        for t in threading.enumerate()
        if t.ident not in threads_before and not t.daemon and t.is_alive()
    ]

    # Check for leaked QThread instances still running (catches PySide6 threads
    # whose Python wrapper may outlive the test scope).
    gc.collect()
    stray_qt = [obj for obj in gc.get_objects() if isinstance(obj, QThread) and obj.isRunning()]

    messages = []
    if stray_python:
        names = [t.name or f"<unnamed ident={t.ident}>" for t in stray_python]
        messages.append(f"stray Python thread(s): {names}")
    if stray_qt:
        names = [type(obj).__name__ for obj in stray_qt]
        messages.append(f"stray QThread(s) still running: {names}")

    if messages:
        pytest.fail(
            f"{request.node.nodeid} left background thread(s) running — "
            + "; ".join(messages)
            + "\nThis causes 'QThread: Destroyed while thread is still running' "
            "crashes in subsequent tests."
        )
