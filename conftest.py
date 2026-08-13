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
import nowplaying.datacache.utils
import nowplaying.utils.sqlite
import tests.utils_prefs

# Keep cached entries alive across CI runs; see _effective_ttl().  Set in the
# environment, not by patching, so subprocesses inherit it -- they spawn rather
# than fork on macOS and Windows.  setdefault to allow a per-run override.
os.environ.setdefault(nowplaying.datacache.utils.TTL_FLOOR_ENV, str(30 * 24 * 3600))

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
                                " OR url LIKE 'derived://%/wnp%mock%'"
                                # cached_fetch() used to mint apicache:// keys; a
                                # restored CI cache can still hold mock rows under
                                # the old prefix, and those expire rather than
                                # being swept, so keep matching it.
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
# OS X caches preference files in cfprefsd, so removing them has to go
# through it -- see tests.utils_prefs.remove_prefs_domain().
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
        # Move datacache out first to avoid ENOTEMPTY from open SQLite WAL handles
        datacache_dir = cachedir / "datacache"
        temp_datacache = None
        if datacache_dir.exists():
            temp_datacache = cachedir.parent / f"datacache_temp_{os.getpid()}"
            shutil.move(str(datacache_dir), str(temp_datacache))

        logging.info("Removing %s", cachedir)
        # requests/request.db (nowplaying/trackrequests.py) sits directly in cachedir,
        # unlike datacache above, and a webserver test's Requests() instance can still
        # hold it open in a just-stopped subprocess for a moment after
        # stop_all_processes() returns.  Same ERROR_SHARING_VIOLATION race the datacache
        # move-aside works around, so retry rather than fail the next test's setup.
        nowplaying.utils.sqlite.retry_file_operation(lambda: shutil.rmtree(cachedir))

        # Always recreate cachedir — other tests depend on it existing even if empty
        cachedir.mkdir(parents=True, exist_ok=True)

        # Restore datacache directory to avoid cache misses that exhaust the
        # Discogs/etc rate limit across tests.
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
    tests.utils_prefs.remove_prefs_domain(filename)
    if filename.exists():
        logging.error("Still exists, wtf?")
    yield filename
    tests.utils_prefs.remove_prefs_domain(filename)


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
