#!/usr/bin/env python3
"""test the anonymous feedback dialog"""
# pylint: disable=redefined-outer-name,protected-access

import threading
import time
import unittest.mock

import pytest

import nowplaying.feedback
import nowplaying.utils.charts_api

LIMIT = nowplaying.utils.charts_api.FEEDBACK_MAX_LENGTH


@pytest.fixture
def dialog(bootstrap, qtbot):
    """a feedback dialog with message boxes captured instead of shown"""
    dlg = nowplaying.feedback.FeedbackDialog(config=bootstrap)
    qtbot.addWidget(dlg)
    dlg.shown_messages = []
    dlg._show_message = lambda icon, title, text: dlg.shown_messages.append((title, text))
    return dlg


def _wait_for_send(qtbot, dlg) -> None:
    qtbot.waitUntil(lambda: dlg._thread is None, timeout=5000)


@pytest.mark.parametrize(
    "text,enabled",
    [("", False), ("   \n\t", False), ("hello", True), ("  hi  ", True)],
)
def test_send_enabled_only_with_text(dialog, text, enabled):
    """Send is disabled for empty or whitespace-only text."""
    dialog.text_edit.setPlainText(text)
    assert dialog.send_button.isEnabled() is enabled


def test_send_disabled_when_opened(dialog):
    """A fresh dialog has nothing to send."""
    assert not dialog.send_button.isEnabled()
    assert dialog.count_label.text() == f"0 / {LIMIT}"


@pytest.mark.parametrize(
    "text,count,enabled,warning",
    [
        pytest.param("x" * (LIMIT - 1), LIMIT - 1, True, False, id="under"),
        pytest.param("x" * LIMIT, LIMIT, True, False, id="at-limit"),
        pytest.param("x" * (LIMIT + 1), LIMIT + 1, False, True, id="over"),
        pytest.param(" \n" + "x" * LIMIT + "\n\t ", LIMIT, True, False, id="padded"),
        pytest.param("\U0001f600" * LIMIT, LIMIT, True, False, id="emoji-code-points"),
    ],
)
def test_limit_counts_stripped_code_points(dialog, text, count, enabled, warning):
    """The count is the stripped text in code points, as the server measures it;
    over the limit the text is kept but Send is disabled and the count warns."""
    dialog.text_edit.setPlainText(text)
    assert dialog.text_edit.toPlainText() == text
    assert dialog.count_label.text() == f"{count} / {LIMIT}"
    assert dialog.send_button.isEnabled() is enabled
    assert ("red" in dialog.count_label.styleSheet()) is warning


def test_send_reenabled_after_trimming_back_under(dialog):
    """Deleting back to the limit clears the warning and re-enables Send."""
    edit = dialog.text_edit
    edit.setPlainText("x" * (LIMIT + 1))
    assert not dialog.send_button.isEnabled()
    edit.moveCursor(edit.textCursor().MoveOperation.End)
    edit.textCursor().deletePreviousChar()
    assert dialog.count_label.text() == f"{LIMIT} / {LIMIT}"
    assert dialog.count_label.styleSheet() == ""
    assert dialog.send_button.isEnabled()


@pytest.mark.parametrize(
    "debug,url",
    [
        (False, nowplaying.utils.charts_api.PROD_BASE_URL),
        (True, nowplaying.utils.charts_api.LOCAL_BASE_URL),
    ],
)
def test_success_closes_and_clears(bootstrap, dialog, qtbot, debug, url):
    """A successful send thanks the user and resets the dialog."""
    bootstrap.cparser.setValue("charts/debug", debug)
    dialog.show()
    dialog.text_edit.setPlainText("love it")
    with unittest.mock.patch.object(
        nowplaying.utils.charts_api, "submit_feedback", return_value=("success", None)
    ) as submit:
        dialog.send_button.click()
        _wait_for_send(qtbot, dialog)
    submit.assert_called_once_with(url, "love it")
    assert dialog.shown_messages[0][0] == "Feedback Sent"
    assert not dialog.isVisible()
    assert dialog.text_edit.toPlainText() == ""


@pytest.mark.parametrize(
    "status,detail,expected",
    [
        ("rate_limited", None, "can't be accepted right now"),
        ("rejected", "text too long", "text too long"),
        ("rejected", None, "rejected"),
        ("network_error", None, "Could not reach"),
        ("server_error", None, "had a problem"),
    ],
)
def test_failure_keeps_text_for_retry(dialog, qtbot, status, detail, expected):
    """Each failure says what went wrong and leaves the text to retry with."""
    dialog.show()
    dialog.text_edit.setPlainText("love it")
    with unittest.mock.patch.object(
        nowplaying.utils.charts_api, "submit_feedback", return_value=(status, detail)
    ):
        dialog.send_button.click()
        _wait_for_send(qtbot, dialog)
    title, text = dialog.shown_messages[0]
    assert title == "Feedback Not Sent"
    assert expected in text
    assert dialog.isVisible()
    assert dialog.text_edit.toPlainText() == "love it"
    assert dialog.send_button.isEnabled()
    assert not dialog.text_edit.isReadOnly()


def test_rate_limited_omits_server_detail(dialog, qtbot):
    """429 may be per-client or server-wide, so the server's reason is not shown."""
    dialog.text_edit.setPlainText("love it")
    with unittest.mock.patch.object(
        nowplaying.utils.charts_api,
        "submit_feedback",
        return_value=("rate_limited", "too much feedback received today, try again later"),
    ):
        dialog.send_button.click()
        _wait_for_send(qtbot, dialog)
    assert dialog.shown_messages == [
        ("Feedback Not Sent", nowplaying.feedback.RESULT_MESSAGES["rate_limited"])
    ]


def test_stop_sending_waits_and_drops_result(dialog, qtbot):
    """Shutdown joins an in-flight send and does not report its result."""
    release = threading.Event()
    returned = threading.Event()

    def blocking_submit(base_url, text):  # pylint: disable=unused-argument
        release.wait(5)
        returned.set()
        return ("network_error", None)

    dialog.text_edit.setPlainText("love it")
    with unittest.mock.patch.object(
        nowplaying.utils.charts_api, "submit_feedback", side_effect=blocking_submit
    ):
        dialog.send_button.click()
        thread = dialog._thread
        assert thread.isRunning()
        threading.Timer(0.2, release.set).start()
        dialog.stop_sending(5000)
        assert returned.is_set()
        assert not thread.isRunning()
        _wait_for_send(qtbot, dialog)
    assert not dialog.shown_messages


def test_stop_sending_idle_is_noop(dialog):
    """Nothing in flight means nothing to wait for."""
    dialog.stop_sending(0)
    assert dialog._thread is None


def test_send_disabled_while_sending(dialog, qtbot):
    """The button stays disabled until the submission finishes."""
    release = threading.Event()

    def blocking_submit(base_url, text):  # pylint: disable=unused-argument
        release.wait(5)
        return ("success", None)

    dialog.text_edit.setPlainText("love it")
    with unittest.mock.patch.object(
        nowplaying.utils.charts_api, "submit_feedback", side_effect=blocking_submit
    ):
        dialog.send_button.click()
        assert not dialog.send_button.isEnabled()
        assert dialog.text_edit.isReadOnly()
        dialog.text_edit.setPlainText("edited")  # setPlainText bypasses readOnly
        assert not dialog.send_button.isEnabled()
        release.set()
        _wait_for_send(qtbot, dialog)


def test_submit_raising_still_reports(dialog, qtbot):
    """If submit_feedback ever raises, the user still gets an answer."""
    dialog.text_edit.setPlainText("love it")
    with unittest.mock.patch.object(
        nowplaying.utils.charts_api, "submit_feedback", side_effect=RecursionError("deep")
    ):
        dialog.send_button.click()
        _wait_for_send(qtbot, dialog)
    assert dialog.shown_messages[0][0] == "Feedback Not Sent"
    assert nowplaying.feedback.RESULT_MESSAGES["server_error"] in dialog.shown_messages[0][1]
    assert dialog.send_button.isEnabled()


@pytest.mark.parametrize("still_running", [True, False], ids=["running", "finished"])
def test_stop_sending_drops_queued_result(dialog, qtbot, monkeypatch, still_running):
    """A result already queued when shutdown starts is not shown, whether or
    not the worker has finished by then."""

    def run(self):
        self.result.emit("network_error", "")
        if still_running:
            time.sleep(0.3)

    monkeypatch.setattr(nowplaying.feedback.FeedbackThread, "run", run)
    dialog.text_edit.setPlainText("love it")
    dialog.send_button.click()
    thread = dialog._thread
    if still_running:
        time.sleep(0.1)  # emitted and queued; no events processed yet
        assert thread.isRunning()
    else:
        assert thread.wait(5000)
    dialog.stop_sending(5000)
    _wait_for_send(qtbot, dialog)
    qtbot.wait(50)
    assert not dialog.shown_messages
