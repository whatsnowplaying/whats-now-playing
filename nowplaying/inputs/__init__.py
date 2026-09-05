#!/usr/bin/env python3
"""Input Plugin definition"""

import dataclasses
import enum

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


class InputHealth(enum.Enum):
    """What a caller should do about an input plugin right now.

    The useful question is not whether something is wrong, it is what to do
    about it, and only the plugin knows. An exception can only say "dead",
    which is why these are separate cases rather than error subclasses.
    """

    OK = "ok"
    STARTING = "starting"
    WAITING = "waiting"
    NEEDS_USER = "needs_user"
    NEEDS_RESTART = "needs_restart"
    BROKEN = "broken"


@dataclasses.dataclass(frozen=True)
class InputStatus:
    """An input plugin's own account of how it is doing.

    `message` is shown to a person, so it says what is wrong and what would fix
    it. `detail` is for the log. A plugin reporting anything other than OK is
    expected to fill in `message`: the caller cannot write one, which is how
    verify ended up scraping exception text to find something to display.
    """

    health: InputHealth = InputHealth.OK
    message: str = ""
    detail: str = ""

    def __bool__(self) -> bool:
        """True while the plugin is worth polling."""
        return self.health in (InputHealth.OK, InputHealth.STARTING, InputHealth.WAITING)

    # Named constructors, so that `message` is required by the signature rather
    # than by the docstring above. Plain InputStatus() remains the OK case,
    # which is the only one with nothing to tell anybody.

    @classmethod
    def starting(cls, message: str, detail: str = "") -> "InputStatus":
        """Not ready yet. Being polled is what lets it finish."""
        return cls(health=InputHealth.STARTING, message=message, detail=detail)

    @classmethod
    def waiting(cls, message: str, detail: str = "") -> "InputStatus":
        """Something is missing and the plugin is dealing with it."""
        return cls(health=InputHealth.WAITING, message=message, detail=detail)

    @classmethod
    def needs_user(cls, message: str, detail: str = "") -> "InputStatus":
        """Only a person can fix this, so say what and where."""
        return cls(health=InputHealth.NEEDS_USER, message=message, detail=detail)

    @classmethod
    def needs_restart(cls, message: str, detail: str = "") -> "InputStatus":
        """A stop() and start() would clear it."""
        return cls(health=InputHealth.NEEDS_RESTART, message=message, detail=detail)

    @classmethod
    def broken(cls, message: str, detail: str = "") -> "InputStatus":
        """Nothing will change by waiting or by restarting."""
        return cls(health=InputHealth.BROKEN, message=message, detail=detail)


class InputPlugin(WNPBasePlugin):
    """base class of input plugins"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype: str = "input"

    def required_port(self) -> int | None:  # pylint: disable=no-self-use
        """The TCP port this input has to bind, or None if it binds nothing.

        Reported so the main process can check the port before starting
        trackpoll, which is where the bind actually happens. Most inputs read a
        file or a database and have no answer here.
        """
        return None

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

    def status(self) -> InputStatus:  # pylint: disable=no-self-use
        """How this plugin is doing, and what the caller should do about it.

        Called every cycle, including while the caller has stopped polling,
        which is how a plugin gets itself out of NEEDS_USER: re-read the setting
        that was wrong, and report STARTING once it looks right. Icecast already
        does this for its port, from getplayingtrack().

        Reading configuration here is expected. Opening a socket, a database or
        a file is not: a plugin that needs to check something like that does it
        on its own schedule and records the answer for status() to hand back.

        The default suits any plugin with nothing that can go wrong after it has
        started, which is most of the file watchers.
        """
        return InputStatus()

    async def start(self) -> None:
        """Get ready to be polled.

        Returns promptly, or says in its own docstring that it does not: Denon
        runs discovery and Icecast waits on a broadcaster, and callers bound
        those with a timeout.

        Does not raise for anything operational. A busy port, an unreachable
        host or a key that does not work are all reported through status(),
        because only status() can distinguish "I am retrying" from "a person
        has to fix this". Exceptions are for bugs.

        Either succeeds or leaves nothing allocated. A caller that sees start()
        fail is entitled to drop the plugin without calling stop().
        """

    async def stop(self) -> None:
        """Release whatever start() acquired.

        Safe at any point, including on a plugin that never started or whose
        start() failed part way. Callers run it on every path out, so it checks
        what it holds rather than assuming.
        """
