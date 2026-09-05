#!/usr/bin/env python3
"""test winmedia ... ok, not really."""

import sys
import unittest.mock

import pytest

import nowplaying.inputs
import nowplaying.inputs.winmedia  # pylint: disable=import-error


@pytest.mark.asyncio
async def test_winmedia():
    """entry point as a standalone app"""
    plugin = nowplaying.inputs.winmedia.Plugin()
    if metadata := await plugin.getplayingtrack():
        if "coverimageraw" in metadata:
            del metadata["coverimageraw"]

    if sys.platform == "win32":
        assert plugin.available
    else:
        assert not plugin.available


def test_winmedia_without_winrt_is_broken():
    """No bindings means this machine cannot run it, which waiting will not fix."""
    plugin = nowplaying.inputs.winmedia.Plugin()
    with unittest.mock.patch.object(nowplaying.inputs.winmedia, "WINMEDIA_STATUS", False):
        status = plugin.status()
    assert status.health is nowplaying.inputs.InputHealth.BROKEN
    assert not status, "nothing to poll on a machine that cannot run it"


def test_winmedia_reader_task_ending_asks_for_a_restart():
    """start() adds a task that discards itself when done, so empty means dead.

    Patches the availability flag so the task branches are reachable off
    Windows; the flag itself is covered above.
    """
    plugin = nowplaying.inputs.winmedia.Plugin()
    with unittest.mock.patch.object(nowplaying.inputs.winmedia, "WINMEDIA_STATUS", True):
        assert plugin.status().health is nowplaying.inputs.InputHealth.OK, "not started yet"

        plugin._started = True  # pylint: disable=protected-access
        status = plugin.status()
        assert status.health is nowplaying.inputs.InputHealth.NEEDS_RESTART
        assert not status

        plugin.tasks.add(object())  # a task that is still running
        assert plugin.status().health is nowplaying.inputs.InputHealth.OK
