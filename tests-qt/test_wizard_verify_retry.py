#!/usr/bin/env python3
"""Verification has to be retryable, and has to reach every path.

Polling stops for good once a plugin's start() fails, so without the slot
freeing itself a corrected key or path could never be checked. And a page that
never gets verification_module set simply never verifies, silently.
"""

import asyncio
import types

from PySide6.QtCore import QEventLoop, QTimer  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QPushButton  # pylint: disable=no-name-in-module

import nowplaying.inputs
import nowplaying.setupwizard
import nowplaying.wizard
import nowplaying.wizard.verify
from nowplaying.setupwizard._constants import PAGE_INPUT_CONFIG

# Pages made here have no parent, so without a reference Python collects them
# mid-test and takes the worker they own with it. The app does not have this
# problem: the wizard owns its pages, and done() stops every worker first.
_KEEPALIVE: list = []


def _pump(ms: int) -> None:
    """Run the event loop, so cross-thread signals actually get delivered."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _failing_module() -> types.ModuleType:
    """A plugin module whose start() raises, the case that stalled the poller."""
    module = types.ModuleType("wnp_failing_plugin")

    class _Plugin:  # pylint: disable=too-few-public-methods
        def __init__(self, config=None):
            self.config = config

        @staticmethod
        async def start():
            """Fail the way a missing database key does."""
            raise RuntimeError("no database key configured")

        @staticmethod
        async def stop():
            """Nothing was started."""

    module.Plugin = _Plugin
    return module


def _wait_for_free_slot(qtbot, page) -> None:
    """Wait for the worker to end, then for the page to release its slot.

    Two waits rather than one so a failure says which half broke: a thread that
    never ends is a different bug from one that ends without the page noticing,
    and a single condition cannot tell them apart. On the conditions rather than
    a fixed sleep because the second is a cross-thread signal.
    """
    timeout = int(nowplaying.wizard.verify.START_TIMEOUT * 1000)
    worker = page._verify_worker  # pylint: disable=protected-access
    if worker is not None:
        qtbot.waitUntil(worker.isFinished, timeout=timeout)
    qtbot.waitUntil(
        lambda: page._verify_worker is None,  # pylint: disable=protected-access
        timeout=timeout,
    )


def test_slot_frees_itself_after_a_failed_start(bootstrap, qtbot):
    """A failed start() must leave the page able to try again.

    Times out here if the slot is never freed, which would make retry
    impossible.
    """
    page = nowplaying.wizard.WizardPage()
    _KEEPALIVE.append(page)
    page.verification_module = _failing_module()

    page.start_verification(bootstrap)
    assert page._verify_worker is not None  # pylint: disable=protected-access

    _wait_for_free_slot(qtbot, page)


def test_retry_starts_a_new_worker(bootstrap, qtbot):
    """Check Again must actually re-run, not no-op on a held slot."""
    page = nowplaying.wizard.WizardPage()
    _KEEPALIVE.append(page)
    page.verification_module = _failing_module()

    page.start_verification(bootstrap)
    _wait_for_free_slot(qtbot, page)

    page.retry_verification()
    assert page._verify_worker is not None  # pylint: disable=protected-access
    _wait_for_free_slot(qtbot, page)


def test_a_check_again_button_appears_with_the_status(bootstrap, qtbot):  # pylint: disable=unused-argument
    """The retry has to be reachable without leaving the page."""
    module = bootstrap.plugins["inputs"]["nowplaying.inputs.traktor"]
    page = module.Plugin(config=bootstrap).wizardpage(config=bootstrap)
    page.on_verify_result(
        nowplaying.wizard.VerifyResult(nowplaying.wizard.VerifyStatus.WAITING, "No track yet.")
    )
    buttons = [b for b in page.findChildren(QPushButton) if b.text() == "Check Again"]
    assert buttons


def test_page_change_does_not_block_on_a_stuck_plugin(bootstrap, qtbot):  # pylint: disable=unused-argument
    """Leaving a page must not freeze the UI for the whole start() timeout.

    START_TIMEOUT is 20s; a page change waiting that long makes Next look
    broken. The worker keeps its reference when it overruns, so shutdown still
    gets a proper wait.
    """
    module = types.ModuleType("wnp_hanging_plugin")

    class _Plugin:  # pylint: disable=too-few-public-methods
        def __init__(self, config=None):
            self.config = config

        @staticmethod
        async def start():
            """Block far longer than the page-change wait allows."""
            await asyncio.sleep(30)

        @staticmethod
        async def stop():
            """Never reached."""

    module.Plugin = _Plugin

    page = nowplaying.wizard.WizardPage()
    _KEEPALIVE.append(page)
    page.verification_module = module
    page.start_verification(bootstrap)
    _pump(300)

    timer = QTimer()
    elapsed = []
    timer.timeout.connect(lambda: elapsed.append(1))
    timer.start(50)
    page.stop_verification()  # page change, not shutdown
    timer.stop()

    # 2s page-change wait, not the 20s start timeout
    assert len(elapsed) < 60, f"stop_verification blocked for roughly {len(elapsed) * 50}ms"
    page.stop_verification(shutting_down=True)


def test_display_machine_page_gets_verification(bootstrap, qtbot):  # pylint: disable=unused-argument
    """The Remote page on a display machine must verify like every other source."""
    wizard = nowplaying.setupwizard.SetupWizard(bootstrap)
    role_page = wizard._multipc_role_page  # pylint: disable=protected-access
    role_page._display.setChecked(True)  # pylint: disable=protected-access
    assert role_page.validatePage()

    page = wizard.page(PAGE_INPUT_CONFIG)
    assert page is not None, "remote page was not registered for the display role"
    assert page.verification_module is not None, (
        "display machine page has no verification_module, so it never verifies"
    )


def test_a_plugin_that_cannot_work_says_so_instead_of_no_track_yet():
    """Its own message reaches the user, rather than being inferred from silence."""
    status = nowplaying.inputs.InputStatus(
        health=nowplaying.inputs.InputHealth.NEEDS_USER,
        message="Rekordbox key does not open the database.",
        detail="file is not a database",
    )
    result = nowplaying.wizard.verify._from_status(status)  # pylint: disable=protected-access
    assert result is not None
    assert result.status is nowplaying.wizard.verify.VerifyStatus.FAILED
    assert result.message == "Rekordbox key does not open the database."
    assert result.detail == "file is not a database"


def test_healthy_and_waiting_plugins_keep_being_polled():
    """WAITING is the plugin handling something, not a verdict to report."""
    for health in (
        nowplaying.inputs.InputHealth.OK,
        nowplaying.inputs.InputHealth.STARTING,
        nowplaying.inputs.InputHealth.WAITING,
    ):
        status = nowplaying.inputs.InputStatus(health=health, message="hold on")
        assert (
            nowplaying.wizard.verify._from_status(status) is None  # pylint: disable=protected-access
        ), f"{health.name} should keep polling"


def test_waiting_message_replaces_the_generic_label():
    """A stalled source explains itself instead of looking unplayed."""
    stalled = nowplaying.wizard.verify._classify(None, waiting="Port 8000 is in use.")  # pylint: disable=protected-access
    assert stalled.status is nowplaying.wizard.verify.VerifyStatus.WAITING
    assert stalled.message == "Port 8000 is in use."

    quiet = nowplaying.wizard.verify._classify(None)  # pylint: disable=protected-access
    assert quiet.message == "No track yet."


def test_a_track_beats_any_waiting_message():
    """Something playing is the answer the page is waiting for."""
    result = nowplaying.wizard.verify._classify(  # pylint: disable=protected-access
        {"artist": "Wire", "title": "The 15th"}, waiting="Port 8000 is in use."
    )
    assert result.status is nowplaying.wizard.verify.VerifyStatus.OK
    assert "Wire" in result.message and "The 15th" in result.message
