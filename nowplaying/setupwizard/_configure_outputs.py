#!/usr/bin/env python3
"""Twitch setup page, reached only when Twitch was enabled on the outputs page."""

# pylint: disable=no-name-in-module,too-few-public-methods

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

import nowplaying.config
from nowplaying.twitch.constants import TWITCH_BUNDLED_APP_PORT, bundled_app_port_ok


class _ConfigureOutputsPage(QWizardPage):
    """Collect the Twitch channel, and a custom application only if one is needed."""

    def __init__(
        self,
        config: nowplaying.config.ConfigFile,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.setTitle("Set Up Twitch")
        self.setSubTitle(
            "Only your channel name is needed here. What's Now Playing will walk "
            "you through authorizing as soon as it starts."
        )

        self.twitch_channel = QLineEdit()
        self.twitch_channel.setPlaceholderText("your_channel_name")
        self.twitch_channel.setText(
            str(config.cparser.value("twitchbot/channel", defaultValue="") or "")
        )

        self.twitch_clientid = QLineEdit()
        self.twitch_clientid.setText(
            str(config.cparser.value("twitchbot/clientid", defaultValue="") or "")
        )
        self.twitch_secret = QLineEdit()
        self.twitch_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.twitch_secret.setText(
            str(config.cparser.value("twitchbot/secret", defaultValue="") or "")
        )

        # Off the bundled app's port a custom application is not optional, so the
        # fields start revealed rather than tucked behind the checkbox.
        must_supply_own = not bundled_app_port_ok(config)
        self._own_app_check = QCheckBox("I have my own Twitch application")
        self._own_app_check.setChecked(must_supply_own or bool(self.twitch_clientid.text()))
        # Locked when it is not a choice: unticking would send uses_own_app False
        # into the commit, which blanks the Client ID and guarantees auth fails.
        self._own_app_check.setEnabled(not must_supply_own)
        self._own_app_check.toggled.connect(self._update_own_app_rows)

        port = config.cparser.value(
            "weboutput/httpport", type=int, defaultValue=TWITCH_BUNDLED_APP_PORT
        )
        self._port_note = QLabel(
            f"The web server is on port {port}, not {TWITCH_BUNDLED_APP_PORT}, so the "
            "bundled WNP application cannot be used. Enter your own Client ID and Secret."
        )
        self._port_note.setWordWrap(True)
        self._port_note.setVisible(must_supply_own)

        # Qt caches isComplete() and only re-reads it on completeChanged, so
        # without these Next never enables once the fields are required.
        for edit in (self.twitch_channel, self.twitch_clientid, self.twitch_secret):
            edit.textChanged.connect(self.completeChanged)

        self._setup_ui()
        self._update_own_app_rows(self._own_app_check.isChecked())

    def _setup_ui(self) -> None:
        self._form = QFormLayout()
        self._form.addRow("Channel:", self.twitch_channel)
        self._form.addRow("Client ID:", self.twitch_clientid)
        self._form.addRow("Client Secret:", self.twitch_secret)

        stored_note = QLabel(
            "Anything you enter is stored only in your local What's Now Playing "
            "configuration on this computer."
        )
        stored_note.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addLayout(self._form)
        layout.addWidget(self._own_app_check)
        layout.addWidget(self._port_note)
        layout.addSpacing(8)
        layout.addWidget(stored_note)
        layout.addStretch()
        self.setLayout(layout)

    @property
    def uses_own_app(self) -> bool:
        """Whether the user opted to register their own Twitch application."""
        return self._own_app_check.isChecked()

    def isComplete(self) -> bool:  # pylint: disable=invalid-name
        """Require whatever Twitch cannot start without.

        A blank channel commits twitchbot/enabled=True and queues the OAuth
        prompt, so the user authorizes successfully and chat still never starts:
        chat.py logs "Twitch channel not configured" and returns False. There is
        no fallback to the broadcaster name, so the log is the only signal.

        The application fields are held to the same standard when they apply,
        since a custom application with no Client ID fails just as quietly.
        """
        if not self.twitch_channel.text().strip():
            return False
        if self.uses_own_app:
            return bool(self.twitch_clientid.text().strip() and self.twitch_secret.text().strip())
        return True

    def _update_own_app_rows(self, checked: bool) -> None:
        """Hide the application fields unless the user actually has their own."""
        self._form.setRowVisible(self.twitch_clientid, checked)
        self._form.setRowVisible(self.twitch_secret, checked)
        self.completeChanged.emit()
