#!/usr/bin/env python3
"""Output selection page for the installation wizard."""

# pylint: disable=no-name-in-module,too-few-public-methods

from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

import nowplaying.config
from nowplaying.installwizard._constants import PAGE_CONFIGURE_OUTPUTS, PAGE_FINISH

_ITEM_SPACING = 6


def _add_item(layout: QVBoxLayout, check: QCheckBox, description: str) -> None:
    """Add a checkbox + indented description label directly to layout."""
    layout.addWidget(check)
    desc = QLabel(description)
    desc.setWordWrap(True)
    desc.setIndent(20)
    small_font = desc.font()
    small_font.setPointSize(small_font.pointSize() - 1)
    desc.setFont(small_font)
    layout.addWidget(desc)
    layout.addSpacing(_ITEM_SPACING)


class _OutputsPage(QWizardPage):
    """Select which output integrations to enable."""

    def __init__(
        self, config: nowplaying.config.ConfigFile, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.setTitle("Output Destinations")
        self.setSubTitle(
            "Choose where What's Now Playing should send track information. "
            "All outputs can be enabled and configured later via Settings."
        )
        self.weboverlay_check: QCheckBox
        self.obsws_check: QCheckBox
        self.twitch_check: QCheckBox
        self.kick_check: QCheckBox
        self.discord_bot_check: QCheckBox
        self.discord_rp_check: QCheckBox
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(0)

        self.weboverlay_check = QCheckBox("Web Overlay")
        self.weboverlay_check.setChecked(
            bool(self.config.cparser.value("weboutput/httpenabled", type=bool, defaultValue=True))
        )
        _add_item(
            layout,
            self.weboverlay_check,
            "Serves a browser-source page for OBS and streaming software "
            "(http://localhost:8899 by default).",
        )

        self.obsws_check = QCheckBox("OBS WebSocket")
        self.obsws_check.setChecked(
            bool(self.config.cparser.value("obsws/enabled", type=bool, defaultValue=False))
        )
        _add_item(
            layout,
            self.obsws_check,
            "Sends track data directly to OBS Studio via WebSocket. "
            "Requires OBS 28+ with the WebSocket server enabled.",
        )

        self.twitch_check = QCheckBox("Twitch Bot")
        self.twitch_check.setChecked(
            bool(self.config.cparser.value("twitchbot/enabled", type=bool, defaultValue=False))
        )
        _add_item(
            layout,
            self.twitch_check,
            "Posts now-playing announcements to your Twitch chat "
            "and optionally updates your stream title.",
        )

        self.kick_check = QCheckBox("Kick Bot")
        self.kick_check.setChecked(
            bool(self.config.cparser.value("kick/enabled", type=bool, defaultValue=False))
        )
        _add_item(
            layout,
            self.kick_check,
            "Posts now-playing announcements to your Kick chat.",
        )

        self.discord_bot_check = QCheckBox("Discord Bot")
        self.discord_bot_check.setChecked(
            bool(self.config.cparser.value("discord/bot_enabled", type=bool, defaultValue=False))
        )
        _add_item(
            layout,
            self.discord_bot_check,
            "Posts now-playing updates to a Discord channel via a bot token.",
        )

        self.discord_rp_check = QCheckBox("Discord Rich Presence")
        self.discord_rp_check.setChecked(
            bool(
                self.config.cparser.value(
                    "discord/richpresence_enabled", type=bool, defaultValue=False
                )
            )
        )
        _add_item(
            layout,
            self.discord_rp_check,
            "Shows now-playing information in your Discord profile status.",
        )

        layout.addStretch()
        self.setLayout(layout)

    def needs_credentials(self) -> bool:
        """True when at least one credential-needing output is enabled."""
        return (
            self.obsws_check.isChecked()
            or self.twitch_check.isChecked()
            or self.kick_check.isChecked()
            or self.discord_bot_check.isChecked()
            or self.discord_rp_check.isChecked()
        )

    def enabled_display_names(self) -> list[str]:
        """Return human-readable names for all enabled outputs."""
        names = []
        if self.weboverlay_check.isChecked():
            names.append("Web Overlay")
        if self.obsws_check.isChecked():
            names.append("OBS WebSocket")
        if self.twitch_check.isChecked():
            names.append("Twitch Bot")
        if self.kick_check.isChecked():
            names.append("Kick Bot")
        if self.discord_bot_check.isChecked():
            names.append("Discord Bot")
        if self.discord_rp_check.isChecked():
            names.append("Discord Rich Presence")
        return names

    def nextId(self) -> int:  # pylint: disable=invalid-name
        """Skip credentials page when only Web Overlay (no credentials) is selected."""
        if self.needs_credentials():
            return PAGE_CONFIGURE_OUTPUTS
        return PAGE_FINISH
