#!/usr/bin/env python3
''' test webserver '''

import asyncio
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
import pytest_asyncio
import requests

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.config  # pylint: disable=import-error
import nowplaying.db  # pylint: disable=import-error
import nowplaying.subprocesses  # pylint: disable=import-error
import nowplaying.processes.webserver  # pylint: disable=import-error


def is_port_in_use(port: int) -> bool:
    ''' check if a port is in use '''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(('localhost', port)) == 0


@pytest.fixture(scope="module")
def shared_webserver_config(pytestconfig):  # pylint: disable=redefined-outer-name
    ''' module-scoped webserver configuration for main webserver tests '''
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

                metadb = nowplaying.db.MetadataDB(initialize=True) #pylint: disable=no-member
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
                time.sleep(2)

                # Try to vacuum database, but handle file locking gracefully
                try:
                    metadb.vacuum_database()
                except Exception as error: # pylint: disable=broad-exception-caught
                    logging.warning("Could not vacuum database during cleanup: %s", error)
                dbinit_mock.stop()


@pytest_asyncio.fixture
async def getwebserver(shared_webserver_config):  # pylint: disable=redefined-outer-name
    ''' configure the webserver, dependents with prereqs '''
    config, metadb, manager, port = shared_webserver_config  # pylint: disable=unused-variable

    # Stop the shared webserver to avoid config conflicts with autouse fixture
    manager.stop_all_processes()
    await asyncio.sleep(1)

    # Re-enable webserver settings (in case autouse clear_old_testsuite cleared them)
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue('weboutput/httpport', port)  # Restore the actual port
    config.cparser.setValue('acoustidmb/enabled', False)  # Ensure this is disabled for tests
    config.cparser.sync()

    # Recreate the database for clean test isolation
    metadb.setupsql()

    # Start a fresh webserver process with current config
    manager.start_webserver()
    await asyncio.sleep(5)

    yield config, metadb

    # Stop the webserver again for next test
    manager.stop_all_processes()
    await asyncio.sleep(1)


@pytest.mark.asyncio
async def test_startstopwebserver(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test a simple start/stop '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.sync()
    await asyncio.sleep(5)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
@pytest.mark.asyncio
async def test_webserver_htmtest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' start webserver, read existing data, add new data, then read that '''
    config, metadb = getwebserver
    port = config.cparser.value('weboutput/httpport', type=int)
    config.cparser.setValue('weboutput/htmltemplate',
                            config.getbundledir().joinpath('templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    await asyncio.sleep(10)

    logging.debug(config.cparser.value('weboutput/htmltemplate'))
    # handle no data, should return refresh

    req = requests.get(f'http://localhost:{port}/index.html', timeout=5)
    assert req.status_code == 202
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

    # handle first write

    await metadb.write_to_metadb(metadata={'title': 'testhtmtitle', 'artist': 'testhtmartist'})
    await asyncio.sleep(1)
    req = requests.get(f'http://localhost:{port}/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testhtmartist - testhtmtitle'

    # another read should give us refresh

    await asyncio.sleep(1)
    req = requests.get(f'http://localhost:{port}/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

    config.cparser.setValue('weboutput/once', False)
    config.cparser.sync()

    # flipping once to false should give us back same info

    await asyncio.sleep(1)
    req = requests.get(f'http://localhost:{port}/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testhtmartist - testhtmtitle'

    # handle second write

    await metadb.write_to_metadb(metadata={
        'artist': 'artisthtm2',
        'title': 'titlehtm2',
    })
    await asyncio.sleep(1)
    req = requests.get(f'http://localhost:{port}/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' artisthtm2 - titlehtm2'


@pytest.mark.asyncio
async def test_webserver_txttest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' start webserver, read existing data, add new data, then read that '''
    config, metadb = getwebserver
    port = config.cparser.value('weboutput/httpport', type=int)
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue('weboutput/htmltemplate',
                            config.getbundledir().joinpath('templates', 'basic-plain.txt'))
    config.cparser.setValue('textoutput/txttemplate',
                            config.getbundledir().joinpath('templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    await asyncio.sleep(10)

    # handle no data, should return refresh

    req = requests.get(f'http://localhost:{port}/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ''  # sourcery skip: simplify-empty-collection-comparison

    # should return empty
    req = requests.get(f'http://localhost:{port}/v1/last', timeout=5)
    assert req.status_code == 200
    assert req.json() == {}
    # handle first write

    await metadb.write_to_metadb(metadata={'title': 'testtxttitle', 'artist': 'testtxtartist'})
    await asyncio.sleep(1)
    req = requests.get(f'http://localhost:{port}/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testtxtartist - testtxttitle'

    req = requests.get(f'http://localhost:{port}/v1/last', timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata['artist'] == 'testtxtartist'
    assert checkdata['title'] == 'testtxttitle'
    assert not checkdata.get('dbid')

    # another read should give us same info

    await asyncio.sleep(1)
    req = requests.get(f'http://localhost:{port}/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testtxtartist - testtxttitle'

    req = requests.get(f'http://localhost:{port}/v1/last', timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata['artist'] == 'testtxtartist'
    assert checkdata['title'] == 'testtxttitle'
    assert not checkdata.get('dbid')

    # handle second write

    await metadb.write_to_metadb(metadata={
        'artist': 'artisttxt2',
        'title': 'titletxt2',
    })
    await asyncio.sleep(1)
    req = requests.get(f'http://localhost:{port}/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' artisttxt2 - titletxt2'

    req = requests.get(f'http://localhost:{port}/v1/last', timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata['artist'] == 'artisttxt2'
    assert checkdata['title'] == 'titletxt2'
    assert not checkdata.get('dbid')


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
@pytest.mark.xfail(sys.platform == "darwin", reason='timesout on macos')
def test_webserver_gifwordstest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure gifwords works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get(f'http://localhost:{port}/gifwords.htm', timeout=5)
    assert req.status_code == 200


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
def test_webserver_coverpng(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure coverpng works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get(f'http://localhost:{port}/cover.png', timeout=5)
    assert req.status_code == 200
