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


async def wait_for_webserver_ready(port: int, timeout: float = 10.0) -> bool:
    ''' Poll webserver until it's ready or timeout '''
    start_time = time.time()
    while time.time() - start_time < timeout:
        with contextlib.suppress(requests.exceptions.RequestException,
                                 requests.exceptions.ConnectionError):
            response = requests.get(f'http://localhost:{port}/internals', timeout=2)
            if response.status_code == 200:
                return True
        await asyncio.sleep(0.1)
    return False


async def wait_for_webserver_content_update(port: int,
                                            endpoint: str,
                                            expected_content: str | None = None,
                                            timeout: float = 5.0) -> tuple[bool, str]:
    ''' Poll webserver endpoint until content is
        updated with expected content or status 200, or timeout

    Returns (success, response_text) tuple
    '''
    start_time = time.time()
    while time.time() - start_time < timeout:
        with contextlib.suppress(requests.exceptions.RequestException,
                                 requests.exceptions.ConnectionError):
            response = requests.get(f'http://localhost:{port}{endpoint}', timeout=2)
            if response.status_code == 200 and (expected_content is None
                                                or expected_content in response.text):
                return True, response.text
        await asyncio.sleep(0.1)
    return False, ""


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

                metadb = nowplaying.db.MetadataDB(initialize=True)  #pylint: disable=no-member
                logging.debug("shared webserver databasefile = %s", metadb.databasefile)

                port = config.cparser.value('weboutput/httpport', type=int)
                logging.debug('checking %s for use', port)
                while is_port_in_use(port):
                    logging.debug('%s is in use; waiting', port)
                    time.sleep(2)

                manager = nowplaying.subprocesses.SubprocessManager(config=config, testmode=True)
                manager.start_webserver()

                # Poll webserver until ready with time-based deadline for accurate timeout
                timeout = 10.0  # 10 seconds for webserver startup
                start_time = time.time()
                while time.time() - start_time < timeout:
                    with contextlib.suppress(requests.exceptions.RequestException,
                                             requests.exceptions.ConnectionError):
                        req = requests.get(f'http://localhost:{port}/internals', timeout=2)
                        if req.status_code == 200:
                            logging.debug("internals = %s", req.json())
                            break
                    time.sleep(0.1)
                else:
                    raise RuntimeError(f"Webserver on port {port} failed to start within "
                                       f"{timeout} seconds")

                # Store the actual port since config gets cleared by autouse fixtures
                yield config, metadb, manager, port

                manager.stop_all_processes()
                time.sleep(2)

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

    # Poll webserver until ready instead of fixed sleep
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to start within 10 seconds")

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

    # Poll webserver until ready instead of fixed sleep
    port = config.cparser.value('weboutput/httpport', type=int)
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")


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

    # Poll webserver until ready instead of fixed sleep
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    logging.debug(config.cparser.value('weboutput/htmltemplate'))
    # handle no data, should return refresh

    req = requests.get(f'http://localhost:{port}/index.html', timeout=5)
    assert req.status_code == 202
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

    # handle first write

    await metadb.write_to_metadb(metadata={'title': 'testhtmtitle', 'artist': 'testhtmartist'})

    # Poll for content update instead of fixed sleep
    content_ready, response_text = await wait_for_webserver_content_update(
        port, '/index.html', expected_content=' testhtmartist - testhtmtitle', timeout=5.0)
    assert content_ready, "Webserver content failed to update within 5 seconds"
    assert response_text == ' testhtmartist - testhtmtitle'

    # another read should give us refresh

    await asyncio.sleep(0.1)  # Small delay for processing
    req = requests.get(f'http://localhost:{port}/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

    config.cparser.setValue('weboutput/once', False)
    config.cparser.sync()

    # flipping once to false should give us back same info

    await asyncio.sleep(0.1)  # Small delay for config to take effect
    req = requests.get(f'http://localhost:{port}/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testhtmartist - testhtmtitle'

    # handle second write

    await metadb.write_to_metadb(metadata={
        'artist': 'artisthtm2',
        'title': 'titlehtm2',
    })

    # Poll for content update instead of fixed sleep
    content_ready, response_text = await wait_for_webserver_content_update(
        port, '/index.html', expected_content=' artisthtm2 - titlehtm2', timeout=5.0)
    assert content_ready, "Webserver content failed to update within 5 seconds"
    assert response_text == ' artisthtm2 - titlehtm2'


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
@pytest.mark.asyncio
async def test_webserver_txttest(getwebserver):  # pylint: disable=redefined-outer-name,too-many-statements
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

    # Poll webserver until ready instead of fixed sleep
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

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

    # Poll for content update instead of fixed sleep
    content_ready, _ = await wait_for_webserver_content_update(
        port, '/index.txt', expected_content=' testtxtartist - testtxttitle', timeout=5.0)
    assert content_ready, "Webserver content failed to update within 5 seconds"

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

    await asyncio.sleep(0.1)  # Small delay for processing
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

    # Poll for content update instead of fixed sleep
    content_ready, _ = await wait_for_webserver_content_update(
        port, '/index.txt', expected_content=' artisttxt2 - titletxt2', timeout=5.0)
    assert content_ready, "Webserver content failed to update within 5 seconds"

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


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
def test_webserver_remote_input_no_secret(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test remote input endpoint without secret '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)

    # Test without secret configured - should accept any request
    test_metadata = {'artist': 'Test Artist', 'title': 'Test Title', 'filename': 'test.mp3'}

    req = requests.post(f'http://localhost:{port}/v1/remoteinput', json=test_metadata, timeout=5)
    assert req.status_code == 200
    response_data = req.json()
    assert 'dbid' in response_data


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
def test_webserver_remote_input_with_secret(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test remote input endpoint with secret authentication '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)

    # Configure secret
    test_secret = 'test_secret_123'  # pragma: allowlist secret
    config.cparser.setValue('remote/remote_key', test_secret)
    config.cparser.sync()

    test_metadata = {
        'artist': 'Test Artist',
        'title': 'Test Title',
        'filename': 'test.mp3',
        'secret': test_secret
    }

    # Test with correct secret
    req = requests.post(f'http://localhost:{port}/v1/remoteinput', json=test_metadata, timeout=5)
    assert req.status_code == 200
    response_data = req.json()
    assert 'dbid' in response_data


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
def test_webserver_remote_input_invalid_secret(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test remote input endpoint with invalid secret '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)

    # Configure secret
    test_secret = 'test_secret_123'   # pragma: allowlist secret
    config.cparser.setValue('remote/remote_key', test_secret)
    config.cparser.sync()

    test_metadata = {
        'artist': 'Test Artist',
        'title': 'Test Title',
        'filename': 'test.mp3',
        'secret': 'wrong_secret' # pragma: allowlist secret
    }

    # Test with wrong secret
    req = requests.post(f'http://localhost:{port}/v1/remoteinput', json=test_metadata, timeout=5)
    assert req.status_code == 403
    response_data = req.json()
    assert 'error' in response_data


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
def test_webserver_remote_input_missing_secret(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test remote input endpoint with missing secret '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)

    # Configure secret
    test_secret = 'test_secret_123'  # pragma: allowlist secret
    config.cparser.setValue('remote/remote_key', test_secret)
    config.cparser.sync()

    test_metadata = {
        'artist': 'Test Artist',
        'title': 'Test Title',
        'filename': 'test.mp3'
        # No secret field
    }

    # Test without secret when required
    req = requests.post(f'http://localhost:{port}/v1/remoteinput', json=test_metadata, timeout=5)
    assert req.status_code == 403
    response_data = req.json()
    assert 'error' in response_data


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
def test_webserver_remote_input_wrong_method(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test remote input endpoint with wrong HTTP method '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)

    test_metadata = {'artist': 'Test Artist', 'title': 'Test Title', 'filename': 'test.mp3'}

    # Test with GET instead of POST
    req = requests.get(f'http://localhost:{port}/v1/remoteinput', params=test_metadata, timeout=5)
    assert req.status_code == 405

    # Test with PUT instead of POST
    req = requests.put(f'http://localhost:{port}/v1/remoteinput', json=test_metadata, timeout=5)
    assert req.status_code == 405


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows SQLite file locking issues with multiprocess webserver")
def test_webserver_remote_input_invalid_json(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test remote input endpoint with invalid JSON '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value('weboutput/httpport', type=int)

    # Test with invalid JSON
    req = requests.post(f'http://localhost:{port}/v1/remoteinput',
                        data='invalid json',
                        headers={'Content-Type': 'application/json'},
                        timeout=5)
    assert req.status_code == 400
    response_data = req.json()
    assert 'error' in response_data
