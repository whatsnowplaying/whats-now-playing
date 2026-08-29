#!/usr/bin/env python3
"""Base page for OAuth steps that wait for a token to land in config.

Twitch and Kick both hand off to a browser and then have nothing to do but
watch for the token to appear. That watching -- a timer, a status line, and
telling the wizard when Next may be pressed -- was written three times; it
lives here now, and subclasses supply only what differs.
"""

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

if TYPE_CHECKING:
    import nowplaying.config

POLL_MS = 1000


class TokenPollPage(QWizardPage):
    """Offer an authorization action, then poll until its token shows up.

    Subclasses set `authorized_key` and implement `act()`. Everything else is
    optional and has a working default.
    """

    #: config key that becomes truthy once authorization succeeded
    authorized_key: str = ""
    #: optional config key holding the account name, appended to the success line
    username_key: str | None = None
    #: text on the action button
    action_text: str = "Authorize"
    #: status shown before anything has happened
    idle_text: str = "Not yet authorized."
    #: status shown once the token appears; `{who}` becomes " as <name>" or ""
    success_text: str = "✅ Authorized{who}."
    #: whether Next must wait for the token. False for genuinely optional steps.
    required: bool = True
    #: stop offering the action once it has succeeded
    disable_when_done: bool = False

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

        self.action_button = QPushButton(self.action_text)
        self.action_button.clicked.connect(self._run_action)
        self.status = QLabel(self.idle_text)
        self.status.setWordWrap(True)

        layout = QVBoxLayout()
        for widget in self.header_widgets():
            layout.addWidget(widget)
        layout.addWidget(self.action_button)
        layout.addSpacing(8)
        layout.addWidget(self.status)
        layout.addStretch()
        self.setLayout(layout)

    def header_widgets(self) -> list[QWidget]:  # pylint: disable=no-self-use
        """Widgets to place above the action button. Override to add context."""
        return []

    def act(self) -> str | None:
        """Start authorization. Return a status line, or None to leave it alone.

        Raising is fine: the caller turns it into a logged failure and a status
        the user can read, so subclasses need no error handling of their own.
        """
        raise NotImplementedError

    def _run_action(self) -> None:
        try:
            if message := self.act():
                self.status.setText(message)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("%s: authorization action failed", type(self).__name__)
            self.status.setText("Something went wrong. See the log for details.")

    def initializePage(self) -> None:  # pylint: disable=invalid-name
        """Show current state immediately, then keep watching."""
        self._poll()
        self._timer.start(POLL_MS)

    def cleanupPage(self) -> None:  # pylint: disable=invalid-name
        """Stop watching when the user navigates away."""
        self._timer.stop()

    def _is_authorized(self) -> bool:
        # Re-read from disk: the token is written by another process.
        self._config.get()
        return bool(self._config.cparser.value(self.authorized_key))

    def _poll(self) -> None:
        if not self._is_authorized():
            return
        who = ""
        if self.username_key:
            name = str(self._config.cparser.value(self.username_key, defaultValue=""))
            who = f" as {name}" if name else ""
        self.status.setText(self.success_text.format(who=who))
        if self.disable_when_done:
            self.action_button.setEnabled(False)
        self._timer.stop()
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # pylint: disable=invalid-name
        """Block Next until the token exists, unless this step is optional."""
        return self._is_authorized() if self.required else True
