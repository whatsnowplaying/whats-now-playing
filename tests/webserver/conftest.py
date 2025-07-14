#!/usr/bin/env python3
"""shared fixtures for webserver tests"""

import asyncio
import contextlib
import logging
import os
import pathlib
import socket
import tempfile
import time
import unittest.mock

import pytest
import pytest_asyncio
import requests

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.subprocesses
from nowplaying.oauth2 import OAuth2Client

# pylint: disable=redefined-outer-name

def is_port_in_use(port: int) -> bool:
    """check if a port is in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("localhost", port)) == 0


async def wait_for_webserver_ready(port: int, timeout: float = 10.0) -> bool:
    """Poll webserver until it's ready or timeout"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        with contextlib.suppress(
            requests.exceptions.RequestException, requests.exceptions.ConnectionError
        ):
            response = requests.get(f"http://localhost:{port}/internals", timeout=2)
            if response.status_code == 200:
                return True
        await asyncio.sleep(0.1)
    return False


async def wait_for_webserver_content_update(
    port: int, endpoint: str, expected_content: str | None = None, timeout: float = 5.0
) -> tuple[bool, str]:
    """Poll webserver endpoint until content is
        updated with expected content or status 200, or timeout

    Returns (success, response_text) tuple
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        with contextlib.suppress(
            requests.exceptions.RequestException, requests.exceptions.ConnectionError
        ):
            response = requests.get(f"http://localhost:{port}{endpoint}", timeout=2)
            if response.status_code == 200 and (
                expected_content is None or expected_content in response.text
            ):
                return True, response.text
        await asyncio.sleep(0.1)
    return False, ""


@pytest.fixture(scope="module")
def shared_webserver_config(pytestconfig):
    """module-scoped webserver configuration shared across all webserver tests"""
    with contextlib.suppress(PermissionError):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as newpath:
            dbinit_patch = unittest.mock.patch("nowplaying.db.MetadataDB.init_db_var")
            dbinit_mock = dbinit_patch.start()
            dbdir = pathlib.Path(newpath).joinpath("mdb")
            dbdir.mkdir()
            dbfile = dbdir.joinpath("test.db")
            dbinit_mock.return_value = dbfile

            with unittest.mock.patch.dict(
                os.environ,
                {"WNP_CONFIG_TEST_DIR": str(newpath), "WNP_METADB_TEST_FILE": str(dbfile)},
            ):
                bundledir = pathlib.Path(pytestconfig.rootpath).joinpath("nowplaying")
                nowplaying.bootstrap.set_qt_names(
                    domain="com.github.whatsnowplaying.testsuite", appname="testsuite"
                )
                config = nowplaying.config.ConfigFile(
                    bundledir=bundledir, logpath=newpath, testmode=True
                )
                config.cparser.setValue("acoustidmb/enabled", False)
                config.cparser.setValue("weboutput/httpenabled", "true")
                config.cparser.sync()

                metadb = nowplaying.db.MetadataDB(initialize=True)
                logging.debug("shared webserver databasefile = %s", metadb.databasefile)

                port = config.cparser.value("weboutput/httpport", type=int)
                logging.debug("checking %s for use", port)
                while is_port_in_use(port):
                    logging.debug("%s is in use; waiting", port)
                    time.sleep(2)

                manager = nowplaying.subprocesses.SubprocessManager(config=config, testmode=True)
                manager.start_webserver()

                # Wait for webserver to start
                timeout = 10.0
                start_time = time.time()
                while time.time() - start_time < timeout:
                    with contextlib.suppress(
                        requests.exceptions.RequestException, requests.exceptions.ConnectionError
                    ):
                        req = requests.get(f"http://localhost:{port}/internals", timeout=2)
                        if req.status_code == 200:
                            logging.debug("internals = %s", req.json())
                            break
                    time.sleep(0.1)
                else:
                    raise RuntimeError(
                        f"Webserver on port {port} failed to start within {timeout} seconds"
                    )

                yield config, metadb, manager, port

                manager.stop_all_processes()
                time.sleep(2)
                dbinit_mock.stop()


@pytest_asyncio.fixture
async def getwebserver(shared_webserver_config):
    """configure the webserver for standard tests"""
    config, metadb, manager, port = shared_webserver_config

    # Stop the shared webserver to avoid config conflicts
    manager.stop_all_processes()
    await asyncio.sleep(1)

    # Re-enable webserver settings
    config.cparser.setValue("weboutput/httpenabled", "true")
    config.cparser.setValue("weboutput/httpport", port)
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.sync()

    # Recreate the database for clean test isolation
    metadb.setupsql()

    # Start a fresh webserver process
    manager.start_webserver()

    # Wait for webserver to be ready
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to start within 10 seconds")

    yield config, metadb

    manager.stop_all_processes()
    await asyncio.sleep(1)


@pytest_asyncio.fixture
async def webserver_with_imagecache(shared_webserver_config):
    """configure webserver with ImageCache for Images WebSocket tests"""
    config, metadb, manager, port = shared_webserver_config

    # Stop the shared webserver to avoid config conflicts
    manager.stop_all_processes()
    await asyncio.sleep(1)

    # Re-enable webserver settings with artist extras
    config.cparser.setValue("weboutput/httpenabled", "true")
    config.cparser.setValue("weboutput/httpport", port)
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("artistextras/enabled", True)
    config.cparser.sync()

    # Recreate the database for clean test isolation
    metadb.setupsql()

    # Start a fresh webserver process
    manager.start_webserver()

    # Wait for webserver to be ready
    timeout = 10.0
    start_time = time.time()
    while time.time() - start_time < timeout:
        with contextlib.suppress(
            requests.exceptions.RequestException, requests.exceptions.ConnectionError
        ):
            req = requests.get(f"http://localhost:{port}/internals", timeout=2)
            if req.status_code == 200:
                break
        await asyncio.sleep(0.1)
    else:
        raise RuntimeError(f"Webserver on port {port} failed to start within {timeout} seconds")

    yield config, metadb, manager, port

    manager.stop_all_processes()
    await asyncio.sleep(1)


@pytest.fixture
def reset_oauth_state(shared_webserver_config):
    """reset OAuth state before each test"""
    config, metadb, _, port = shared_webserver_config

    # Re-enable webserver settings
    config.cparser.setValue("weboutput/httpenabled", "true")
    config.cparser.setValue("weboutput/httpport", port)
    config.cparser.sync()

    # Clear any OAuth state
    OAuth2Client.cleanup_stray_temp_credentials(config)
    config.cparser.remove("kick/clientid")
    config.cparser.remove("kick/redirecturi")
    config.cparser.sync()

    yield config, metadb
