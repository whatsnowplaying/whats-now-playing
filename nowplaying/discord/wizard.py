#!/usr/bin/env python3
"""Guided setup wizard for Discord.

Launched from Discord settings. Unlike Twitch and Kick there is no OAuth
redirect to wait on -- Discord hands out a bot token in its developer portal --
so this collects values and says where to find them.
"""

# pylint: disable=too-few-public-methods

import webbrowser
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from nowplaying.wizard.finish import FinishPage

if TYPE_CHECKING:
    import nowplaying.config

_PORTAL_URL = "https://discord.com/developers/applications"

_FINISH_BODY = (
    "Bot Mode will be enabled when you save your settings.\n\n"
    "Discord rate-limits presence updates, so WNP waits at least 20 seconds "
    "between them -- expect a short delay before the bot's status catches up "
    "to a new track."
)

# Exactly the permissions docs/output/discord.md asks for -- more than this and
# server owners get suspicious of a bot that only announces tracks.
_PERMISSIONS = (
    "View Channels",
    "Send Messages",
    "Embed Links",
    "Attach Files",
    "Read Message History",
)


class _AppPage(QWizardPage):
    """Collects the bot token, and the application ID for Rich Presence.

    Both live on the same two screens of the developer portal, so asking for
    them together saves a second trip.
    """

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.setTitle("Create a Discord Application")
        self.setSubTitle(
            "In the developer portal: New Application, name it (e.g. wnpbot), then "
            "Bot → Reset Token and copy the token. It is shown only once."
        )

        portal_btn = QPushButton("Open Discord Developer Portal")
        portal_btn.clicked.connect(lambda: webbrowser.open(_PORTAL_URL))

        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Bot → Reset Token")
        self.token_edit.setText(str(config.cparser.value("discord/token", defaultValue="") or ""))
        self.token_edit.textChanged.connect(self.completeChanged)

        self.clientid_edit = QLineEdit()
        self.clientid_edit.setPlaceholderText("Optional, only for Rich Presence")
        self.clientid_edit.setText(
            str(config.cparser.value("discord/clientid", defaultValue="") or "")
        )

        note = QLabel(
            "No privileged intents are required. The Application ID is on the "
            "General Information page and is only needed if you want Rich Presence "
            "on your own Discord profile."
        )
        note.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Bot Token:", self.token_edit)
        form.addRow("Application ID:", self.clientid_edit)

        layout = QVBoxLayout()
        layout.addWidget(portal_btn)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addStretch()
        self.setLayout(layout)

    def isComplete(self) -> bool:  # pylint: disable=invalid-name
        """A bot token is the one thing this wizard cannot proceed without."""
        return bool(self.token_edit.text().strip())


class _InvitePage(QWizardPage):
    """Explains how to invite the bot to a server."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Invite the Bot to Your Server")
        self.setSubTitle(
            "A token alone does nothing. The bot has to be added to a server before it can post."
        )

        permissions = "\n".join(f"    •  {name}" for name in _PERMISSIONS)
        body = QLabel(
            "In the portal, open Installation:\n\n"
            "1.  Under Installation Contexts, check only Guild Install\n"
            "2.  Under Default Install Settings → Guild Install, set Scopes to bot\n"
            "3.  Set Permissions to:\n"
            f"{permissions}\n\n"
            "4.  Open the Discord Provided Link in a browser\n"
            "5.  Click Add to Server, pick your server, and Authorize\n\n"
            "You need Manage Server permission on that server to add a bot."
        )
        body.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(body)
        layout.addStretch()
        self.setLayout(layout)


class _ChannelPage(QWizardPage):
    """Collects the optional channel ID for track announcements."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setTitle("Announce Tracks in a Channel (Optional)")
        self.setSubTitle(
            "Leave this blank to have the bot only update its own presence. Click Next to skip."
        )

        self.channel_edit = QLineEdit()
        self.channel_edit.setPlaceholderText("Right-click the channel → Copy Channel ID")
        self.channel_edit.setText(
            str(config.cparser.value("discord/channel_id", defaultValue="") or "")
        )

        note = QLabel(
            "Copy Channel ID only appears once Developer Mode is enabled in "
            "Discord's Advanced settings. The bot needs Send Messages in that "
            "channel, plus Attach Files if you want cover art included."
        )
        note.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Channel ID:", self.channel_edit)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addStretch()
        self.setLayout(layout)


class DiscordWizard(QWizard):
    """Step-by-step setup wizard for Discord bot mode."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Set Up Discord")
        self.setModal(True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)

        self._app_page = _AppPage(config)
        self._channel_page = _ChannelPage(config)

        self.addPage(self._app_page)
        self.addPage(_InvitePage())
        self.addPage(self._channel_page)
        self.addPage(FinishPage("Discord Setup Complete", _FINISH_BODY))

    def accept(self) -> None:
        """Write the collected values, then let the launching page reload them.

        Written on accept rather than per page so that cancelling halfway leaves
        the existing configuration alone.
        """
        cparser = self._config.cparser
        cparser.setValue("discord/token", self._app_page.token_edit.text().strip())
        cparser.setValue("discord/clientid", self._app_page.clientid_edit.text().strip())
        cparser.setValue("discord/channel_id", self._channel_page.channel_edit.text().strip())
        cparser.setValue("discord/bot_enabled", True)
        super().accept()
