#!/usr/bin/env python3
"""pytest fixtures for the non-Qt test suite (tests/)"""

import asyncio
import pathlib
import tempfile
import unittest.mock

import pytest
import pytest_asyncio
from aiointercept import aiointercept

import nowplaying.apicache
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


_SHARED_CACHE_INSTANCE = None


@pytest_asyncio.fixture
async def isolated_api_cache():
    """Create an isolated API cache for testing (one per test)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = pathlib.Path(temp_dir)
        cache = nowplaying.apicache.APIResponseCache(cache_dir=cache_dir)
        await cache._initialize_db()  # pylint: disable=protected-access
        try:
            yield cache
        finally:
            await cache.close()


@pytest_asyncio.fixture(scope="function")
async def shared_api_cache():
    """Shared API cache for artistextras tests to reduce API calls."""
    global _SHARED_CACHE_INSTANCE  # pylint: disable=global-statement
    if _SHARED_CACHE_INSTANCE is None:
        _SHARED_CACHE_INSTANCE = nowplaying.apicache.APIResponseCache()
        await _SHARED_CACHE_INSTANCE._initialize_db()  # pylint: disable=protected-access
    yield _SHARED_CACHE_INSTANCE


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _shared_aiointercept():
    """One aiointercept(mock_external_urls=True) instance for the whole session.

    aiointercept starts a background thread with its own event loop per
    instantiation. On Windows (ProactorEventLoop) repeated start/stop cycles
    across many tests have been observed to hang the test run after a
    handful of uses, regardless of what a given test mocks. Tests share this
    one instance instead of creating a fresh one each time; use the
    aiointercept_mock fixture for a per-test-cleared view of it.
    """
    async with aiointercept(mock_external_urls=True) as mock:
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


@pytest_asyncio.fixture(autouse=True)
async def auto_shared_api_cache_for_artistextras(request, shared_api_cache):  # pylint: disable=redefined-outer-name
    """Automatically use shared API cache for tests that hit external APIs."""
    test_modules = ["test_artistextras", "test_musicbrainz", "test_metadata_multi_artist"]
    test_manages_own_cache = (
        "shared_api_cache" in request.fixturenames or "isolated_api_cache" in request.fixturenames
    )
    if (
        any(module in request.module.__name__ for module in test_modules)
        and not test_manages_own_cache
    ):
        nowplaying.apicache.set_cache_instance(shared_api_cache)
    yield
