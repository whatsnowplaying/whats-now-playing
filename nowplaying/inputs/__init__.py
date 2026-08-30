#!/usr/bin/env python3
"""Input Plugin definition"""

import dataclasses

# import logging
from typing import TYPE_CHECKING

# from nowplaying.exceptions import PluginVerifyError
from nowplaying.plugin import WNPBasePlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    import nowplaying.config


@dataclasses.dataclass(frozen=True)
class Detected:
    """What an input plugin found on this machine.

    Truthy when the software is present, so `if plugin.detect():` still reads
    the way it always did.

    `settings` is what the plugin *would* configure, not what it did: nothing is
    written. Callers decide, because the policy differs -- first run fills
    blanks, Redetect overwrites, and the wizard wants to show a found path next
    to a configured one rather than silently replace it.

    Present with an empty `settings` is normal and distinct from absent. Serato
    4 derives its library path on demand and Rekordbox needs a key that cannot
    be detected, so both are findable with nothing to record.

    `fallback` marks presence that comes from a platform capability rather than
    from finding the user's music software: MPRIS2 works wherever D-Bus does and
    WinMedia wherever the winrt bindings import, on every such machine, whether
    or not anything is playing. Still worth offering, but never worth choosing
    over software that was actually found.
    """

    present: bool = False
    settings: dict[str, str] = dataclasses.field(default_factory=dict)
    fallback: bool = False

    def __bool__(self) -> bool:
        return self.present


class InputPlugin(WNPBasePlugin):
    """base class of input plugins"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype: str = "input"

    #### Additional UI method

    def desc_settingsui(self, qwidget: "QWidget") -> None:  # pylint: disable=no-self-use
        """description of this input"""
        qwidget.setText("No description available.")

    #### Autoinstallation methods ####

    def detect(self) -> Detected:  # pylint: disable=no-self-use
        """Report whether this DJ software is here, and what it would configure.

        Writes nothing: return findings in Detected.settings and let the caller
        record them, since only it knows whether to fill blanks or overwrite.
        Staying side-effect free is what lets serato3 call serato4's detect() to
        ask whether it claims the shared library.

        Never include settings/input; choosing the source is the caller's.
        """
        return Detected()

    #### Mix Mode menu item methods

    def validmixmodes(self) -> list[str]:  # pylint: disable=no-self-use
        """tell ui valid mixmodes"""
        # return ['newest', 'oldest']
        return ["newest"]

    def setmixmode(self, mixmode: str) -> str:  # pylint: disable=no-self-use, unused-argument
        """handle user switching the mix mode: TBD"""
        return "newest"

    def getmixmode(self) -> str:  # pylint: disable=no-self-use
        """return what the current mixmode is set to"""

        # mixmode may only be allowed to be in one state
        # depending upon other configuration that may be in
        # play

        return "newest"

    #### Data feed methods

    def get_source_agent_data(self) -> dict:
        """Return source agent identification data for this input plugin.

        Returns a stable machine-readable name derived from the plugin's module,
        e.g. 'virtualdj', 'traktor', 'serato'. Override in subclasses to also
        provide source_agent_version when the DJ software version can be detected.
        """
        module = type(self).__module__
        parts = module.split(".")
        name = parts[-2] if parts[-1] == "plugin" else parts[-1]
        return {"source_agent_name": name}

    async def getplayingtrack(self) -> TrackMetadata | None:
        """Get the currently playing track"""
        raise NotImplementedError

    async def getrandomtrack(self, playlist: str) -> str | None:  # pylint: disable=no-self-use, unused-argument
        """Get a file associated with a playlist, crate, whatever"""
        return None

    async def has_tracks_by_artist(self, artist_name: str) -> bool:  # pylint: disable=no-self-use, unused-argument
        """Check if DJ has any tracks by the specified artist"""
        # Default implementation - can be overridden by plugins with database access
        return False

    #### Control methods

    async def start(self) -> None:
        """any initialization before actual polling starts"""

    async def stop(self) -> None:
        """stopping either the entire program or just this
        input"""
