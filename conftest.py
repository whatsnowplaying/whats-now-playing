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

# Enable tracemalloc to track resource allocations
tracemalloc.start()

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths  # pylint: disable=import-error, no-name-in-module

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.apicache

# if sys.platform == 'darwin':
#     import psutil
#     import pwd

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

            with unittest.mock.patch.dict(
                os.environ,
                {"WNP_CONFIG_TEST_DIR": str(newpath), "WNP_METADB_TEST_FILE": str(dbfile)},
            ):
                rmdir = newpath
                bundledir = pathlib.Path(getroot).joinpath("nowplaying")
                nowplaying.bootstrap.set_qt_names(domain=DOMAIN, appname="testsuite")
                config = nowplaying.config.ConfigFile(
                    bundledir=bundledir, logpath=newpath, testmode=True
                )
                config.cparser.setValue("acoustidmb/enabled", False)
                config.cparser.sync()
                config.testdir = pathlib.Path(newpath)

                yield config
            if pathlib.Path(rmdir).exists():
                shutil.rmtree(rmdir)


#
# OS X has a lot of caching wrt preference files
# so we have do a lot of work to make sure they
# don't stick around
#
@pytest.fixture(autouse=True, scope="function")
def clear_old_testsuite():
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
        logging.info("Removing %s", cachedir)
        shutil.rmtree(cachedir)

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


@pytest_asyncio.fixture
async def temp_api_cache():
    """Create a temporary API cache for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = pathlib.Path(temp_dir)
        cache = nowplaying.apicache.APIResponseCache(cache_dir=cache_dir)
        # Wait for initialization to complete
        await cache._initialize_db()  # pylint: disable=protected-access
        try:
            yield cache
        finally:
            # Properly close the cache to prevent event loop warnings
            if hasattr(cache, "close"):
                await cache.close()


@pytest.fixture(autouse=True)
def auto_temp_api_cache_for_artistextras(request, temp_api_cache):  # pylint: disable=redefined-outer-name
    """Automatically use temp API cache for artistextras tests to prevent random CI failures."""
    # Only auto-apply to artistextras tests, not apicache tests
    if "test_artistextras" in request.module.__name__:
        original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
        nowplaying.apicache.set_cache_instance(temp_api_cache)
        try:
            yield
        finally:
            nowplaying.apicache.set_cache_instance(original_cache)
    else:
        yield
