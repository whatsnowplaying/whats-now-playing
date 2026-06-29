#!/usr/bin/env python3
"""Credentials configuration page for enabled outputs."""

# pylint: disable=no-name-in-module,too-few-public-methods,too-many-instance-attributes,duplicate-code

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

import nowplaying.config

if TYPE_CHECKING:
    from nowplaying.installwizard._outputs import _OutputsPage


class _ConfigureOutputsPage(QWizardPage):
    """Enter credentials for each enabled output that requires them."""

    def __init__(
        self,
        outputs_page: "_OutputsPage",
        config: nowplaying.config.ConfigFile,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._outputs_page = outputs_page
        self.config = config
        self.setTitle("Configure Outputs")
        self.setSubTitle(
            "Enter the credentials for each enabled output. "
            "Leave a field blank to configure it later in Preferences."
        )

        self.obsws_host = QLineEdit()
        self.obsws_port = QLineEdit()
        self.obsws_secret = QLineEdit()
        self.twitch_channel = QLineEdit()
        self.twitch_clientid = QLineEdit()
        self.twitch_secret = QLineEdit()
        self.kick_channel = QLineEdit()
        self.kick_clientid = QLineEdit()
        self.kick_secret = QLineEdit()
        self.discord_token = QLineEdit()

        self._obsws_group: QGroupBox
        self._twitch_group: QGroupBox
        self._kick_group: QGroupBox
        self._discord_group: QGroupBox

        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner_widget = QWidget()
        inner = QVBoxLayout()

        self._obsws_group = self._make_obsws_group()
        self._twitch_group = self._make_twitch_group()
        self._kick_group = self._make_kick_group()
        self._discord_group = self._make_discord_group()

        inner.addWidget(self._obsws_group)
        inner.addWidget(self._twitch_group)
        inner.addWidget(self._kick_group)
        inner.addWidget(self._discord_group)
        inner.addStretch()

        inner_widget.setLayout(inner)
        scroll.setWidget(inner_widget)
        outer.addWidget(scroll)
        self.setLayout(outer)

    def _make_obsws_group(self) -> QGroupBox:
        group = QGroupBox("OBS WebSocket")
        form = QFormLayout()
        self.obsws_host.setPlaceholderText("localhost")
        self.obsws_host.setText(
            str(self.config.cparser.value("obsws/host", defaultValue="localhost") or "localhost")
        )
        self.obsws_port.setPlaceholderText("4455")
        self.obsws_port.setText(
            str(self.config.cparser.value("obsws/port", type=str, defaultValue="4455") or "4455")
        )
        self.obsws_secret.setPlaceholderText("WebSocket password (if set)")
        self.obsws_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.obsws_secret.setText(
            str(self.config.cparser.value("obsws/secret", defaultValue="") or "")
        )
        form.addRow("Host:", self.obsws_host)
        form.addRow("Port:", self.obsws_port)
        form.addRow("Password:", self.obsws_secret)
        group.setLayout(form)
        return group

    def _make_twitch_group(self) -> QGroupBox:
        group = QGroupBox("Twitch Bot")
        form = QFormLayout()
        self.twitch_channel.setPlaceholderText("your_channel_name")
        self.twitch_channel.setText(
            str(self.config.cparser.value("twitchbot/channel", defaultValue="") or "")
        )
        self.twitch_clientid.setPlaceholderText("Client ID from dev.twitch.tv")
        self.twitch_clientid.setText(
            str(self.config.cparser.value("twitchbot/clientid", defaultValue="") or "")
        )
        self.twitch_secret.setPlaceholderText("Client secret")
        self.twitch_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.twitch_secret.setText(
            str(self.config.cparser.value("twitchbot/secret", defaultValue="") or "")
        )
        form.addRow("Channel:", self.twitch_channel)
        form.addRow("Client ID:", self.twitch_clientid)
        form.addRow("Client Secret:", self.twitch_secret)
        group.setLayout(form)
        return group

    def _make_kick_group(self) -> QGroupBox:
        group = QGroupBox("Kick Bot")
        form = QFormLayout()
        self.kick_channel.setPlaceholderText("your_channel_name")
        self.kick_channel.setText(
            str(self.config.cparser.value("kick/channel", defaultValue="") or "")
        )
        self.kick_clientid.setPlaceholderText("Client ID")
        self.kick_clientid.setText(
            str(self.config.cparser.value("kick/clientid", defaultValue="") or "")
        )
        self.kick_secret.setPlaceholderText("Client secret")
        self.kick_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.kick_secret.setText(
            str(self.config.cparser.value("kick/secret", defaultValue="") or "")
        )
        form.addRow("Channel:", self.kick_channel)
        form.addRow("Client ID:", self.kick_clientid)
        form.addRow("Client Secret:", self.kick_secret)
        group.setLayout(form)
        return group

    def _make_discord_group(self) -> QGroupBox:
        group = QGroupBox("Discord")
        form = QFormLayout()
        self.discord_token.setPlaceholderText("Bot token from discord.com/developers")
        self.discord_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.discord_token.setText(
            str(self.config.cparser.value("discord/token", defaultValue="") or "")
        )
        form.addRow("Bot Token:", self.discord_token)
        group.setLayout(form)
        return group

    def initializePage(self) -> None:  # pylint: disable=invalid-name
        """Show only sections for outputs the user enabled on the previous page."""
        op = self._outputs_page
        self._obsws_group.setVisible(op.obsws_check.isChecked())
        self._twitch_group.setVisible(op.twitch_check.isChecked())
        self._kick_group.setVisible(op.kick_check.isChecked())
        self._discord_group.setVisible(
            op.discord_bot_check.isChecked() or op.discord_rp_check.isChecked()
        )
