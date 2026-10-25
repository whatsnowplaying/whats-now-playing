#!/usr/bin/env python3
"""Anonymous feedback dialog."""

import logging
from typing import TYPE_CHECKING

# pylint: disable=no-name-in-module
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import nowplaying.utils.charts_api

if TYPE_CHECKING:
    import nowplaying.config

DISCORD_URL = "https://discord.gg/bGdgm64Erb"

RESULT_MESSAGES: dict[str, str] = {
    "rate_limited": "Feedback can't be accepted right now. Please try again later.",
    "rejected": "The feedback server rejected this message.",
    "network_error": "Could not reach the feedback server. "
    "Check your internet connection and try again.",
    "server_error": "The feedback server had a problem. Please try again later.",
    "invalid": f"Feedback must be between 1 and "
    f"{nowplaying.utils.charts_api.FEEDBACK_MAX_LENGTH} characters.",
}


class FeedbackThread(QThread):  # pylint: disable=too-few-public-methods
    """Submit feedback off the UI thread."""

    result = Signal(str, str)  # status, detail ("" if none)

    def __init__(self, base_url: str, text: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.base_url = base_url
        self.text = text

    def run(self) -> None:
        """Send the feedback and report the status."""
        try:
            status, detail = nowplaying.utils.charts_api.submit_feedback(self.base_url, self.text)
        except Exception:  # pylint: disable=broad-except
            # A dead worker would leave the user with no answer at all.
            logging.exception("Feedback submission raised")
            status, detail = "server_error", None
        self.result.emit(status, detail or "")


class FeedbackDialog(QDialog):  # pylint: disable=too-few-public-methods
    """Collect free-form feedback and send it anonymously to the charts server."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._thread: FeedbackThread | None = None
        self._closing = False
        self.setWindowTitle("Send Feedback")
        self.resize(520, 360)

        payload = nowplaying.utils.charts_api.build_feedback_payload("")
        platform = " ".join(part for part in (payload["os"], payload["chipset"]) if part)
        intro = QLabel(
            "Tell us what is working, what is not, or what you would like to see.<br><br>"
            "Feedback is anonymous: only your message, the What's Now Playing version "
            f"({payload['version']}) and your OS ({platform or 'unknown'}) are sent. "
            "Because of that we cannot reply. If you want an answer, ask on "
            f"<a href='{DISCORD_URL}'>Discord</a> instead."
        )
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Your feedback")
        self.text_edit.textChanged.connect(self._on_text_changed)

        self.count_label = QLabel()

        self.button_box = QDialogButtonBox()
        self.send_button: QPushButton = self.button_box.addButton(
            "Send", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._send)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.text_edit)
        layout.addWidget(self.count_label)
        layout.addWidget(self.button_box)

        self._on_text_changed()

    def _length(self) -> int:
        # Code points of the stripped text, as the server counts.
        return len(self.text_edit.toPlainText().strip())

    def _on_text_changed(self) -> None:
        length = self._length()
        limit = nowplaying.utils.charts_api.FEEDBACK_MAX_LENGTH
        self.count_label.setText(f"{length} / {limit}")
        self.count_label.setStyleSheet("color: red;" if length > limit else "")
        self._update_send_enabled()

    def _update_send_enabled(self) -> None:
        sending = self._thread is not None
        length = self._length()
        self.send_button.setEnabled(
            not sending and 0 < length <= nowplaying.utils.charts_api.FEEDBACK_MAX_LENGTH
        )

    def _send(self) -> None:
        if not self.send_button.isEnabled():  # sending, empty or over the limit
            return
        text = self.text_edit.toPlainText()
        # QSettings is read here, on the UI thread, not in the worker.
        base_url = nowplaying.utils.charts_api.get_charts_base_url(self.config)
        self._thread = FeedbackThread(base_url, text, parent=self)
        self._thread.result.connect(self._on_result)
        self._thread.finished.connect(self._on_thread_finished)
        self._update_send_enabled()
        self.text_edit.setReadOnly(True)
        self._thread.start()

    def stop_sending(self, timeout_ms: int) -> None:
        """Wait for an in-flight send at shutdown so its QThread is not
        destroyed while running; the result is dropped."""
        self._closing = True  # disconnect does not cancel an already-queued result
        thread = self._thread
        if thread is None:
            return
        thread.result.disconnect(self._on_result)
        if thread.isRunning() and not thread.wait(timeout_ms):
            logging.warning("Feedback send still running at shutdown; terminating")
            thread.terminate()
            thread.wait()

    def _on_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self.text_edit.setReadOnly(False)
        self._update_send_enabled()

    def _on_result(self, status: str, detail: str) -> None:
        if self._closing:
            return
        if status == "success":
            self._show_message(
                QMessageBox.Icon.Information, "Feedback Sent", "Thanks for the feedback!"
            )
            self.text_edit.clear()
            self.accept()
            return
        message = RESULT_MESSAGES.get(status, RESULT_MESSAGES["server_error"])
        # 429 covers both per-client and server-wide limits; the detail could
        # contradict the neutral message.
        if detail and status != "rate_limited":
            message = f"{message}\n\n{detail}"
        logging.debug("feedback not sent: %s", status)
        self._show_message(QMessageBox.Icon.Warning, "Feedback Not Sent", message)

    def _show_message(self, icon: QMessageBox.Icon, title: str, text: str) -> None:
        box = QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, self)
        box.setTextFormat(Qt.TextFormat.PlainText)  # may carry the server's error text
        box.exec()
