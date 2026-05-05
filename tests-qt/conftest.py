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
    # Snapshot Python threads and QThread instances before the test so that
    # long-lived global threads are not incorrectly flagged as leaks.
    threads_before = {t.ident for t in threading.enumerate()}
    gc.collect()
    qt_before = {id(obj) for obj in gc.get_objects() if isinstance(obj, QThread)}

    yield

    # Brief grace period for threads that are legitimately winding down.
    time.sleep(0.15)

    # Check for leaked plain Python threads.
    stray_python = [
        t
        for t in threading.enumerate()
        if t.ident not in threads_before and not t.daemon and t.is_alive()
    ]

    # Check for QThread instances created during the test that are still running.
    gc.collect()
    stray_qt = [
        obj
        for obj in gc.get_objects()
        if isinstance(obj, QThread) and obj.isRunning() and id(obj) not in qt_before
    ]

    messages = []
    if stray_python:
        reprs = [f"{t.name or '<unnamed>'}(ident={t.ident}, {repr(t)})" for t in stray_python]
        messages.append(f"stray Python thread(s): {reprs}")
    if stray_qt:
        reprs = [f"{type(obj).__name__}({repr(obj)})" for obj in stray_qt]
        messages.append(f"stray QThread(s) still running: {reprs}")

    if messages:
        pytest.fail(
            f"{request.node.nodeid} left background thread(s) running — "
            + "; ".join(messages)
            + "\nThis causes 'QThread: Destroyed while thread is still running' "
            "crashes in subsequent tests."
        )
