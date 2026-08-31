#!/usr/bin/env python3
"""pytest fixtures for the non-Qt test suite (tests/)"""

import asyncio
import pathlib
import tempfile
import unittest.mock

import pytest
import pytest_asyncio
from aiointercept import aiointercept

import nowplaying.bootstrap
import nowplaying.datacache

# DO NOT CHANGE THIS TO BE com.github.whatsnowplaying
DOMAIN = "com.github.whatsnowplaying.testsuite"


@pytest.fixture(scope="session", autouse=True)
def run_datacache_maintenance_once():
    """Run datacache maintenance once per session to clean up expired entries."""
    nowplaying.bootstrap.set_qt_names(domain=DOMAIN, appname="testsuite")
    nowplaying.datacache.run_maintenance()
    yield


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _shared_aiointercept():
    """One aiointercept(mock_external_urls=True) instance for the whole session.

    aiointercept starts a background thread with its own event loop per
    instantiation. On Windows (ProactorEventLoop) repeated start/stop cycles
    across many tests have been observed to hang the test run after a
    handful of uses, regardless of what a given test mocks. Tests share this
    one instance instead of creating a fresh one each time; use the
    aiointercept_mock fixture for a per-test-cleared view of it.

    passthrough_unmatched=True is required here: this instance's DNS patch
    stays installed for the entire session (not just the tests that use it),
    so without it, any host a given test didn't explicitly register — e.g.
    the real webserver tests spin up and connect to — gets silently
    redirected into this mock's own dummy server instead of the real network.
    """
    async with aiointercept(mock_external_urls=True, passthrough_unmatched=True) as mock:
        yield mock


@pytest_asyncio.fixture
async def aiointercept_mock(_shared_aiointercept):  # pylint: disable=redefined-outer-name
    """Function-scoped, auto-cleared view onto the shared aiointercept mock."""
    _shared_aiointercept._caller_loop = asyncio.get_running_loop()  # pylint: disable=protected-access
    try:
        yield _shared_aiointercept
    finally:
        _shared_aiointercept.clear()


@pytest_asyncio.fixture(loop_scope="session")
async def isolated_datacache_storage():
    """Fresh DataStorage per test — use when a test directly exercises DataStorage APIs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = nowplaying.datacache.DataStorage(pathlib.Path(temp_dir))
        await storage.initialize()
        yield storage
        await storage.close()


@pytest_asyncio.fixture(loop_scope="session")
async def isolated_datacache_client():
    """Fresh DataCacheClient per test.

    Patches nowplaying.datacache.get_client so all code that calls get_client()
    — image queuing, cached_fetch, _artfallbacks, processors — uses a single
    isolated client backed by a temporary directory. No separate storage fixture
    is needed; client.storage is the one source of truth for the test.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = pathlib.Path(temp_dir)
        client = nowplaying.datacache.DataCacheClient(temp_path)
        await client.initialize()
        with unittest.mock.patch("nowplaying.datacache.get_client", return_value=client):
            try:
                yield client
            finally:
                await client.close()


def _providers(item) -> frozenset[str]:
    """Services a live test talks to, from @pytest.mark.live("discogs", ...)."""
    marker = item.get_closest_marker("live")
    return frozenset(marker.args) if marker else frozenset()


def _spread_by_provider(live: list) -> list:
    """Order live tests so neighbours share no service.

    Greedy rather than exact: at each step take the waiting test whose services
    were used longest ago. Good enough, and it keeps the artist extras tests
    that touch four providers at once away from the single-provider ones.
    """
    remaining = list(live)
    last_used: dict[str, int] = {}
    out: list = []
    while remaining:
        # Highest "staleness" first: the further back a test's services were
        # touched, the safer it is to run now.
        best = max(
            remaining,
            key=lambda item: min(
                (len(out) - last_used.get(name, -len(live)) for name in _providers(item)),
                default=len(out),
            ),
        )
        remaining.remove(best)
        for name in _providers(best):
            last_used[name] = len(out)
        out.append(best)
    return out


def pytest_collection_modifyitems(session, config, items):  # pylint: disable=unused-argument
    """Reorder the live-API tests so consecutive ones hit different services.

    Each live test builds its own client and wnpmb's adaptive pacing lives on
    the instance, so a file's worth of them arrives at one service with no
    spacing at all. Running them round-robin across providers gives each one
    roughly as many test-lengths of breathing room as there are providers.

    Only the live tests move, and only into slots live tests already occupied,
    so nothing else is reordered. That matters twice over: tests-qt has to stay
    first because qtbot must initialize before anything starts asyncio or
    threads, and tests/webserver's module-scoped fixture starts a real server
    that must not be torn down mid-module. This hook is handed every collected
    item, not just this directory's, so neither can be assumed.
    """
    slots = [i for i, item in enumerate(items) if item.get_closest_marker("live")]
    if len(slots) < 2:
        return
    ordered = _spread_by_provider([items[i] for i in slots])
    for slot, item in zip(slots, ordered, strict=True):
        items[slot] = item
