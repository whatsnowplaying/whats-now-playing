#!/usr/bin/env python3
"""pytest fixtures"""

import contextlib
import logging
import os
import pathlib
import shutil
import sys
import tempfile
import tracemalloc
import unittest.mock

import pytest
import pytest_asyncio
from PySide6.QtCore import (  # pylint: disable=import-error, no-name-in-module
    QCoreApplication,
    QSettings,
    QStandardPaths,
)

import nowplaying.apicache
import nowplaying.bootstrap
import nowplaying.config
import nowplaying.datacache

# if sys.platform == 'darwin':
#     import psutil
#     import pwd

# Enable tracemalloc to track resource allocations
tracemalloc.start()

# These libraries are extremely verbose at DEBUG level; suppress them so they
# don't overwhelm test output.  (bootstrap.setuplogging() does the same for
# the running app but is not called during tests.)
logging.getLogger("hpack").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# DO NOT CHANGE THIS TO BE com.github.whatsnowplaying
# otherwise your actual bits will disappear!
DOMAIN = "com.github.whatsnowplaying.testsuite"

try:
    from pytest_cov.embed import cleanup_on_sigterm
except ImportError:
    pass
else:
    cleanup_on_sigterm()


def reboot_macosx_prefs():
    """work around Mac OS X's preference caching"""
    if sys.platform == "darwin":
        os.system(f"defaults delete {DOMAIN}")
        #
        # old method:
        #
        # for process in psutil.process_iter():
        #     try:
        #         if 'cfprefsd' in process.name() and pwd.getpwuid(
        #                 os.getuid()).pw_name == process.username():
        #             process.terminate()
        #             process.wait()
        #     except psutil.NoSuchProcess:
        #         pass


@pytest.fixture
def getroot(pytestconfig):
    """get the base of the source tree"""
    return pytestconfig.rootpath


@pytest.fixture
def bootstrap(getroot):  # pylint: disable=redefined-outer-name
    """bootstrap a configuration"""
    with contextlib.suppress(PermissionError):  # Windows blows
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as newpath:
            dbdir = pathlib.Path(newpath).joinpath("mdb")
            dbdir.mkdir()
            dbfile = dbdir.joinpath("test.db")

            rmdir = newpath
            bundledir = pathlib.Path(getroot).joinpath("nowplaying")
            nowplaying.bootstrap.set_qt_names(domain=DOMAIN, appname="testsuite")
            config = nowplaying.config.ConfigFile(
                bundledir=bundledir, logpath=newpath, testmode=True
            )
            config.cparser.setValue("acoustidmb/enabled", False)
            config.cparser.setValue("testmode/metadbpath", str(dbfile))
            config.cparser.sync()
            config.testdir = pathlib.Path(newpath)
            config.dbtestfile = dbfile

            yield config
            if pathlib.Path(rmdir).exists():
                shutil.rmtree(rmdir)


#
# OS X has a lot of caching wrt preference files
# so we have do a lot of work to make sure they
# don't stick around
#
@pytest.fixture(autouse=True, scope="function")
def clear_old_testsuite():  # pylint: disable=too-many-statements
    """clear out old testsuite configs"""
    if sys.platform == "win32":
        qsettingsformat = QSettings.IniFormat
    else:
        qsettingsformat = QSettings.NativeFormat

    nowplaying.bootstrap.set_qt_names(appname="testsuite")
    config = QSettings(
        qsettingsformat,
        QSettings.SystemScope,
        QCoreApplication.organizationName(),
        QCoreApplication.applicationName(),
    )
    config.clear()
    config.sync()

    cachedir = pathlib.Path(QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0])
    if "testsuite" in cachedir.name and cachedir.exists():
        # Preserve api_cache directory for shared cache across tests
        api_cache_dir = cachedir / "api_cache"
        temp_api_cache = None
        if api_cache_dir.exists():
            # Temporarily move api_cache out of the way
            temp_api_cache = cachedir.parent / f"api_cache_temp_{os.getpid()}"
            shutil.move(str(api_cache_dir), str(temp_api_cache))

        # Move datacache out first to avoid ENOTEMPTY from open SQLite WAL handles
        datacache_dir = cachedir / "datacache"
        temp_datacache = None
        if datacache_dir.exists():
            temp_datacache = cachedir.parent / f"datacache_temp_{os.getpid()}"
            shutil.move(str(datacache_dir), str(temp_datacache))

        logging.info("Removing %s", cachedir)
        shutil.rmtree(cachedir)

        # Always recreate cachedir — other tests depend on it existing even if empty
        cachedir.mkdir(parents=True, exist_ok=True)

        # Restore api_cache directory
        if temp_api_cache and temp_api_cache.exists():
            shutil.move(str(temp_api_cache), str(api_cache_dir))

        # Restore datacache directory (preserved like api_cache to avoid cache
        # misses that exhaust the Discogs/etc rate limit across tests).
        if temp_datacache and temp_datacache.exists():
            shutil.move(str(temp_datacache), str(datacache_dir))
        # Reset singleton so the next test reconnects to the restored database.
        global _SHARED_DATACACHE_INSTANCE  # pylint: disable=global-statement
        _SHARED_DATACACHE_INSTANCE = None
        nowplaying.datacache.reset_shared_storage()

    config = QSettings(
        qsettingsformat,
        QSettings.UserScope,
        QCoreApplication.organizationName(),
        QCoreApplication.applicationName(),
    )
    config.clear()
    config.sync()
    filename = pathlib.Path(config.fileName())
    del config
    if filename.exists():
        filename.unlink()
    reboot_macosx_prefs()
    if filename.exists():
        filename.unlink()
    reboot_macosx_prefs()
    if filename.exists():
        logging.error("Still exists, wtf?")
    yield filename
    if filename.exists():
        filename.unlink()
    reboot_macosx_prefs()
    if filename.exists():
        filename.unlink()
    reboot_macosx_prefs()


@pytest.fixture(scope="session", autouse=True)
def run_datacache_maintenance_once():
    """Run datacache maintenance once per session to clean up expired entries.

    Without this, stale entries (e.g. empty-dict negative results from previous
    sessions) accumulate indefinitely since the test suite never calls systemtray's
    startup maintenance path.
    """
    nowplaying.datacache.run_maintenance()
    yield


@pytest.fixture(autouse=True)
def mock_first_install_dialog():
    """Globally mock the first-install dialog to prevent it from blocking tests."""
    with unittest.mock.patch("nowplaying.firstinstall.show_first_install_dialog"):
        yield


# Global cache instance shared across all tests in the session
_SHARED_CACHE_INSTANCE = None


@pytest_asyncio.fixture
async def isolated_api_cache():
    """Create an isolated API cache for testing (one per test)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = pathlib.Path(temp_dir)
        cache = nowplaying.apicache.APIResponseCache(cache_dir=cache_dir)
        # Wait for initialization to complete
        await cache._initialize_db()  # pylint: disable=protected-access
        try:
            yield cache
        finally:
            # Properly close the cache to prevent event loop warnings
            await cache.close()


@pytest_asyncio.fixture(scope="function")
async def shared_api_cache():
    """Create a shared API cache for artistextras tests to reduce API calls.

    Uses Qt standard cache location which is preserved by clear_old_testsuite.
    """
    global _SHARED_CACHE_INSTANCE  # pylint: disable=global-statement

    # Reuse the same cache instance across all tests
    # Don't pass cache_dir - let it use Qt standard location
    if _SHARED_CACHE_INSTANCE is None:
        _SHARED_CACHE_INSTANCE = nowplaying.apicache.APIResponseCache()
        await _SHARED_CACHE_INSTANCE._initialize_db()  # pylint: disable=protected-access

    yield _SHARED_CACHE_INSTANCE


@pytest_asyncio.fixture
async def isolated_datacache_storage():
    """Fresh DataStorage per test for verifying cache hit/miss behaviour."""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = nowplaying.datacache.DataStorage(pathlib.Path(temp_dir))
        await storage.initialize()
        original = nowplaying.datacache._shared_storage  # pylint: disable=protected-access
        nowplaying.datacache.set_shared_storage(storage)
        try:
            yield storage
        finally:
            nowplaying.datacache.set_shared_storage(original)
            await storage.close()


@pytest_asyncio.fixture
async def isolated_datacache_client():
    """Fresh DataCacheClient per test with isolated storage.

    Patches nowplaying.datacache.get_client so that plugins calling get_client()
    receive a client backed by a temporary directory rather than the real cache.
    Also swaps the shared storage singleton so cached_fetch() is isolated too.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = pathlib.Path(temp_dir)
        client = nowplaying.datacache.DataCacheClient(temp_path)
        await client.initialize()
        original_storage = nowplaying.datacache._shared_storage  # pylint: disable=protected-access
        nowplaying.datacache.set_shared_storage(client.storage)
        with unittest.mock.patch("nowplaying.datacache.get_client", return_value=client):
            try:
                yield client
            finally:
                nowplaying.datacache.set_shared_storage(original_storage)
                await client.close()


_SHARED_DATACACHE_INSTANCE = None


@pytest_asyncio.fixture(scope="function")
async def shared_datacache_storage():
    """Shared DataStorage for artistextras tests to avoid redundant fetches.

    scope="function" is required by pytest-asyncio's function-scoped event loop.
    The module-level singleton makes this a session singleton in practice.
    No explicit close() needed: DataStorage uses connection-per-operation with
    no persistent handle to release.
    """
    global _SHARED_DATACACHE_INSTANCE  # pylint: disable=global-statement
    if _SHARED_DATACACHE_INSTANCE is None:
        _SHARED_DATACACHE_INSTANCE = nowplaying.datacache.DataStorage()
        await _SHARED_DATACACHE_INSTANCE.initialize()
    yield _SHARED_DATACACHE_INSTANCE


@pytest_asyncio.fixture(autouse=True)
async def auto_shared_datacache_for_artistextras(request, shared_datacache_storage):  # pylint: disable=redefined-outer-name
    """Mirror of auto_shared_api_cache_for_artistextras for the datacache layer."""
    test_modules = ["test_artistextras", "test_musicbrainz", "test_metadata_multi_artist"]
    test_manages_own_cache = (
        "shared_datacache_storage" in request.fixturenames
        or "isolated_datacache_storage" in request.fixturenames
    )
    if (
        any(module in request.module.__name__ for module in test_modules)
        and not test_manages_own_cache
    ):
        nowplaying.datacache.set_shared_storage(shared_datacache_storage)
        yield
    else:
        yield


@pytest_asyncio.fixture(autouse=True)
async def auto_shared_api_cache_for_artistextras(request, shared_api_cache):  # pylint: disable=redefined-outer-name
    """Automatically use shared API cache for tests that hit
    external APIs to prevent CI failures.
    """
    # Auto-apply to artistextras, musicbrainz, and metadata_multi_artist tests
    # Skip tests that explicitly manage their own cache
    test_modules = ["test_artistextras", "test_musicbrainz", "test_metadata_multi_artist"]
    test_manages_own_cache = (
        "shared_api_cache" in request.fixturenames or "isolated_api_cache" in request.fixturenames
    )

    if (
        any(module in request.module.__name__ for module in test_modules)
        and not test_manages_own_cache
    ):
        # Set the shared cache instance for this test
        nowplaying.apicache.set_cache_instance(shared_api_cache)
        yield
        # Note: We intentionally do NOT restore the original cache instance
        # to avoid race conditions where async operations might still be using the cache
    else:
        yield


@pytest.fixture(autouse=True)
def mock_charts_key_generation():
    """Mock Charts anonymous key generation to prevent API calls during tests."""
    with unittest.mock.patch("nowplaying.notifications.charts.generate_anonymous_key") as mock_key:
        # Return None to simulate no key generation during tests
        mock_key.return_value = None
        yield mock_key
