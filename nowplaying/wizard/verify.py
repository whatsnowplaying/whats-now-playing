#!/usr/bin/env python3
"""Live verification of an input plugin while its wizard page is shown.

Kept apart from the page base: this half is a worker thread and a result
type, and the only thing it shares with the widgets is the signal between
them.
"""

import asyncio
import contextlib
import dataclasses
import enum
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QWidget  # pylint: disable=no-name-in-module

if TYPE_CHECKING:
    import nowplaying.inputs

# A plugin's start() may never return -- Denon runs discovery, Icecast waits on
# a broadcaster -- so every call the worker makes is bounded.
START_TIMEOUT = 20.0
POLL_TIMEOUT = 10.0
POLL_INTERVAL = 2.0


class VerifyStatus(enum.Enum):
    """Outcome of one verification poll.

    Plugins only ever produce OK and WAITING: they report what they saw.
    FAILED and TIMEOUT are synthesised by the worker, so plugin authors do not
    have to write error handling.
    """

    OK = "ok"
    WAITING = "waiting"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclasses.dataclass
class VerifyResult:
    """What verification currently sees, in terms the user can act on."""

    status: VerifyStatus
    message: str
    prompt: str | None = None
    detail: str | None = None


class VerifyWorker(QThread):
    """Drive a plugin's start/poll/stop lifecycle on its own asyncio loop.

    The plugin is constructed inside run(), so it is only ever touched by the
    thread that owns its event loop; the UI side holds nothing but the
    VerifyResult carried by the signal.
    """

    observed = Signal(object)

    def __init__(self, plugin_module, config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugin_module = plugin_module
        self._config = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None

    def request_stop(self) -> None:
        """Ask the loop to wind up. Safe to call from the UI thread.

        The loop may already be gone: start() timing out or raising ends
        _drive() early, after which asyncio.run() closes it. Racing that is
        normal, not an error -- there is nothing left to stop.
        """
        if self._loop is None or self._stop is None:
            return
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(self._stop.set)

    def run(self) -> None:  # pylint: disable=invalid-name
        """QThread entry point: one asyncio loop for the page's whole lifetime."""
        with contextlib.suppress(Exception):
            asyncio.run(self._drive())

    async def _drive(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        try:
            plugin = self._plugin_module.Plugin(config=self._config)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.exception("verify: could not construct plugin")
            self.observed.emit(
                VerifyResult(VerifyStatus.FAILED, _explain(error), detail=str(error))
            )
            return

        # Once the plugin exists, stop() has to run on every path out. A
        # start() that times out is cancelled mid-flight, so it can be holding
        # real resources already: icecast and traktor bind the SOURCE port in
        # start_port(), and virtualdj and rekordbox have a watchdog Observer
        # thread running. Leaving those alive is the state stop_verification()
        # exists to prevent, since start_all_processes() follows moments later.
        try:
            try:
                await asyncio.wait_for(plugin.start(), timeout=START_TIMEOUT)
            except TimeoutError:
                self.observed.emit(
                    VerifyResult(VerifyStatus.TIMEOUT, "This source did not respond.")
                )
                return
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.exception("verify: start() failed")
                self.observed.emit(
                    VerifyResult(VerifyStatus.FAILED, _explain(error), detail=str(error))
                )
                return
            await self._poll_loop(plugin)
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(plugin.stop(), timeout=START_TIMEOUT)

    async def _poll_loop(self, plugin) -> None:
        """Emit what the plugin sees until asked to stop."""
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                status = plugin.status()
                if (settled := _from_status(status)) is not None:
                    self.observed.emit(settled)
                else:
                    meta = await asyncio.wait_for(plugin.getplayingtrack(), timeout=POLL_TIMEOUT)
                    self.observed.emit(_classify(meta, waiting=status.message))
            except TimeoutError:
                self.observed.emit(
                    VerifyResult(VerifyStatus.TIMEOUT, "This source stopped responding.")
                )
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.exception("verify: getplayingtrack() failed")
                self.observed.emit(
                    VerifyResult(VerifyStatus.FAILED, _explain(error), detail=str(error))
                )
            # Interruptible sleep: a plain asyncio.sleep would delay page
            # changes by up to the poll interval.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=POLL_INTERVAL)


def _from_status(status: "nowplaying.inputs.InputStatus") -> VerifyResult | None:
    """Report what the plugin says about itself, or None to go on polling.

    A plugin that cannot work knows why and says so in terms fit to show
    someone, which is the whole reason status() carries a message. Polling it
    anyway would produce "No track yet." indefinitely and leave the user to
    guess whether they had done something wrong.
    """
    if status:
        # OK, STARTING and WAITING all expect to produce a track, so carry on
        # polling; WAITING's message becomes the label if nothing arrives.
        return None
    return VerifyResult(
        VerifyStatus.FAILED,
        status.message or "This source cannot run right now.",
        detail=status.detail or None,
    )


def _explain(error: BaseException) -> str:
    """Prefer the plugin's own words.

    Plugins raise domain errors that already say what to do -- Rekordbox's
    names the missing key and where to enter it -- and replacing that with a
    generic "could not start" throws away the only actionable part.

    Only start() failures reach this now: per the input contract those are
    defects rather than misconfiguration, so there is no message written for a
    user to read and the exception text is the best available.
    """
    text = str(error).strip()
    return text or "Could not start this source."


def _classify(meta, waiting: str = "") -> VerifyResult:
    """Turn a getplayingtrack() result into something worth showing a user.

    `waiting` is what the plugin said it was waiting on, used in place of the
    generic label so a stalled source explains itself rather than looking the
    same as one nobody has played a track on yet.
    """
    nothing = waiting or "No track yet."
    if not meta:
        return VerifyResult(VerifyStatus.WAITING, nothing)
    artist = meta.get("artist") or ""
    title = meta.get("title") or ""
    if not (artist or title):
        return VerifyResult(VerifyStatus.WAITING, nothing)
    seen = " — ".join(part for part in (artist, title) if part)
    return VerifyResult(VerifyStatus.OK, f"Reading: {seen}")
