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
from PySide6.QtCore import (  # pylint: disable=import-error, no-name-in-module
    QCoreApplication,
    QSettings,
    QStandardPaths,
)

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.datacache
import nowplaying.utils.sqlite

# if sys.platform == 'darwin':
#     import psutil
#     import pwd

# Enable tracemalloc to track resource allocations
tracemalloc.start()

_PYTEST_LOCKFILE = pathlib.Path(tempfile.gettempdir()) / "pytest-wnp.lock"


@pytest.fixture(scope="session", autouse=True)
def enforce_single_pytest_instance():
    """Fail immediately if another pytest session is already running."""
    if _PYTEST_LOCKFILE.exists():
        raise RuntimeError(
            f"\n\nAnother pytest session is already running (lockfile: {_PYTEST_LOCKFILE}).\n"
            "NEVER run more than one pytest at a time.\n"
            "If no pytest is actually running, delete the lockfile and retry.\n"
        )
    _PYTEST_LOCKFILE.touch()
    yield
    _PYTEST_LOCKFILE.unlink(missing_ok=True)


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

            # Remove any mock cache entries created during the test so they
            # don't contaminate subsequent tests that use the shared cache.
            cachedir = pathlib.Path(
                QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
            )
            datacache_db = cachedir / "datacache" / "datacache.sqlite"
            if datacache_db.exists():
                with contextlib.suppress(Exception):  # pylint: disable=broad-exception-caught

                    def _cleanup():
                        with nowplaying.utils.sqlite.sqlite_connection(str(datacache_db)) as conn:
                            conn.execute(
                                "DELETE FROM cached_data"
                                " WHERE identifier LIKE 'wnpmock%'"
                                " OR LOWER(identifier) LIKE 'wnp mock%'"
                                " OR url LIKE 'apicache://%/wnp%mock%'"
                            )
                            conn.execute(
                                "DELETE FROM pending_requests"
                                " WHERE json_extract(params, '$.identifier') LIKE 'wnpmock%'"
                                " OR LOWER(json_extract(params, '$.identifier')) LIKE 'wnp mock%'"
                            )

                    nowplaying.utils.sqlite.retry_sqlite_operation(_cleanup)

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
        # Reset singletons so the next test reconnects to the restored DB
        # on the current event loop rather than a stale one.
        nowplaying.datacache.reset_shared_storage()
        nowplaying.datacache.reset_client()

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


@pytest.fixture(autouse=True)
def mock_first_install_dialog():
    """Globally mock the first-install dialog to prevent it from blocking tests."""
    with unittest.mock.patch("nowplaying.firstinstall.show_first_install_dialog"):
        yield


@pytest.fixture(autouse=True)
def mock_charts_key_generation():
    """Mock Charts anonymous key generation to prevent API calls during tests."""
    with unittest.mock.patch("nowplaying.notifications.charts.generate_anonymous_key") as mock_key:
        mock_key.return_value = None
        yield mock_key
