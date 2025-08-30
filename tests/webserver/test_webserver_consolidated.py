#!/usr/bin/env python3
"""Consolidated webserver tests using aiohttp"""

import aiohttp
import pytest

from tests.webserver.conftest import wait_for_webserver_content_update, wait_for_webserver_ready


@pytest.mark.asyncio
async def test_startstopwebserver(getwebserver):  # pylint: disable=redefined-outer-name
    """test basic webserver startup"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue("weboutput/httpenabled", "true")
    config.cparser.sync()

    # Poll webserver until ready instead of fixed sleep
    port = config.cparser.value("weboutput/httpport", type=int)
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template_type,endpoint,expected_content",
    [
        ("html", "/index.html", " testartist - testtitle"),
        ("txt", "/index.txt", " testartist - testtitle"),
    ],
)
async def test_webserver_templates(getwebserver, template_type, endpoint, expected_content):
    """test webserver template rendering"""
    config, metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)

    # Configure template
    template_path = config.getbundledir().joinpath("templates", "basic-plain.txt")
    if template_type == "html":
        config.cparser.setValue("weboutput/htmltemplate", template_path)
    else:
        config.cparser.setValue("textoutput/txttemplate", template_path)

    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    # Poll webserver until ready
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    # Write test metadata
    await metadb.write_to_metadb(metadata={"title": "testtitle", "artist": "testartist"})

    # Poll for content update
    content_ready, response_text = await wait_for_webserver_content_update(
        port, endpoint, expected_content=expected_content, timeout=5.0
    )
    assert content_ready, "Webserver content failed to update within 5 seconds"
    assert response_text == expected_content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        "/gifwords.htm",
        "/cover.png",
        "/artistfanart.htm",
        "/artistbanner.htm",
        "/artistbanner.png",
        "/artistlogo.htm",
        "/artistlogo.png",
    ],
)
async def test_webserver_static_endpoints(getwebserver, endpoint):
    """test webserver static endpoints return proper status codes"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"http://localhost:{port}{endpoint}", timeout=aiohttp.ClientTimeout(total=5)
        ) as req:
            # Most endpoints return 200 or 202, we just want to make sure they don't error
            assert req.status in (200, 202)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret_config,request_secret,expected_status",
    [
        (None, None, 200),  # No secret configured - should accept any request
        ("test_secret", "test_secret", 200),  # Correct secret
        ("test_secret", "wrong_secret", 403),  # Wrong secret
        ("test_secret", None, 403),  # Missing secret when required
    ],
)
async def test_webserver_remote_input_authentication(
    getwebserver, secret_config, request_secret, expected_status
):
    """test remote input endpoint authentication scenarios"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Configure secret if specified
    if secret_config:
        config.cparser.setValue("remote/remote_key", secret_config)
        config.cparser.sync()

    # Wait for webserver to be ready
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    # Prepare test metadata
    test_metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}
    if request_secret:
        test_metadata["secret"] = request_secret

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"http://localhost:{port}/v1/remoteinput",
            json=test_metadata,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == expected_status
            response_data = await req.json()

            if expected_status == 200:
                assert "dbid" in response_data
                assert "processed_metadata" in response_data
                assert response_data["processed_metadata"]["artist"] == "Test Artist"
                # Secret should be stripped from processed metadata
                assert "secret" not in response_data["processed_metadata"]
            else:
                assert "error" in response_data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,expected_status",
    [
        ("GET", 200),  # GET with query parameters
        ("POST", 200),  # POST with JSON body
        ("PUT", 405),  # PUT should return method not allowed
    ],
)
async def test_webserver_remote_input_http_methods(getwebserver, method, expected_status):
    """test remote input endpoint HTTP method support"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Wait for webserver to be ready
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    test_metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    async with aiohttp.ClientSession() as session:
        if method == "GET":
            async with session.get(
                f"http://localhost:{port}/v1/remoteinput",
                params=test_metadata,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as req:
                assert req.status == expected_status
        elif method == "POST":
            async with session.post(
                f"http://localhost:{port}/v1/remoteinput",
                json=test_metadata,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as req:
                assert req.status == expected_status
        elif method == "PUT":
            async with session.put(
                f"http://localhost:{port}/v1/remoteinput",
                json=test_metadata,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as req:
                assert req.status == expected_status


@pytest.mark.asyncio
async def test_webserver_remote_input_validation(getwebserver):
    """test remote input endpoint input validation and processing"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    # Wait for webserver to be ready
    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    async with aiohttp.ClientSession() as session:
        # Test invalid JSON
        async with session.post(
            f"http://localhost:{port}/v1/remoteinput",
            data="invalid json",
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 400
            response_data = await req.json()
            assert "error" in response_data
            assert response_data["error"] == "Invalid JSON in request body"

        # Test null byte stripping
        test_metadata_nulls = {
            "artist": "Test Artist",
            "title": "Test Title",
            "isrc": "USWB10104747\x00\x00\x00",  # Null bytes at end
            "filename": "test.mp3",
        }
        async with session.get(
            f"http://localhost:{port}/v1/remoteinput",
            params=test_metadata_nulls,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200
            response_data = await req.json()
            processed_isrc = response_data["processed_metadata"].get("isrc", [])
            assert all("\x00" not in item for item in processed_isrc)

        # Test field length limits
        very_long_title = "x" * 1500  # Exceeds MAX_FIELD_LENGTH of 1000
        test_metadata_long = {
            "artist": "Test Artist",
            "title": very_long_title,
            "filename": "test.mp3",
        }
        async with session.post(
            f"http://localhost:{port}/v1/remoteinput",
            json=test_metadata_long,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200
            response_data = await req.json()
            # Title should be truncated to 1000 characters
            assert len(response_data["processed_metadata"]["title"]) == 1000

        # Test field whitelisting/filtering
        test_metadata_filtered = {
            "artist": "Test Artist",
            "title": "Test Title",
            "filename": "test.mp3",
            "httpport": 8080,  # Should be filtered out
            "hostname": "testhost",  # Should be filtered out
            "dbid": 12345,  # Should be filtered out
            "secret": "test_secret",   # pragma: allowlist secret
        }
        async with session.post(
            f"http://localhost:{port}/v1/remoteinput",
            json=test_metadata_filtered,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200
            response_data = await req.json()
            processed = response_data["processed_metadata"]

            # Allowed fields should be present
            assert processed["artist"] == "Test Artist"
            assert processed["title"] == "Test Title"

            # Excluded fields should not be present
            assert "httpport" not in processed
            assert "hostname" not in processed
            assert "secret" not in processed
            assert "filename" not in processed  # Security: filename should be filtered
