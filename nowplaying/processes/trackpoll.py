#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""thread to poll music player"""

import asyncio
import contextlib
import datetime
import logging
import os
import pathlib
import signal
import socket
import sys
import threading
import time
from typing import Any

import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.guessgame
import nowplaying.datacache
import nowplaying.inputs
import nowplaying.metadata
import nowplaying.metadata.processors
import nowplaying.notifications
import nowplaying.pluginimporter
import nowplaying.trackrequests
import nowplaying.utils
import nowplaying.version  # pylint: disable=import-error,no-name-in-module
from nowplaying.types import TrackMetadata

COREMETA = ["artist", "filename", "title"]

# A plugin that asks to be restarted gets one attempt this long after asking.
# Fixed, not escalating: a plugin that keeps asking must not be able to turn
# the poll loop into a restart loop.
_RESTART_DELAY_SECONDS = 30.0

# stop() during cleanup is bounded so a plugin wedged in it cannot take the
# poll loop with it.
_STOP_TIMEOUT_SECONDS = 20.0

# No configured name to log: it runs alongside whatever the user did choose.
_EARSHOT_NAME = "EarShot secondary monitor"


def compute_final_sleep(fill_duration: float, configured_delay: float) -> float:
    """Compute grace-period sleep before checkagain.

    Gives up to configured_delay/2 of extra sleep, reduced by however much
    fill_duration exceeded configured_delay.  Ensures the total inter-track
    gap scales correctly with the user's configured delay.
    """
    return max(0.0, configured_delay / 2 - max(0.0, fill_duration - configured_delay))


class TrackPoll:  # pylint: disable=too-many-instance-attributes
    """
    Do the heavy lifting of reading from the DJ software
    """

    def __init__(
        self,
        stopevent: asyncio.Event | None = None,
        config: nowplaying.config.ConfigFile | None = None,
        testmode: bool = False,
    ):
        """Initialize core polling components only - use create_with_plugins() for full setup"""
        self.datestr = time.strftime("%Y%m%d-%H%M%S")
        self.stopevent = stopevent
        # we can't use asyncio's because it doesn't work on Windows
        _ = signal.signal(signal.SIGINT, self.forced_stop)
        if testmode and config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()
        self.currentmeta: TrackMetadata = {}
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
        self._resetcurrent()
        self.testmode = testmode

        # Core polling components
        self.input: nowplaying.inputs.InputPlugin | None = None
        self.previousinput: str | None = None
        self.inputname: str | None = None
        self._reported_health: "nowplaying.inputs.InputHealth | None" = None
        self._restart_input_at: float = 0.0
        self._input_pollable: bool = False
        self.tasks: set[asyncio.Task[Any]] = set()
        self.metadataprocessors = nowplaying.metadata.MetadataProcessors(config=self.config)

        # Plugin components - initialized separately
        self.plugins: dict = {}
        self.notification_plugins: dict = {}
        self.active_notifications: list = []
        self.trackrequests: nowplaying.trackrequests.Requests | None = None
        self.guessgame: nowplaying.guessgame.GuessGame | None = None
        self._pending_meta: TrackMetadata | None = None

        # EarShot secondary monitor (runs alongside any non-EarShot source)
        self.earshot_plugin: nowplaying.inputs.InputPlugin | None = None
        self.earshot_last_meta: TrackMetadata = {}
        self._reported_earshot_health: "nowplaying.inputs.InputHealth | None" = None
        self._restart_earshot_at: float = 0.0
        # When EarShot overrides, remember what the main source was reporting
        # so its stale data does not immediately win back.
        self.main_source_suppressed_meta: TrackMetadata = {}

    @classmethod
    def create_with_plugins(
        cls,
        stopevent: asyncio.Event | None = None,
        config: nowplaying.config.ConfigFile | None = None,
        testmode: bool = False,
    ) -> "TrackPoll":
        """Factory method to create TrackPoll with full plugin initialization"""
        instance = cls(stopevent, config, testmode)
        instance._setup_plugins()
        return instance

    def _setup_plugins(self):
        """Initialize all plugin subsystems"""
        self._setup_input_plugins()
        self._setup_trackrequests()
        self._setup_guessgame()
        self._setup_notifications()

        # Start the polling loop
        self.create_tasks()
        if not self.testmode:
            self.loop.run_forever()

    def _setup_input_plugins(self):
        """Initialize input plugins"""
        self.plugins = nowplaying.pluginimporter.import_plugins(nowplaying.inputs)

    def _setup_guessgame(self):
        """Initialize guess game system"""
        self.guessgame = nowplaying.guessgame.GuessGame(
            config=self.config, stopevent=self.stopevent
        )

    def _setup_trackrequests(self):
        """Initialize track request system"""
        self.trackrequests = nowplaying.trackrequests.Requests(
            config=self.config, stopevent=self.stopevent
        )
        self.trackrequests.clear_roulette_artist_dupes()

    def _resetcurrent(self):
        """reset the currentmeta to blank"""
        for key in COREMETA:
            self.currentmeta[f"fetched{key}"] = None

    def create_tasks(self):
        """create the asyncio tasks"""
        task = self.loop.create_task(self.run())
        task.add_done_callback(self.tasks.discard)
        self.tasks.add(task)
        if self.trackrequests:
            task = self.loop.create_task(self.trackrequests.watch_for_respin(self.stopevent))
            task.add_done_callback(self.tasks.discard)
            self.tasks.add(task)
        if self.guessgame:
            task = self.loop.create_task(self.guessgame.send_game_state_to_server())
            task.add_done_callback(self.tasks.discard)
            self.tasks.add(task)

    async def switch_input_plugin(self) -> bool:
        """Handle user switching source input while running.

        Returns True when there is something for gettrack() to do, which the
        EarShot monitor satisfies on its own. _input_pollable carries whether
        the chosen source is worth asking; every path through here has to reach
        _manage_earshot_plugin(), because EarShot accepts input regardless of
        what the chosen source is doing and nothing else stops or reads it.
        """
        configured: str | None = self.config.cparser.value("settings/input")

        if not configured:
            await self._drop_input()
        elif self.previousinput != configured:
            await self._drop_input()
            self.previousinput: str | None = configured
            await self._start_input(configured)

        self._input_pollable = bool(configured) and self._act_on_status()

        # One exit, because every path has to get here: EarShot is managed and
        # read from nowhere else, and an early return skipped it three times.
        await self._manage_earshot_plugin()
        return self._input_pollable or self.earshot_plugin is not None

    @staticmethod
    async def _stop_plugin(plugin: "nowplaying.inputs.InputPlugin", name: str | None) -> None:
        """Stop a plugin without letting it take the poll loop with it.

        Every caller is on a path that has to continue regardless: an input
        switch, a restart, or shutdown. The contract asks stop() to be safe at
        any time but says nothing about how long it may take.
        """
        logging.info("stopping %s", name)
        try:
            await asyncio.wait_for(plugin.stop(), timeout=_STOP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logging.error("%s did not stop within %ss", name, _STOP_TIMEOUT_SECONDS)
        except Exception:  # pylint: disable=broad-except
            logging.exception("error stopping %s", name)

    async def _drop_input(self) -> None:
        """Stop the current input, if any, and forget everything about it.

        The health and the restart deadline belong to the plugin going away:
        carrying either into the next one reports its first failure as old
        news, or lets it skip the wait on an already-elapsed clock.
        """
        if self.input:
            await self._stop_plugin(self.input, self.previousinput)
        self.input = None
        self.previousinput = None
        self._reported_health = None
        self._restart_input_at = 0.0

    async def _start_input(self, configured: str) -> None:
        """Build and start the configured plugin.

        Per the input contract, start() does not raise for anything operational,
        so an exception here is a defect rather than a misconfiguration. It still
        has to be survivable: stop() runs first because start() may have got as
        far as a watcher or a port.

        A failure clears self.input and sets the restart clock, so the caller
        learns about it from status() like everything else.
        """
        plugin: nowplaying.inputs.InputPlugin = self.plugins[
            f"nowplaying.inputs.{configured}"
        ].Plugin(config=self.config)
        self.input = plugin
        logging.info("Starting %s plugin", configured)
        try:
            await plugin.start()
        except Exception:  # pylint: disable=broad-except
            logging.exception("cannot start %s", configured)
            await self._stop_plugin(plugin, configured)
            self.input = None
            self._restart_input_at = time.monotonic() + _RESTART_DELAY_SECONDS
            self._reported_health = nowplaying.inputs.InputHealth.BROKEN

    def _act_on_status(self) -> bool:
        """Consult the plugin and decide whether it is worth polling.

        Only the plugin knows whether a problem is one it is handling, one a
        person has to fix, or one a restart would clear, so the decision is
        taken here rather than inferred from a poll that returned nothing.
        """
        if not self.input:
            # start() failed, which set the clock; this only runs it down.
            self._await_restart()
            return False

        status = self.input.status()
        if status.health is not self._reported_health:
            self._report_health(status)
            self._reported_health = status.health

        if status:
            self._restart_input_at = 0.0
            return True
        if status.health is nowplaying.inputs.InputHealth.NEEDS_RESTART:
            self._await_restart()
        # NEEDS_USER clears when the plugin sees its setting corrected and
        # reports STARTING. BROKEN never clears itself, so the only way out is
        # the user choosing a different input, which the previousinput check
        # above catches. Either way there is nothing to do here.
        return False

    def _await_restart(self) -> None:
        """Run the clock on a restart request, and rebuild when it runs out.

        Clearing previousinput is what causes the rebuild: the next cycle sees
        it differ from the configured input and goes through the whole
        stop-construct-start path.
        """
        now = time.monotonic()
        if not self._restart_input_at:
            self._restart_input_at = now + _RESTART_DELAY_SECONDS
        elif now >= self._restart_input_at:
            self._restart_input_at = 0.0
            self.previousinput = None

    @staticmethod
    def _report_health(status: "nowplaying.inputs.InputStatus", label: str = "input") -> None:
        """Log a health change once, at a level that matches whose problem it is."""
        health = status.health
        text = status.message or health.value
        if health is nowplaying.inputs.InputHealth.NEEDS_USER:
            logging.error("%s needs attention: %s", label, text)
        elif health is nowplaying.inputs.InputHealth.BROKEN:
            logging.error("%s has stopped working: %s", label, text)
        elif health is nowplaying.inputs.InputHealth.NEEDS_RESTART:
            logging.warning("%s asked to be restarted: %s", label, text)
        else:
            logging.debug("%s health %s: %s", label, health.value, text)

    async def _act_on_earshot_status(self) -> None:
        """Rebuild the EarShot monitor when it asks.

        It inherits remote's watcher, which dies when another observer already
        holds the same file and then stores arriving tracks where nobody reads
        them. Only NEEDS_RESTART is acted on: nothing here can clear NEEDS_USER
        or BROKEN for a monitor the user never chose.
        """
        if not self.earshot_plugin:
            return

        status = self.earshot_plugin.status()
        if status.health is not self._reported_earshot_health:
            self._report_health(status, _EARSHOT_NAME)
            self._reported_earshot_health = status.health

        if status:
            self._restart_earshot_at = 0.0
            return
        if status.health is not nowplaying.inputs.InputHealth.NEEDS_RESTART:
            return

        now = time.monotonic()
        if not self._restart_earshot_at:
            self._restart_earshot_at = now + _RESTART_DELAY_SECONDS
        elif now >= self._restart_earshot_at:
            # Dropping it is the rebuild: next cycle sees no monitor and starts one.
            await self._stop_earshot_plugin()

    async def _stop_earshot_plugin(self) -> None:
        """Stop the EarShot monitor and clear everything derived from it."""
        if self.earshot_plugin:
            await self._stop_plugin(self.earshot_plugin, _EARSHOT_NAME)
        self.earshot_plugin = None
        self.earshot_last_meta = {}
        self.main_source_suppressed_meta = {}
        self._reported_earshot_health = None
        self._restart_earshot_at = 0.0

    async def _manage_earshot_plugin(self):
        """Start, stop or restart the secondary EarShot monitor."""
        active = self.config.cparser.value("settings/input")
        always_accept = self.config.cparser.value(
            "earshot/always_accept", type=bool, defaultValue=True
        )
        earshot_key = "nowplaying.inputs.earshot"
        should_run = (
            always_accept and active not in ("earshot", "remote") and earshot_key in self.plugins
        )

        if should_run and self.earshot_plugin is None:
            logging.info("Starting %s", _EARSHOT_NAME)
            self.earshot_plugin = self.plugins[earshot_key].Plugin(config=self.config)
            self._reported_earshot_health = None
            self._restart_earshot_at = 0.0
            try:
                await self.earshot_plugin.start()
            except Exception as err:  # pylint: disable=broad-except
                logging.error("Cannot start %s: %s", _EARSHOT_NAME, err)
                self.earshot_plugin = None
        elif not should_run and self.earshot_plugin is not None:
            await self._stop_earshot_plugin()
        elif self.earshot_plugin is not None:
            await self._act_on_earshot_status()

    async def run(self):
        """track polling process"""

        threading.current_thread().name = "TrackPoll"
        socket.setdefaulttimeout(5.0)

        # Start notification plugins
        await self._start_notification_plugins()

        if not self.config.cparser.value("settings/input", defaultValue=None):
            logging.debug("Waiting for user to configure source input.")

        # sleep until we have something to do
        while (
            not nowplaying.utils.safe_stopevent_check(self.stopevent)
            and not self.config.getpause()
            and not self.config.cparser.value("settings/input", defaultValue=None)
        ):
            await asyncio.sleep(0.5)
            self.config.get()

        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(0.5)
            try:
                self.config.get()

                if not await self.switch_input_plugin():
                    continue

                await self.gettrack()
            except Exception as error:  # pylint: disable=broad-except
                logging.error("Failed attempting to get a track: %s", error, exc_info=True)
                self.previousinput = None  # force input plugin restart on next iteration

        if not self.testmode and self.config.cparser.value("setlist/enabled", type=bool):
            nowplaying.db.create_setlist(self.config)
        await self.stop()
        logging.debug("Trackpoll stopped gracefully.")

    async def stop(self):
        """stop trackpoll thread gracefully"""
        logging.debug("Stopping trackpoll")
        if self._pending_meta:
            logging.info("Flushing pending metadata on shutdown")
            if self.guessgame:
                try:
                    await self.guessgame.end_game(reason="shutdown")
                except Exception as err:  # pylint: disable=broad-except
                    logging.exception("end_game failed on shutdown: %s", err)
            await self._publish(self._pending_meta)
            self._pending_meta = None
        self.stopevent.set()
        await self._stop_earshot_plugin()
        if self.input:
            await self._stop_plugin(self.input, self.previousinput)
        self.plugins = None
        loop = asyncio.get_running_loop()
        if not self.testmode:
            loop.stop()

    def forced_stop(self, signum, frame):  # pylint: disable=unused-argument
        """caught an int signal so tell the world to stop"""
        self.stopevent.set()

    def _verify_filename(self, metadata: TrackMetadata) -> TrackMetadata:
        """verify filename actual exists and/or needs path substitution"""
        if metadata.get("filename"):
            filepath = pathlib.Path(metadata["filename"])
            if not filepath.exists():
                metadata["filename"] = nowplaying.utils.songpathsubst(
                    self.config, metadata["filename"]
                )
                filepath = pathlib.Path(metadata["filename"])
                if not filepath.exists():
                    logging.error("cannot find %s; removing from metadata", metadata["filename"])
                    del metadata["filename"]
        return metadata

    def _check_title_for_path(self, title: str | None, filename: str) -> tuple[str | None, str]:
        """if title actually contains a filename, move it to filename"""

        if not title:
            return title, filename

        if title == filename:
            return None, filename

        if ("\\" in title or "/" in title) and pathlib.Path(
            nowplaying.utils.songpathsubst(self.config, title)
        ).exists():
            if not filename:
                logging.debug("Copied title to filename")
                filename = title
            logging.debug("Wiping title because it is actually a filename")
            title = None

        return title, filename

    @staticmethod
    def _earshot_track_key(meta: TrackMetadata) -> tuple[str, str]:
        """Stable (artist, title) key for EarShot change detection."""
        return (meta.get("artist") or "", meta.get("title") or "")

    async def _check_earshot_override(
        self, main_nextmeta: TrackMetadata
    ) -> tuple[TrackMetadata, bool]:
        """Check whether a new EarShot identification should override the main source.

        Returns (metadata_to_use, earshot_overrode) where earshot_overrode is True
        when EarShot fired.  Also handles suppression of the main source's stale
        last-seen track so it does not immediately win back after an EarShot override.
        """
        if not self.earshot_plugin:
            return main_nextmeta, False

        try:
            earshot_meta = await self.earshot_plugin.getplayingtrack() or {}
        except Exception as err:  # pylint: disable=broad-except
            logging.error("EarShot secondary poll failed: %s", err)
            return main_nextmeta, False

        if earshot_meta and self._earshot_track_key(earshot_meta) != self._earshot_track_key(
            self.earshot_last_meta
        ):
            if self._earshot_track_key(earshot_meta) == self._earshot_track_key(main_nextmeta):
                logging.debug("EarShot heard the same track as main source; not overriding")
                self.earshot_last_meta = earshot_meta
            else:
                logging.info(
                    "EarShot identified new track: %s / %s",
                    earshot_meta.get("artist"),
                    earshot_meta.get("title"),
                )
                self.earshot_last_meta = earshot_meta
                self.main_source_suppressed_meta = main_nextmeta
                return earshot_meta, True

        # EarShot has not changed — suppress main source if it is still reporting
        # the same stale track it was showing when EarShot last overrode.
        # Return empty so _ismetaempty() at the call site skips the publish.
        if self.main_source_suppressed_meta and self._earshot_track_key(
            main_nextmeta
        ) == self._earshot_track_key(self.main_source_suppressed_meta):
            return {}, False

        # Main source has a genuinely new track — clear suppression.
        if self.main_source_suppressed_meta:
            logging.debug("Main source reports new track; clearing EarShot suppression")
            self.main_source_suppressed_meta = {}

        return main_nextmeta, False

    @staticmethod
    def _ismetaempty(metadata: TrackMetadata) -> bool:
        """need at least one value"""

        if not metadata:
            return True

        return not any(key in metadata and metadata[key] for key in COREMETA)

    def _ismetasame(self, metadata: TrackMetadata) -> bool:
        """same as current check"""
        if not self.currentmeta:
            return False

        for key in COREMETA:
            fetched = f"fetched{key}"
            if (
                key in metadata
                and fetched in self.currentmeta
                and metadata[key] != self.currentmeta[fetched]
            ):
                return False
        return True

    async def _maybe_flush_pending(self) -> None:
        """Publish deferred metadata if the guess game has ended.

        Called from idle gettrack cycles (same track or empty input) so that
        a solved/timed-out game flushes the deferred write without waiting for
        the next track change.
        """
        if not (self._pending_meta and self.guessgame):
            return
        try:
            await self.guessgame.check_game_timeout()
            if await self.guessgame.may_publish():
                logging.debug("Publishing deferred metadata after may_publish=True")
                await self._publish(self._pending_meta)
                self._pending_meta = None
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("Guessgame idle check failed, publishing deferred track: %s", err)
            await self._publish(self._pending_meta)
            self._pending_meta = None

    @staticmethod
    def _isignored(metadata: TrackMetadata) -> bool:
        """bail out if the text WNPIGNORE appears in the comment field"""
        if metadata.get("comments") and "WNPIGNORE" in metadata["comments"]:
            return True
        return False

    async def checkskip(self, nextmeta: TrackMetadata) -> bool:
        """check if this metadata is meant to be skipped"""
        if not nextmeta:
            return False

        for skiptype in ["comments", "genre"]:
            skipdata = self.config.cparser.value(f"trackskip/{skiptype}", defaultValue=None)
            if not skipdata:
                continue
            if skipdata in nextmeta.get(skiptype, ""):
                return True
        return False

    async def _fill_inmetadata(self, metadata: TrackMetadata) -> TrackMetadata:  # pylint: disable=too-many-branches
        """keep a copy of our fetched data"""

        # Fill in as much metadata as possible. everything
        # after this expects artist, filename, and title are expected to exist
        # so if they don't, make them at least an empty string, keeping what
        # the input actually gave as 'fetched' to compare with what
        # was given before to shortcut all of this work in the future

        if not metadata:
            return {}

        for key in COREMETA:
            fetched = f"fetched{key}"
            if key in metadata:
                if isinstance(metadata[key], str):
                    metadata[fetched] = metadata[key].strip()
                else:
                    metadata[fetched] = metadata[key]
            else:
                metadata[fetched] = None

        if metadata.get("filename"):
            metadata = self._verify_filename(metadata)

        if metadata.get("title"):
            (metadata["title"], metadata["filename"]) = self._check_title_for_path(
                metadata["title"], metadata.get("filename")
            )

        for key in COREMETA:
            if key in metadata and not metadata[key]:
                del metadata[key]

        try:
            metadata = await self.metadataprocessors.getmoremetadata(metadata=metadata)
            if duration := metadata.get("duration"):
                metadata["duration_hhmmss"] = nowplaying.utils.humanize_time(duration)
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("Ignoring metadataprocessor failure (%s).", err)

        for key in COREMETA:
            if key not in metadata:
                logging.info("Track missing %s data, setting it to blank.", key)
                metadata[key] = ""
        return metadata

    async def gettrack(  # pylint: disable=too-many-branches,too-many-statements,too-many-return-statements
        self,
    ):
        """get currently playing track, returns None if not new or not found"""

        # check paused state
        while self.config.getpause() and not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(0.5)

        if nowplaying.utils.safe_stopevent_check(self.stopevent):
            return

        nextmeta: TrackMetadata = {}
        if self._input_pollable and self.input:
            try:
                nextmeta = await self.input.getplayingtrack() or {}
                for key, value in self.input.get_source_agent_data().items():
                    if key not in nextmeta:
                        nextmeta[key] = value
            except Exception as err:  # pylint: disable=broad-except
                logging.exception("Failed during getplayingtrack() (%s)", err)
                await asyncio.sleep(1)
                return
        elif not self.earshot_plugin:
            return

        nextmeta, _ = await self._check_earshot_override(nextmeta)

        if self._ismetaempty(nextmeta) or self._isignored(nextmeta):
            # No fresh input this cycle.  If a previous track is still deferred
            # waiting on a guess game, drive the publish-permission check here
            # too — otherwise change-only sources (EarShot, Remote) leave
            # deferred metadata stuck until the next track.
            await self._maybe_flush_pending()
            return

        if self._ismetasame(nextmeta):
            # Same track still playing — use this idle cycle to check write permission.
            await self._maybe_flush_pending()
            return

        # fill in the blanks and make it live
        logging.debug(
            "raw input metadata: artist=%s title=%s filename=%s",
            nextmeta.get("artist"),
            nextmeta.get("title"),
            nextmeta.get("filename"),
        )
        oldmeta = self.currentmeta
        fill_start_time = time.time()
        try:
            self.currentmeta = await self._fill_inmetadata(nextmeta)
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("Ignoring the %s crash and just keep going!", err)
            await asyncio.sleep(1)
            self.currentmeta = nextmeta

        fill_duration = time.time() - fill_start_time
        logging.debug("_fill_inmetadata took %.3f seconds", fill_duration)

        # Set timestamp and version when track is accepted as current
        self.currentmeta["track_received"] = datetime.datetime.now(datetime.UTC).isoformat()
        self.currentmeta["version"] = nowplaying.version.__VERSION__  # pylint: disable=no-member

        logging.info(
            "Potential new track: %s / %s",
            self.currentmeta.get("artist", ""),
            self.currentmeta.get("title", ""),
        )

        if await self.checkskip(nextmeta):
            logging.info(
                "Skipping %s / %s",
                self.currentmeta.get("artist", ""),
                self.currentmeta.get("title", ""),
            )
            return

        # Get configured delay for optimization calculations
        try:
            configured_delay = self.config.cparser.value(
                "settings/delay", type=float, defaultValue=1.0
            )
        except ValueError:
            configured_delay = 1.0

        if not self.currentmeta.get("cache_warmed", False):
            # try to interleave downloads in-between the delay
            await self._half_delay_write(fill_duration)  # Use fill duration for first delay
            await self._process_artistextras()
            await self._half_delay_write()  # Normal delay for second half
            await self._process_artistextras()
            # Reduce sleep by any remaining fill duration beyond the configured delay
            await asyncio.sleep(compute_final_sleep(fill_duration, configured_delay))
        else:
            # cache was already warmed — interleave DB-only image reads with the delay
            await self._half_delay_write(fill_duration)  # Use fill duration for first delay
            await self._process_artistextras()
            await self._half_delay_write()  # Normal delay for second half
            await self._process_artistextras()

        # checkagain
        nextcheck = {}
        if self._input_pollable and self.input:
            nextcheck = await self.input.getplayingtrack() or {}
        if not self._ismetaempty(nextcheck) and not self._ismetasame(nextcheck):
            logging.info("Track changed during delay, skipping")
            self.currentmeta = oldmeta
            return

        if self.config.cparser.value("settings/requests", type=bool):
            if data := await self.trackrequests.get_request(self.currentmeta):
                self.currentmeta.update(data)

        await self._artfallbacks()

        # If a previous game was active, reveal its track before starting the new one.
        if self._pending_meta:
            if self.guessgame:
                try:
                    await self.guessgame.end_game(reason="track_change")
                except Exception as err:  # pylint: disable=broad-except
                    logging.exception("end_game failed on track change: %s", err)
            await self._publish(self._pending_meta)
            self._pending_meta = None

        # Start a new game (defers the write) or publish immediately.
        if (
            self.guessgame
            and self.guessgame.is_enabled()
            and self.currentmeta.get("artist")
            and self.currentmeta.get("title")
        ):
            try:
                if await self.guessgame.start_new_game(
                    track=self.currentmeta["title"], artist=self.currentmeta["artist"]
                ):
                    self._pending_meta = self.currentmeta.copy()
                    logging.info(
                        "Started guess game, deferring write for: %s - %s",
                        self.currentmeta.get("artist"),
                        self.currentmeta.get("title"),
                    )
                else:
                    logging.error("Failed to start guess game, publishing track immediately")
                    await self._publish(self.currentmeta)
            except Exception as err:  # pylint: disable=broad-except
                logging.exception("start_new_game raised, publishing track immediately: %s", err)
                await self._publish(self.currentmeta)
        else:
            await self._publish(self.currentmeta)

    def _setup_notifications(self):
        """Initialize notification plugins"""
        self.notification_plugins = nowplaying.pluginimporter.import_plugins(
            nowplaying.notifications
        )
        for plugin_name, plugin_class in self.notification_plugins.items():
            try:
                plugin_instance = plugin_class.Plugin(config=self.config)
                self.active_notifications.append(plugin_instance)
                logging.debug("Loaded notification plugin: %s", plugin_name)
            except Exception as err:  # pylint: disable=broad-except
                logging.error("Failed to load notification plugin %s: %s", plugin_name, err)

    async def _start_notification_plugins(self):
        """Start all notification plugins"""
        for plugin in self.active_notifications:
            plugin_name = plugin.__class__.__name__
            try:
                await plugin.start()
                logging.debug("Started notification plugin: %s", plugin_name)
            except Exception as err:  # pylint: disable=broad-except
                logging.error("Failed to start notification plugin %s: %s", plugin_name, err)

    async def _publish(self, metadata: TrackMetadata) -> None:
        """Write metadata to database and notify plugins."""
        if not self.testmode:
            try:
                metadb = nowplaying.db.MetadataDB()
                await metadb.write_to_metadb(metadata=metadata)
            except Exception as err:  # pylint: disable=broad-except
                logging.exception("write_to_metadb failed, still notifying plugins: %s", err)
        await self._notify_plugins(metadata=metadata)

    async def _notify_plugins(self, metadata: TrackMetadata | None = None) -> None:
        """notify all active notification plugins of track change"""
        if not self.active_notifications:
            return

        target_meta = metadata if metadata is not None else self.currentmeta

        # Fire-and-forget notification plugins to prevent blocking track polling
        for plugin in self.active_notifications:
            plugin_name = plugin.__class__.__name__

            async def notify_plugin_safe(
                plugin_instance=plugin,
                plugin_instance_name=plugin_name,
                meta=target_meta,
            ):
                """Wrapper to safely call plugin with error handling"""
                try:
                    await plugin_instance.notify_track_change(meta)
                except Exception as err:  # pylint: disable=broad-except
                    logging.error("Notification plugin %s failed: %s", plugin_instance_name, err)

            # Create task and manage its lifecycle to prevent garbage collection
            task = asyncio.create_task(notify_plugin_safe())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def _artfallbacks(self):
        if (
            self.config.cparser.value("artistextras/coverfornologos", type=bool)
            and not self.currentmeta.get("artistlogoraw")
            and self.currentmeta.get("coverimageraw")
        ):
            self.currentmeta["artistlogoraw"] = self.currentmeta["coverimageraw"]

        if (
            self.config.cparser.value("artistextras/coverfornothumbs", type=bool)
            and not self.currentmeta.get("artistthumbnailraw")
            and self.currentmeta.get("coverimageraw")
        ):
            self.currentmeta["artistthumbnailraw"] = self.currentmeta["coverimageraw"]

        if not self.currentmeta.get("coverimageraw"):
            storage = nowplaying.datacache.get_client().storage
            # Shared with _process_cover_images() so both sides build the key the same
            # way and album-less tracks get looked up here too.  They do not always
            # agree on the *input*: that stores mid-pipeline, while currentmeta has
            # been through _strip_identifiers().  So an album-less track whose title
            # loses content to titlestripper() was stored under the unstripped title
            # and will miss here.  Silent miss, never wrong art, and the album path is
            # unaffected since it does not key on title.  Making it hit would mean
            # carrying the computed identifier through as another temp key, or
            # stripping before MusicBrainz sees the title -- neither is worth it for a
            # fallback.
            if cachekey := nowplaying.metadata.processors.cover_cache_key(self.currentmeta):
                result = await storage.retrieve_by_identifier(
                    cachekey,
                    nowplaying.metadata.processors.COVER_DATA_TYPE,
                    random=True,
                )
                if result:
                    self.currentmeta["coverimageraw"] = result.data
            if not self.currentmeta.get("coverimageraw"):
                if imagetype := self.config.cparser.value("artistextras/nocoverfallback"):
                    imagetype = imagetype.lower()
                    if imagetype != "none" and self.currentmeta.get("imagecacheartist"):
                        norm_ic = nowplaying.utils.normalize(
                            self.currentmeta["imagecacheartist"], sizecheck=0, nospaces=True
                        )
                        result = await storage.retrieve_by_identifier(
                            norm_ic,
                            f"artist{imagetype}",
                            random=True,
                        )
                        if result:
                            self.currentmeta["coverimageraw"] = result.data

    async def _half_delay_write(self, elapsed_time: float = 0.0):
        try:
            delay = self.config.cparser.value("settings/delay", type=float, defaultValue=1.0)
        except ValueError:
            delay = 1.0
        delay /= 2

        # Reduce delay by time already spent processing
        actual_delay = max(0.0, delay - elapsed_time)
        logging.debug(
            "got half-delay of %ss (reduced by %.3fs elapsed, sleeping %.3fs)",
            delay,
            elapsed_time,
            actual_delay,
        )
        await asyncio.sleep(actual_delay)

    async def _process_artistextras(self):
        if not self.currentmeta.get("artist") or not self.config.cparser.value(
            "artistextras/enabled", type=bool
        ):
            return

        async def fill_in_async():
            """Async wrapper to fetch images with task management"""
            tryagain = False

            storage = nowplaying.datacache.get_client().storage
            identifier = nowplaying.utils.normalize(
                self.currentmeta.get("imagecacheartist", ""), sizecheck=0, nospaces=True
            )

            # Create tasks for each image type to fetch concurrently
            image_tasks = []
            image_keys = ["artistthumbnail", "artistlogo", "artistbanner"]

            for key in image_keys:
                rawkey = f"{key}raw"
                if not self.currentmeta.get(rawkey):

                    async def fetch_image_task(image_key: str, raw_key: str):
                        """Task to fetch a single image type via datacache (aiosqlite + aiofiles)"""
                        try:
                            result = await storage.retrieve_by_identifier(
                                identifier, image_key, random=True
                            )
                            if result:
                                return raw_key, result.data
                            return raw_key, None
                        except Exception as err:  # pylint: disable=broad-except
                            logging.debug("Error fetching %s: %s", image_key, err)
                            return raw_key, None

                    task = asyncio.create_task(fetch_image_task(key, rawkey))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                    image_tasks.append(task)

            # Wait for all image fetch tasks to complete
            if image_tasks:
                results = await asyncio.gather(*image_tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        logging.debug("Image fetch task failed: %s", result)
                        tryagain = True
                        continue

                    rawkey, image = result
                    if not image:
                        logging.debug(
                            "did not get an image for %s %s",
                            rawkey,
                            self.currentmeta["artist"],
                        )
                        tryagain = True
                    else:
                        self.currentmeta[rawkey] = image

            return tryagain

        # try to give it a bit more time if it doesn't complete the first time
        if not await fill_in_async():
            await fill_in_async()


def stop(pid):
    """stop the web server -- called from Tray"""
    logging.info("sending INT to %s", pid)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGINT)


def start(stopevent, bundledir, testmode=False):  # pylint: disable=unused-argument
    """multiprocessing start hook"""
    threading.current_thread().name = "TrackPoll"

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
    else:
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname="debug.log", rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir, logpath=logpath, testmode=testmode)
    try:
        TrackPoll.create_with_plugins(  # pylint: disable=unused-variable
            stopevent=stopevent, config=config, testmode=testmode
        )
    except Exception as error:  # pylint: disable=broad-except
        logging.error("TrackPoll crashed: %s", error, exc_info=True)
        sys.exit(1)
    logging.info("shutting down trackpoll v%s", config.version)
