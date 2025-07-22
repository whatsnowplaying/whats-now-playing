#!/usr/bin/env python3
"""test webserver artist-related endpoints"""

import sys
import time

import pytest
import requests


@pytest.fixture
def getwebserver(shared_webserver_config):
    """configure the webserver for artist endpoint tests"""
    config, metadb, manager, port = shared_webserver_config

    # Stop the shared webserver to avoid config conflicts
    manager.stop_all_processes()
    time.sleep(1)

    # Re-enable webserver settings
    config.cparser.setValue("weboutput/httpenabled", "true")
    config.cparser.setValue("weboutput/httpport", port)
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    # Recreate the database for clean test isolation
    metadb.setupsql()

    # Start a fresh webserver process
    manager.start_webserver()
    time.sleep(5)

    yield config, metadb

    # Stop the webserver again for next test
    manager.stop_all_processes()
    time.sleep(1)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_artistfanart_test(getwebserver):  # pylint: disable=redefined-outer-name
    """make sure artistfanart works"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    req = requests.get(f"http://localhost:{port}/artistfanart.htm", timeout=5)
    assert req.status_code == 202


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_banner_test(getwebserver):  # pylint: disable=redefined-outer-name
    """make sure banner works"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    req = requests.get(f"http://localhost:{port}/artistbanner.htm", timeout=5)
    assert req.status_code == 202

    req = requests.get(f"http://localhost:{port}/artistbanner.png", timeout=5)
    assert req.status_code == 200


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot close fast enough")
def test_webserver_logo_test(getwebserver):  # pylint: disable=redefined-outer-name
    """make sure banner works"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    req = requests.get(f"http://localhost:{port}/artistlogo.htm", timeout=5)
    assert req.status_code == 202

    req = requests.get(f"http://localhost:{port}/artistlogo.png", timeout=5)
    assert req.status_code == 200
