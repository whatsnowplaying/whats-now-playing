#!/usr/bin/env python3
''' test webserver artist-related endpoints '''

import contextlib
import logging
import os
import pathlib
import socket
import sys
import tempfile
import time
import unittest.mock

import pytest
import requests

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.config  # pylint: disable=import-error
import nowplaying.db  # pylint: disable=import-error
import nowplaying.subprocesses  # pylint: disable=import-error


def is_port_in_use(port: int) -> bool:
    ''' check if a port is in use '''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(('localhost', port)) == 0


@pytest.fixture(scope="module")
def shared_webserver_config(pytestconfig):  # pylint: disable=redefined-outer-name
    ''' module-scoped webserver configuration for artist endpoint tests '''
    with contextlib.suppress(PermissionError):  # Windows blows
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as newpath:

            dbinit_patch = unittest.mock.patch('nowplaying.db.MetadataDB.init_db_var')
            dbinit_mock = dbinit_patch.start()
            dbdir = pathlib.Path(newpath).joinpath('mdb')
            dbdir.mkdir()
            dbfile = dbdir.joinpath('test.db')
            dbinit_mock.return_value = dbfile

            with unittest.mock.patch.dict(os.environ, {
                    "WNP_CONFIG_TEST_DIR": str(newpath),
                    "WNP_METADB_TEST_FILE": str(dbfile)
            }):
                bundledir = pathlib.Path(pytestconfig.rootpath).joinpath('nowplaying')
                nowplaying.bootstrap.set_qt_names(domain='com.github.whatsnowplaying.testsuite',
                                                  appname='testsuite')
                config = nowplaying.config.ConfigFile(bundledir=bundledir,
                                                      logpath=newpath,
                                                      testmode=True)
                config.cparser.setValue('acoustidmb/enabled', False)
                config.cparser.setValue('weboutput/httpenabled', 'true')
                config.cparser.sync()

                metadb = nowplaying.db.MetadataDB(initialize=True)
                logging.debug("shared webserver databasefile = %s", metadb.databasefile)

                port = config.cparser.value('weboutput/httpport', type=int)
                logging.debug('checking %s for use', port)
                while is_port_in_use(port):
                    logging.debug('%s is in use; waiting', port)
                    time.sleep(2)

                manager = nowplaying.subprocesses.SubprocessManager(config=config, testmode=True)
                manager.start_webserver()
                time.sleep(5)

                req = requests.get(f'http://localhost:{port}/internals', timeout=5)
                logging.debug("internals = %s", req.json())

                # Store the actual port since config gets cleared by autouse fixtures
                yield config, metadb, manager, port

                manager.stop_all_processes()
                # Give Windows more time for process shutdown and cleanup
                time.sleep(5)
                # Don't vacuum on Windows - causes file locking issues in tests
                if sys.platform != "win32":
                    try:
                        metadb.vacuum_database()
                    except Exception as e:
                        logging.warning("Could not vacuum database during cleanup: %s", e)
                # Give Windows additional time to release file handles
                time.sleep(2)
                dbinit_mock.stop()


@pytest.fixture
def getwebserver(shared_webserver_config):  # pylint: disable=redefined-outer-name
    ''' configure the webserver, dependents with prereqs '''
    config, metadb, manager, port = shared_webserver_config  # pylint: disable=unused-variable

    # Stop the shared webserver to avoid config conflicts with autouse fixture
    manager.stop_all_processes()
    time.sleep(1)

    # Re-enable webserver settings (in case autouse clear_old_testsuite cleared them)
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue('weboutput/httpport', port)  # Restore the actual port
    config.cparser.setValue('acoustidmb/enabled', False)  # Ensure this is disabled for tests
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    # Recreate the database for clean test isolation
    metadb.setupsql()

    # Start a fresh webserver process with current config
    manager.start_webserver()
    time.sleep(5)

    yield config, metadb

    # Stop the webserver again for next test
    manager.stop_all_processes()
    # Give Windows time to release resources between tests
    if sys.platform == "win32":
        time.sleep(3)
    else:
        time.sleep(1)


def test_webserver_artistfanart_test(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure artistfanart works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get(f'http://localhost:{port}/artistfanart.htm', timeout=5)
    assert req.status_code == 202


def test_webserver_banner_test(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure banner works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get(f'http://localhost:{port}/artistbanner.htm', timeout=5)
    assert req.status_code == 202

    req = requests.get(f'http://localhost:{port}/artistbanner.png', timeout=5)
    assert req.status_code == 200


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot close fast enough")
def test_webserver_logo_test(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure banner works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get(f'http://localhost:{port}/artistlogo.htm', timeout=5)
    assert req.status_code == 202

    req = requests.get(f'http://localhost:{port}/artistlogo.png', timeout=5)
    assert req.status_code == 200