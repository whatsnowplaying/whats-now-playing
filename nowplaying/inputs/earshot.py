#!/usr/bin/env python3
"""EarShot input plugin"""

import pathlib
import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget  # pylint: disable=import-error, no-name-in-module

import nowplaying.inputs.remote
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
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

    # Ships as WNPEarShot.app; the spaced name is accepted too since older
    # builds used it and the two are indistinguishable to a user.
    _APP_NAMES = ("WNPEarShot.app", "WNP EarShot.app")

    def detect(self) -> nowplaying.inputs.Detected:
        """Detect EarShot in /Applications or ~/Applications on macOS.

        Nothing to configure: EarShot pushes to the webserver, so there is no
        local path or library to find.
        """
        if sys.platform != "darwin":
            return nowplaying.inputs.Detected()
        roots = (pathlib.Path("/Applications"), pathlib.Path.home() / "Applications")
        found = any((root / name).exists() for root in roots for name in self._APP_NAMES)
        return nowplaying.inputs.Detected(found)

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

    def defaults(self, qsettings: "QSettings") -> None:
        """Set default configuration values for EarShot."""
        qsettings.setValue("earshot/always_accept", True)

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
