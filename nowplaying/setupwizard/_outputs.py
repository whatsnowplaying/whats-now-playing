#!/usr/bin/env python3
"""Output selection page for the setup wizard."""

# pylint: disable=no-name-in-module,too-few-public-methods

from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

import nowplaying.config
from nowplaying.setupwizard._constants import PAGE_CONFIGURE_OUTPUTS, PAGE_FINISH

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
        self.setSubTitle("Others, such as Discord, may be set up in Settings.")
        self.obs_export_check: QCheckBox
        self.twitch_check: QCheckBox
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(0)

        # Whether to offer the OBS scene export after setup, not whether to run
        # the web server. The server always runs: the overlay, Twitch
        # authorization and the remote input all arrive through it.
        self.obs_export_check = QCheckBox("Set up OBS")
        self.obs_export_check.setChecked(True)
        _add_item(
            layout,
            self.obs_export_check,
            "Write an OBS scene collection with the track display already sized "
            "and positioned. Also available later from Export for OBS in the "
            "tray menu.",
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

        layout.addStretch()
        self.setLayout(layout)

    def needs_credentials(self) -> bool:
        """True when at least one credential-needing output is enabled."""
        return self.twitch_check.isChecked()

    def enabled_display_names(self) -> list[str]:
        """Return human-readable names for all enabled outputs.

        Web Overlay is unconditional because the web server always runs.
        """
        names = ["Web Overlay"]
        if self.twitch_check.isChecked():
            names.append("Twitch Bot")
        return names

    def nextId(self) -> int:  # pylint: disable=invalid-name
        """Skip the credentials page when nothing selected needs credentials."""
        if self.needs_credentials():
            return PAGE_CONFIGURE_OUTPUTS
        return PAGE_FINISH
