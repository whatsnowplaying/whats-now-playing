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

    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=30)
    assert req.status_code == 200
    response_data = req.json()
    assert "dbid" in response_data
    assert "processed_metadata" in response_data
    assert response_data["processed_metadata"]["artist"] == "Test Artist"


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
    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=30)
    assert req.status_code == 200
    response_data = req.json()
    assert "dbid" in response_data
    assert "processed_metadata" in response_data
    # Secret should be stripped from processed metadata
    assert "secret" not in response_data["processed_metadata"]


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
    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=30)
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
    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=30)
    assert req.status_code == 403
    response_data = req.json()
    assert "error" in response_data


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_get_method(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint with GET method"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    test_metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    # Test with GET - should now work
    req = requests.get(f"http://localhost:{port}/v1/remoteinput", params=test_metadata, timeout=30)
    assert req.status_code == 200
    response_data = req.json()
    assert "dbid" in response_data
    assert "processed_metadata" in response_data

    # Negative test: GET with empty metadata (should still work, just return minimal processed data)
    req = requests.get(f"http://localhost:{port}/v1/remoteinput", params={}, timeout=30)
    assert req.status_code == 200
    response_data = req.json()
    assert "dbid" in response_data
    assert "processed_metadata" in response_data

    # Test with PUT - should still return 405
    req = requests.put(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=30)
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
        timeout=30,
    )
    assert req.status_code == 400
    response_data = req.json()
    assert "error" in response_data
    assert response_data["error"] == "Invalid JSON in request body"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_null_byte_stripping(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint strips null bytes from string fields"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Test data with null bytes (like radiologik sends)
    # using GET to avoid JSON serialization issues
    test_metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "isrc": "USWB10104747\x00\x00\x00",  # Null bytes at end
        "filename": "test.mp3",
    }

    req = requests.get(f"http://localhost:{port}/v1/remoteinput", params=test_metadata, timeout=30)
    assert req.status_code == 200
    response_data = req.json()
    assert "dbid" in response_data
    assert "processed_metadata" in response_data
    # Null bytes should be stripped and ISRC should be in list format
    # The metadata processing treats ISRC as a list field and deduplicates/sorts characters
    processed_isrc = response_data["processed_metadata"].get("isrc", [])
    assert isinstance(processed_isrc, list)
    # Check that the expected characters from "USWB10104747" are present (deduplicated and sorted)
    expected_chars = sorted(set("USWB10104747"))  # ['0', '1', '4', '7', 'B', 'S', 'U', 'W']
    assert processed_isrc == expected_chars
    # Ensure no null bytes in any ISRC items
    assert all("\x00" not in item for item in processed_isrc)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_field_length_limits(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint enforces field length limits"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Test data with oversized field (1000+ characters)
    very_long_title = "x" * 1500  # Exceeds MAX_FIELD_LENGTH of 1000
    test_metadata = {
        "artist": "Test Artist",
        "title": very_long_title,
        "filename": "test.mp3",
    }

    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=30)
    assert req.status_code == 200
    response_data = req.json()
    assert "dbid" in response_data
    assert "processed_metadata" in response_data
    # Title should be truncated to 1000 characters
    assert len(response_data["processed_metadata"]["title"]) == 1000
    assert response_data["processed_metadata"]["title"] == "x" * 1000


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows SQLite file locking issues with multiprocess webserver",
)
def test_webserver_remote_input_field_whitelisting(getwebserver):  # pylint: disable=redefined-outer-name
    """test remote input endpoint filters out excluded fields"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Test data with fields that should be filtered out
    # Note: Binary fields like coverimageraw can't be sent via JSON,
    # so we test with other filterable fields
    test_metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "filename": "test.mp3",
        "httpport": 8080,  # Should be filtered out
        "hostname": "testhost",  # Should be filtered out
        "dbid": 12345,  # Should be filtered out
        "secret": "test_secret",  # Should be filtered out
    }

    req = requests.post(f"http://localhost:{port}/v1/remoteinput", json=test_metadata, timeout=30)
    assert req.status_code == 200
    response_data = req.json()
    assert "dbid" in response_data  # Response dbid is different from input dbid
    assert "processed_metadata" in response_data

    processed = response_data["processed_metadata"]
    # Allowed fields should be present
    assert processed["artist"] == "Test Artist"
    assert processed["title"] == "Test Title"

    # Excluded fields should not be present
    assert "httpport" not in processed
    assert "hostname" not in processed
    assert "secret" not in processed
    assert "filename" not in processed  # Security: filename should be filtered
    # Note: input dbid is filtered out, but response has a new dbid from storage
