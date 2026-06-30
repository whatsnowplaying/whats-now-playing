#!/usr/bin/env python3
"""Guided OAuth authentication wizard for Twitch and Kick.

Launched automatically after first-run setup when platforms requiring OAuth
were configured, and accessible from Settings for re-authentication.
"""

import logging
import webbrowser
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QApplication,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

import nowplaying.kick.oauth2
import nowplaying.twitch.oauth2
from nowplaying.twitch.constants import (
    BROADCASTER_USERNAME_KEY,
    CHAT_USERNAME_KEY,
)

if TYPE_CHECKING:
    import nowplaying.config


class _TwitchBroadcasterPage(QWizardPage):
    """Guides the user through authorizing the broadcaster Twitch account."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

        self.setTitle("Authorize Twitch — Broadcaster Account")
        self.setSubTitle(
            "This lets WNP post track info to your chat and update your stream title. "
            "Your broadcaster and bot accounts may be in different browsers — "
            "paste this URL into whichever browser is logged in as your broadcaster."
        )

        port = config.cparser.value("weboutput/httpport", type=int, defaultValue=8899)
        has_custom_id = bool(config.cparser.value("twitchbot/clientid", defaultValue=""))
        if port == 8899 and not has_custom_id:
            app_note = "✅ Using the bundled WNP Twitch app — no Client ID or Secret required."
        else:
            app_note = (
                "ℹ️  You are not on port 8899 or have a custom Client ID configured. "
                "Make sure your Client ID and Client Secret are saved in Settings "
                "before authorizing."
            )
        self._app_note = QLabel(app_note)
        self._app_note.setWordWrap(True)

        self._copy_btn = QPushButton("Copy Broadcaster Auth URL")
        self._copy_btn.clicked.connect(self._copy_url)
        self._status = QLabel("Not yet authorized.")
        self._status.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self._app_note)
        layout.addSpacing(8)
        layout.addWidget(self._copy_btn)
        layout.addSpacing(8)
        layout.addWidget(self._status)
        layout.addStretch()
        self.setLayout(layout)

    def initializePage(self) -> None:  # pylint: disable=invalid-name
        self._poll()
        self._timer.start(1000)

    def cleanupPage(self) -> None:  # pylint: disable=invalid-name
        self._timer.stop()

    def _copy_url(self) -> None:
        try:
            oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config=self._config)
            url = oauth.get_auth_url("broadcaster")
            if url:
                QApplication.clipboard().setText(url)
                self._status.setText(
                    "URL copied to clipboard. Paste it into the browser where "
                    "your broadcaster account is logged in, then authorize WNP."
                )
            else:
                self._status.setText(
                    "Could not generate URL — check that your Client ID and "
                    "Client Secret are saved in Settings."
                )
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("authwizard: failed to generate Twitch broadcaster URL")
            self._status.setText("Error generating URL — see log for details.")

    def _poll(self) -> None:
        self._config.cparser.sync()
        if self._config.cparser.value("twitchbot/accesstoken"):
            username = str(self._config.cparser.value(BROADCASTER_USERNAME_KEY, defaultValue=""))
            label = f"✅ Authorized{' as ' + username if username else ''}."
            self._status.setText(label)
            self._timer.stop()
            self.completeChanged.emit()

    def isComplete(self) -> bool:  # pylint: disable=invalid-name
        self._config.cparser.sync()
        return bool(self._config.cparser.value("twitchbot/accesstoken"))


class _TwitchChatPage(QWizardPage):
    """Guides the user through authorizing a separate Twitch bot/chat account (optional)."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

        self.setTitle("Authorize Twitch — Bot Account (Optional)")
        self.setSubTitle(
            "If you use a separate account for chat messages, paste this URL into "
            "the browser where that bot account is logged in. "
            "Click Next to skip if your broadcaster account handles chat."
        )

        self._copy_btn = QPushButton("Copy Bot Auth URL")
        self._copy_btn.clicked.connect(self._copy_url)
        self._status = QLabel("Not yet authorized (optional — you can skip this).")
        self._status.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self._copy_btn)
        layout.addSpacing(8)
        layout.addWidget(self._status)
        layout.addStretch()
        self.setLayout(layout)

    def initializePage(self) -> None:  # pylint: disable=invalid-name
        self._poll()
        self._timer.start(1000)

    def cleanupPage(self) -> None:  # pylint: disable=invalid-name
        self._timer.stop()

    def _copy_url(self) -> None:
        try:
            oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config=self._config)
            url = oauth.get_auth_url("chat")
            if url:
                QApplication.clipboard().setText(url)
                self._status.setText(
                    "URL copied to clipboard. Paste it into the browser where "
                    "your bot account is logged in, then authorize WNP."
                )
            else:
                self._status.setText(
                    "Could not generate URL — check that your Client ID and "
                    "Client Secret are saved in Settings."
                )
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("authwizard: failed to generate Twitch chat URL")
            self._status.setText("Error generating URL — see log for details.")

    def _poll(self) -> None:
        self._config.cparser.sync()
        if self._config.cparser.value("twitchbot/chattoken"):
            username = str(self._config.cparser.value(CHAT_USERNAME_KEY, defaultValue=""))
            label = f"✅ Bot authorized{' as ' + username if username else ''}."
            self._status.setText(label)
            self._timer.stop()


class _KickPage(QWizardPage):
    """Guides the user through authorizing Kick."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

        self.setTitle("Authorize Kick")
        self.setSubTitle(
            "WNP will open your browser to authorize with Kick. "
            "Complete the login and this page will update automatically."
        )

        self._auth_btn = QPushButton("Open Browser to Authorize Kick")
        self._auth_btn.clicked.connect(self._open_browser)
        self._status = QLabel("Not yet authorized.")
        self._status.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self._auth_btn)
        layout.addSpacing(8)
        layout.addWidget(self._status)
        layout.addStretch()
        self.setLayout(layout)

    def initializePage(self) -> None:  # pylint: disable=invalid-name
        self._poll()
        self._timer.start(1000)

    def cleanupPage(self) -> None:  # pylint: disable=invalid-name
        self._timer.stop()

    def _open_browser(self) -> None:
        try:
            oauth = nowplaying.kick.oauth2.KickOAuth2(config=self._config)
            # get_auth_url() sets redirect_uri and generates PKCE in one shot;
            # open_browser_for_auth() would regenerate PKCE, causing a state mismatch.
            url = oauth.get_auth_url()
            if not url:
                self._status.setText(
                    "Could not generate auth URL — check that your Client ID and "
                    "Client Secret are saved in Settings."
                )
                return
            webbrowser.open(url)
            self._status.setText("Browser opened — complete authorization on the Kick website.")
            self._auth_btn.setEnabled(False)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("authwizard: failed to open Kick auth browser")
            self._status.setText("Error opening browser — see log for details.")

    def _poll(self) -> None:
        self._config.cparser.sync()
        if self._config.cparser.value("kick/accesstoken"):
            self._status.setText("✅ Kick authorized.")
            self._auth_btn.setEnabled(False)
            self._timer.stop()
            self.completeChanged.emit()

    def isComplete(self) -> bool:  # pylint: disable=invalid-name
        self._config.cparser.sync()
        return bool(self._config.cparser.value("kick/accesstoken"))


class _FinishPage(QWizardPage):
    """Final page confirming authentication is complete."""

    def __init__(self, platforms: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Authentication Complete")
        names = {"twitch": "Twitch", "kick": "Kick"}
        joined = " and ".join(names.get(p, p.title()) for p in platforms)
        body = QLabel(
            f"{joined} {'is' if len(platforms) == 1 else 'are'} now authorized. "
            "What's Now Playing will use these credentials when it runs.\n\n"
            "You can re-authorize at any time from Settings."
        )
        body.setWordWrap(True)
        layout = QVBoxLayout()
        layout.addWidget(body)
        layout.addStretch()
        self.setLayout(layout)


class AuthWizard(QWizard):
    """Step-by-step OAuth authorization wizard for Twitch and/or Kick.

    Pass ``platforms`` as a list containing 'twitch', 'kick', or both.
    """

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile",
        platforms: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Complete Authentication")
        self.setModal(True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)

        if "twitch" in platforms:
            self.addPage(_TwitchBroadcasterPage(config))
            self.addPage(_TwitchChatPage(config))
        if "kick" in platforms:
            self.addPage(_KickPage(config))
        self.addPage(_FinishPage(platforms))
