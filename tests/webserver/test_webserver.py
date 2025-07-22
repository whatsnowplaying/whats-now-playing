#!/usr/bin/env python3
"""test webserver"""

import asyncio
import logging
import sys

import pytest
import requests

import nowplaying.processes.webserver
from tests.webserver.conftest import wait_for_webserver_content_update, wait_for_webserver_ready


@pytest.mark.asyncio
async def test_startstopwebserver(getwebserver):  # pylint: disable=redefined-outer-name
    """test a simple start/stop"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue("weboutput/httpenabled", "true")
    config.cparser.sync()

    # Poll webserver until ready instead of fixed sleep
    port = config.cparser.value("weboutput/httpport", type=int)
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
@pytest.mark.asyncio
async def test_webserver_htmtest(getwebserver):  # pylint: disable=redefined-outer-name
    """start webserver, read existing data, add new data, then read that"""
    config, metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    config.cparser.setValue(
        "weboutput/htmltemplate", config.getbundledir().joinpath("templates", "basic-plain.txt")
    )
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    # Poll webserver until ready instead of fixed sleep
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    logging.debug(config.cparser.value("weboutput/htmltemplate"))
    # handle no data, should return refresh

    req = requests.get(f"http://localhost:{port}/index.html", timeout=5)
    assert req.status_code == 202
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

    # handle first write

    await metadb.write_to_metadb(metadata={"title": "testhtmtitle", "artist": "testhtmartist"})

    # Poll for content update instead of fixed sleep
    content_ready, response_text = await wait_for_webserver_content_update(
        port, "/index.html", expected_content=" testhtmartist - testhtmtitle", timeout=5.0
    )
    assert content_ready, "Webserver content failed to update within 5 seconds"
    assert response_text == " testhtmartist - testhtmtitle"

    # another read should give us refresh

    await asyncio.sleep(0.1)  # Small delay for processing
    req = requests.get(f"http://localhost:{port}/index.html", timeout=5)
    assert req.status_code == 200
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

    config.cparser.setValue("weboutput/once", False)
    config.cparser.sync()

    # flipping once to false should give us back same info

    await asyncio.sleep(0.1)  # Small delay for config to take effect
    req = requests.get(f"http://localhost:{port}/index.html", timeout=5)
    assert req.status_code == 200
    assert req.text == " testhtmartist - testhtmtitle"

    # handle second write

    await metadb.write_to_metadb(
        metadata={
            "artist": "artisthtm2",
            "title": "titlehtm2",
        }
    )

    # Poll for content update instead of fixed sleep
    content_ready, response_text = await wait_for_webserver_content_update(
        port, "/index.html", expected_content=" artisthtm2 - titlehtm2", timeout=5.0
    )
    assert content_ready, "Webserver content failed to update within 5 seconds"
    assert response_text == " artisthtm2 - titlehtm2"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
@pytest.mark.asyncio
async def test_webserver_txttest(getwebserver):  # pylint: disable=redefined-outer-name,too-many-statements
    """start webserver, read existing data, add new data, then read that"""
    config, metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    config.cparser.setValue("weboutput/httpenabled", "true")
    config.cparser.setValue(
        "weboutput/htmltemplate", config.getbundledir().joinpath("templates", "basic-plain.txt")
    )
    config.cparser.setValue(
        "textoutput/txttemplate", config.getbundledir().joinpath("templates", "basic-plain.txt")
    )
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    # Poll webserver until ready instead of fixed sleep
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    # handle no data, should return refresh

    req = requests.get(f"http://localhost:{port}/index.txt", timeout=5)
    assert req.status_code == 200
    assert req.text == ""  # sourcery skip: simplify-empty-collection-comparison

    # should return empty
    req = requests.get(f"http://localhost:{port}/v1/last", timeout=5)
    assert req.status_code == 200
    assert req.json() == {}
    # handle first write

    await metadb.write_to_metadb(metadata={"title": "testtxttitle", "artist": "testtxtartist"})

    # Poll for content update instead of fixed sleep
    content_ready, _ = await wait_for_webserver_content_update(
        port, "/index.txt", expected_content=" testtxtartist - testtxttitle", timeout=5.0
    )
    assert content_ready, "Webserver content failed to update within 5 seconds"

    req = requests.get(f"http://localhost:{port}/index.txt", timeout=5)
    assert req.status_code == 200
    assert req.text == " testtxtartist - testtxttitle"

    req = requests.get(f"http://localhost:{port}/v1/last", timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata["artist"] == "testtxtartist"
    assert checkdata["title"] == "testtxttitle"
    assert not checkdata.get("dbid")

    # another read should give us same info

    await asyncio.sleep(0.1)  # Small delay for processing
    req = requests.get(f"http://localhost:{port}/index.txt", timeout=5)
    assert req.status_code == 200
    assert req.text == " testtxtartist - testtxttitle"

    req = requests.get(f"http://localhost:{port}/v1/last", timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata["artist"] == "testtxtartist"
    assert checkdata["title"] == "testtxttitle"
    assert not checkdata.get("dbid")

    # handle second write

    await metadb.write_to_metadb(
        metadata={
            "artist": "artisttxt2",
            "title": "titletxt2",
        }
    )

    # Poll for content update instead of fixed sleep
    content_ready, _ = await wait_for_webserver_content_update(
        port, "/index.txt", expected_content=" artisttxt2 - titletxt2", timeout=5.0
    )
    assert content_ready, "Webserver content failed to update within 5 seconds"

    req = requests.get(f"http://localhost:{port}/index.txt", timeout=5)
    assert req.status_code == 200
    assert req.text == " artisttxt2 - titletxt2"

    req = requests.get(f"http://localhost:{port}/v1/last", timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata["artist"] == "artisttxt2"
    assert checkdata["title"] == "titletxt2"
    assert not checkdata.get("dbid")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
@pytest.mark.xfail(sys.platform == "darwin", reason="timesout on macos")
def test_webserver_gifwordstest(getwebserver):  # pylint: disable=redefined-outer-name
    """make sure gifwords works"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    req = requests.get(f"http://localhost:{port}/gifwords.htm", timeout=5)
    assert req.status_code == 200


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_coverpng(getwebserver):  # pylint: disable=redefined-outer-name
    """make sure coverpng works"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    req = requests.get(f"http://localhost:{port}/cover.png", timeout=5)
    assert req.status_code == 200


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_no_secret(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint without secret"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Test without secret configured - should accept any request
    test_metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=5)
    assert req.status_code == 200
    response_data = req.json()
    assert "dbid" in response_data


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_with_secret(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint with secret authentication"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Configure secret
    test_secret = "test_secret_123"  # pragma: allowlist secret
    config.cparser.setValue("remote/remote_key", test_secret)
    config.cparser.sync()

    test_metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "filename": "test.mp3",
        "secret": test_secret,
    }

    # Test with correct secret
    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=5)
    assert req.status_code == 200
    response_data = req.json()
    assert "dbid" in response_data


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_invalid_secret(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint with invalid secret"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Configure secret
    test_secret = "test_secret_123"  # pragma: allowlist secret
    config.cparser.setValue("remote/remote_key", test_secret)
    config.cparser.sync()

    test_metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "filename": "test.mp3",
        "secret": "wrong_secret",  # pragma: allowlist secret
    }

    # Test with wrong secret
    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=5)
    assert req.status_code == 403
    response_data = req.json()
    assert "error" in response_data


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_missing_secret(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint with missing secret"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Configure secret
    test_secret = "test_secret_123"  # pragma: allowlist secret
    config.cparser.setValue("remote/remote_key", test_secret)
    config.cparser.sync()

    test_metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "filename": "test.mp3",
        # No secret field
    }

    # Test without secret when required
    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=5)
    assert req.status_code == 403
    response_data = req.json()
    assert "error" in response_data


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_wrong_method(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint with wrong HTTP method"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    test_metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    # Test with GET instead of POST
    req = requests.get(f"http://localhost:{port}/v1/remoteinput", params=test_metadata, timeout=5)
    assert req.status_code == 405

    # Test with PUT instead of POST
    req = requests.put(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=5)
    assert req.status_code == 405


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_invalid_json(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint with invalid JSON"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Test with invalid JSON
    req = requests.post(
        f"http://localhost:{port}/v1/remoteinput",
        data="invalid json",
        headers={"Content-Type": "application/json"},
        timeout=5,
    )
    assert req.status_code == 400
    response_data = req.json()
    assert "error" in response_data
