#!/usr/bin/env python3
"""Guided OAuth authorization wizard for Twitch.

Launched from Twitch settings, and automatically after first-run setup when
Twitch was configured.
"""

# pylint: disable=too-few-public-methods

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QApplication,
    QLabel,
    QWidget,
    QWizard,
)

import nowplaying.twitch.oauth2
from nowplaying.twitch.constants import (
    BROADCASTER_USERNAME_KEY,
    CHAT_USERNAME_KEY,
    TWITCH_BUNDLED_APP_PORT,
    bundled_app_port_ok,
)
from nowplaying.wizard.finish import FinishPage
from nowplaying.wizard.tokenpoll import TokenPollPage

if TYPE_CHECKING:
    import nowplaying.config

_FINISH_BODY = (
    "Twitch is now authorized. What's Now Playing will use these credentials "
    "when it runs.\n\n"
    "You can re-authorize at any time from Settings."
)


class _BroadcasterPage(TokenPollPage):
    """Authorize the broadcaster account, the one that has to exist."""

    authorized_key = "twitchbot/accesstoken"
    username_key = BROADCASTER_USERNAME_KEY
    action_text = "Copy Broadcaster Auth URL"

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        # Read before super().__init__(), which calls header_widgets().
        self._has_custom_id = bool(config.cparser.value("twitchbot/clientid", defaultValue=""))
        super().__init__(config, parent)
        self.setTitle("Authorize Twitch — Broadcaster Account")
        self.setSubTitle(
            "This lets WNP post track info to your chat and update your stream title. "
            "Your broadcaster and bot accounts may be in different browsers — "
            "paste this URL into whichever browser is logged in as your broadcaster."
        )

    def header_widgets(self) -> list[QWidget]:
        """Say up front whether a Client ID is needed, since most users need none."""
        if bundled_app_port_ok(self._config) and not self._has_custom_id:
            text = "✅ Using the bundled WNP Twitch app — no Client ID or Secret required."
        else:
            text = (
                f"ℹ️  You are not on port {TWITCH_BUNDLED_APP_PORT} or have a custom "
                "Client ID configured. Make sure your Client ID and Client Secret are "
                "saved in Settings before authorizing."
            )
        note = QLabel(text)
        note.setWordWrap(True)
        return [note]

    def act(self) -> str:
        """Put the broadcaster auth URL on the clipboard."""
        oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config=self._config)
        if url := oauth.get_auth_url("broadcaster"):
            QApplication.clipboard().setText(url)
            return (
                "URL copied to clipboard. Paste it into the browser where "
                "your broadcaster account is logged in, then authorize WNP."
            )
        if self._has_custom_id:
            return (
                "Could not generate URL — check that your Client ID and "
                "Client Secret are saved in Settings."
            )
        return (
            "Could not generate URL — please try again, or check Settings "
            "if you have configured a custom Client ID."
        )


class _ChatPage(TokenPollPage):
    """Authorize a separate bot account for chat. Optional, so it never blocks."""

    authorized_key = "twitchbot/chattoken"
    username_key = CHAT_USERNAME_KEY
    action_text = "Copy Bot Auth URL"
    idle_text = "Not yet authorized (optional — you can skip this)."
    success_text = "✅ Bot authorized{who}."
    required = False

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(config, parent)
        self.setTitle("Authorize Twitch — Bot Account (Optional)")
        self.setSubTitle(
            "If you use a separate account for chat messages, paste this URL into "
            "the browser where that bot account is logged in. "
            "Click Next to skip if your broadcaster account handles chat."
        )

    def act(self) -> str:
        """Put the chat-account auth URL on the clipboard."""
        oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config=self._config)
        if url := oauth.get_auth_url("chat"):
            QApplication.clipboard().setText(url)
            return (
                "URL copied to clipboard. Paste it into the browser where "
                "your bot account is logged in, then authorize WNP."
            )
        return (
            "Could not generate URL — check that your Client ID and "
            "Client Secret are saved in Settings."
        )


class TwitchWizard(QWizard):
    """Step-by-step OAuth authorization wizard for Twitch."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Up Twitch")
        self.setModal(True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)

        self.addPage(_BroadcasterPage(config))
        self.addPage(_ChatPage(config))
        self.addPage(FinishPage("Twitch Setup Complete", _FINISH_BODY))
