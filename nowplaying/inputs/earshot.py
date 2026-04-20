#!/usr/bin/env python3
"""EarShot input plugin"""

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget  # pylint: disable=import-error, no-name-in-module

import nowplaying.inputs.remote
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    import nowplaying.config


class Plugin(nowplaying.inputs.remote.Plugin):
    """Input plugin for EarShot — accepts only EarShot-identified tracks."""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: QWidget | None = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "EarShot"

    def get_source_agent_data(self) -> dict:
        """EarShot preserves source_agent data set by the sender."""
        return {}

    async def getplayingtrack(self) -> TrackMetadata | None:
        """Return metadata only when it originated from EarShot."""
        meta = self.metadata
        if not meta:
            return None
        agent = meta.get("source_agent_name") or ""
        if not agent.startswith("wnpearshot"):
            return None
        return meta

    def load_settingsui(self, qwidget: "QWidget"):
        """Load settings into the UI."""
        if not self.config:
            return
        qwidget.earshot_always_checkbox.setChecked(  # type: ignore[attr-defined]
            self.config.cparser.value("earshot/always_accept", type=bool, defaultValue=True)
        )

    def save_settingsui(self, qwidget: "QWidget"):
        """Save settings from the UI."""
        if not self.config:
            return
        self.config.cparser.setValue(
            "earshot/always_accept",
            qwidget.earshot_always_checkbox.isChecked(),  # type: ignore[attr-defined]
        )

    def verify_settingsui(self, qwidget: "QWidget"):
        """Nothing to verify."""

    def connect_settingsui(self, qwidget: "QWidget", uihelp):
        """No connections needed."""
        self.qwidget = qwidget
        self.uihelp = uihelp

    def desc_settingsui(self, qwidget: "QWidget"):
        """Description shown in the source list."""
        qwidget.setText(
            "EarShot identifies tracks via Shazam on vinyl, CDJs, Rekordbox, and analog mixers."
        )
