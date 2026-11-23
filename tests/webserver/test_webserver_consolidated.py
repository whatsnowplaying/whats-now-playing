#!/usr/bin/env python3
"""Consolidated webserver tests using aiohttp"""

import asyncio
import base64
import json
import sys

import aiohttp
import pytest
import websockets

import nowplaying.db
import nowplaying.metadata.processors
import nowplaying.trackrequests
import nowplaying.webserver.auth
from tests.utils_images import jpeg_bytes
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
    template_path = str(config.getbundledir().joinpath("templates", "basic-plain.txt"))
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


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
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


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret_config,request_secret,auth_location,expected_status",
    [
        (None, None, None, 200),  # No secret configured - should accept any request
        ("test_secret", "test_secret", "header", 200),  # Correct secret via header
        ("test_secret", "wrong_secret", "header", 403),  # Wrong secret via header
        ("test_secret", "test_secret", "body", 200),  # Correct secret via legacy body field
        ("test_secret", "wrong_secret", "body", 403),  # Wrong secret via legacy body field
        ("test_secret", None, None, 403),  # Missing secret when required
    ],
)
async def test_webserver_remote_input_authentication(
    getwebserver, secret_config, request_secret, auth_location, expected_status
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
    headers = {}
    if request_secret and auth_location == "header":
        headers[nowplaying.webserver.auth.CLIENT_AUTH_HEADER] = request_secret
    elif request_secret and auth_location == "body":
        test_metadata["secret"] = request_secret

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"http://localhost:{port}/v1/remoteinput",
            json=test_metadata,
            headers=headers,
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


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "submitted_coverurl",
    [
        # protocol-relative: resolves against the browser source's own scheme, and
        # skips the http fetch, so nothing sets coverimageraw to trigger an overwrite
        "//evil.example/x.png",
        # renders directly from an img src, no fetch at all
        "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=",
        "ftp://evil.example/x.png",
        "javascript:alert(1)",
        # shape-legal, so only the inequality check catches this one surviving
        "cover/../../../etc/passwd",
    ],
)
async def test_webserver_remote_input_drops_submitted_coverurl(getwebserver, submitted_coverurl):
    """a submitted coverurl must never survive into the metadata templates render

    Templates use coverurl as an img src inside an OBS browser source, so a value that
    outlives the handler is a fetch the DJ's overlay performs on the submitter's behalf.
    processors.py supplies the real relative value once it knows where the art landed.
    """
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    test_metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "filename": "test.mp3",
        "coverurl": submitted_coverurl,
    }

    async with (
        aiohttp.ClientSession() as session,
        session.post(
            f"http://localhost:{port}/v1/remoteinput",
            json=test_metadata,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req,
    ):
        assert req.status == 200
        processed = (await req.json())["processed_metadata"]

    # Assert the shape, not merely "not what was submitted": != would also accept a
    # mangled version of the submitted URL.  Every legitimate value is relative and
    # WNP-generated -- absent when the track has no art, the singleton when it has art
    # but no cachekey to address it by, and the keyed route on a datacache hit.  Which
    # one appears is not stable: this track has no album, so it keys on artist+title
    # and _process_cover_images does a retrieve_by_identifier against the datacache
    # that every test shares, so art cached under that key elsewhere flips the answer.
    coverurl = processed.get("coverurl", "")
    assert coverurl in (
        "",
        nowplaying.metadata.processors.COVER_SINGLETON_URL,
    ) or coverurl.startswith(nowplaying.metadata.processors.COVER_KEYED_PREFIX)
    # and not merely shape-legal: a submitter can name "cover/anything" too
    assert coverurl != submitted_coverurl


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
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


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
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
            "secret": "test_secret",  # pragma: allowlist secret
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


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_webserver_remote_input_source_agent(getwebserver):
    """test that source_agent_name and source_agent_version pass through remote input"""
    config, metadb = getwebserver  # pylint: disable=unused-variable
    port = config.cparser.value("weboutput/httpport", type=int)

    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    async with aiohttp.ClientSession() as session:
        # Test with both fields present
        test_metadata = {
            "artist": "Test Artist",
            "title": "Test Title",
            "source_agent_name": "WNPListener",
            "source_agent_version": "1.2.3",
        }
        async with session.post(
            f"http://localhost:{port}/v1/remoteinput",
            json=test_metadata,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200
            response_data = await req.json()
            processed = response_data["processed_metadata"]
            assert processed["source_agent_name"] == "WNPListener"
            assert processed["source_agent_version"] == "1.2.3"

        # Test with only name present (version omitted by client)
        test_metadata_name_only = {
            "artist": "Test Artist",
            "title": "Test Title",
            "source_agent_name": "WNPListener",
        }
        async with session.post(
            f"http://localhost:{port}/v1/remoteinput",
            json=test_metadata_name_only,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200
            response_data = await req.json()
            processed = response_data["processed_metadata"]
            assert processed["source_agent_name"] == "WNPListener"
            assert (
                "source_agent_version" not in processed
                or processed["source_agent_version"] is None
            )

        # Test without source_agent fields (legacy client) — should still work fine
        test_metadata_legacy = {
            "artist": "Test Artist",
            "title": "Test Title",
        }
        async with session.post(
            f"http://localhost:{port}/v1/remoteinput",
            json=test_metadata_legacy,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200
            response_data = await req.json()
            processed = response_data["processed_metadata"]
            assert processed["artist"] == "Test Artist"


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        "/?preview=1",
        "/index.html?preview=1",
        "/index.htm?preview=1",
    ],
)
async def test_webserver_preview_empty_db(getwebserver, endpoint):
    """preview mode renders sample data when no metadata is in the DB"""
    config, _metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    template_path = config.getbundledir().joinpath("templates", "basic-plain.txt")
    config.cparser.setValue("weboutput/htmltemplate", str(template_path))
    config.cparser.setValue("weboutput/once", True)
    config.cparser.sync()

    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"http://localhost:{port}{endpoint}", timeout=aiohttp.ClientTimeout(total=5)
        ) as req:
            assert req.status == 200
            text = await req.text()
            # basic-plain.txt renders "{{ artist }} - {{ title }}"
            assert "Sample Artist" in text
            assert "Sample Track Title" in text


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_webserver_preview_uses_live_metadata(getwebserver):
    """preview mode uses live metadata from DB when a track is playing"""
    config, metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    template_path = config.getbundledir().joinpath("templates", "basic-plain.txt")
    config.cparser.setValue("weboutput/htmltemplate", str(template_path))
    config.cparser.setValue("weboutput/once", False)
    config.cparser.sync()

    await metadb.write_to_metadb(metadata={"artist": "Live Artist", "title": "Live Title"})

    webserver_ready = await wait_for_webserver_ready(port, timeout=10.0)
    if not webserver_ready:
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"http://localhost:{port}/?preview=1", timeout=aiohttp.ClientTimeout(total=5)
        ) as req:
            assert req.status == 200
            text = await req.text()
            assert "Live Artist" in text
            assert "Live Title" in text


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_cover_by_cachekey_unknown_key_is_404(getwebserver):
    """An unknown cachekey is refused rather than answered with a placeholder.

    /cover.png falls back to a transparent PNG so template code stays simple, but a
    caller of the keyed route supplied a key: a miss means that key is stale, and
    saying so lets the client go re-read the frame instead of rendering nothing.

    The hit path is covered at the storage layer in tests/datacache/test_storage.py;
    seeding the webserver subprocess's datacache from here is not worth the wiring.
    """
    config, _metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    async with (
        aiohttp.ClientSession() as session,
        session.get(
            f"http://localhost:{port}/cover/not-a-real-cachekey",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as req,
    ):
        assert req.status == 404


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_events_connect_sends_connected_frame_first(getwebserver):
    """the very first frame is a server-minted, per-connection-unique session id

    Never a query param -- there is no preceding .htm render for /v1/events to
    relay one from, unlike /wsstream et al., so the id has to be minted here.
    """
    config, _metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    async with websockets.connect(f"ws://localhost:{port}/v1/events") as ws1:
        first1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=10))
        async with websockets.connect(f"ws://localhost:{port}/v1/events") as ws2:
            first2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=10))

    assert first1["type"] == "connected"
    assert first2["type"] == "connected"
    session_id1 = first1["payload"]["session_id"]
    session_id2 = first2["payload"]["session_id"]
    assert session_id1
    assert session_id2
    assert session_id1 != session_id2


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_events_connect_honors_client_session_header(getwebserver):
    """a well-formed X-WNP-Client-Session is echoed back verbatim"""
    config, _metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    async with websockets.connect(
        f"ws://localhost:{port}/v1/events",
        additional_headers={"X-WNP-Client-Session": "my-lumia-session-42"},
    ) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))

    assert first == {
        "type": "connected",
        "timestamp": first["timestamp"],
        "payload": {"session_id": "my-lumia-session-42"},
    }


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_events_connect_sends_snapshot(getwebserver):
    """after connected: current track, one request-added per row, then snapshot-complete

    snapshot-complete is the deterministic alternative to a client-side debounce
    timer for "is the initial request-added burst finished yet".
    """
    config, metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    config.cparser.setValue("settings/requests", True)
    config.cparser.sync()

    await metadb.write_to_metadb(
        metadata={
            "artist": "WNP Mock Artist",
            "title": "WNP Mock Song",
            "coverimageraw": jpeg_bytes(),
        }
    )
    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"http://localhost:{port}/v1/requests", timeout=aiohttp.ClientTimeout(total=5)
        ) as req:
            assert req.status == 200
        async with session.post(
            f"http://localhost:{port}/v1/requests",
            json={"requester": "viewer1", "artist": "Radiohead", "title": "Creep"},
            timeout=aiohttp.ClientTimeout(total=5),
        ) as req:
            assert req.status == 200

    async with websockets.connect(f"ws://localhost:{port}/v1/events") as ws:
        connected = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        track_update = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        request_added = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        snapshot_complete = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))

    assert connected["type"] == "connected"
    assert track_update["type"] == "track-update"
    assert track_update["payload"]["artist"] == "WNP Mock Artist"
    for key in nowplaying.db.METADATABLOBLIST:
        assert key not in track_update["payload"]
    assert "dbid" not in track_update["payload"]
    assert request_added["type"] == "request-added"
    assert request_added["payload"]["artist"] == "Radiohead"
    assert request_added["payload"]["title"] == "Creep"
    assert snapshot_complete["type"] == "snapshot-complete"
    assert snapshot_complete["payload"]["request_count"] == 1


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_events_broadcasts_track_update_on_change(getwebserver):
    """a live write_to_metadb after connecting produces a fresh track-update frame"""
    config, metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    async with websockets.connect(f"ws://localhost:{port}/v1/events") as ws:
        await asyncio.wait_for(ws.recv(), timeout=10)  # connected
        # No snapshot frame necessarily follows: getwebserver's metadb and request
        # queue both start empty, so there is nothing to send until something
        # actually changes -- scan by type/content rather than assume a fixed count.

        await metadb.write_to_metadb(metadata={"artist": "Depeche Mode", "title": "Strangelove"})

        frame = None
        for _ in range(5):
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if (
                frame["type"] == "track-update"
                and frame["payload"].get("artist") == "Depeche Mode"
            ):
                break
        assert frame is not None
        assert frame["type"] == "track-update"
        assert frame["payload"]["artist"] == "Depeche Mode"
        assert frame["payload"]["title"] == "Strangelove"


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_events_broadcasts_request_added_and_removed(getwebserver):
    """POST /v1/requests -> request-added; DELETE that id -> request-removed with the full row"""
    config, _metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    config.cparser.setValue("settings/requests", True)
    config.cparser.sync()

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"http://localhost:{port}/v1/requests", timeout=aiohttp.ClientTimeout(total=5)
        ) as req:
            assert req.status == 200

        async with websockets.connect(f"ws://localhost:{port}/v1/events") as ws:
            await asyncio.wait_for(ws.recv(), timeout=10)  # connected
            # Queue is empty after the clear above, so the snapshot phase is just
            # "connected" then "snapshot-complete" (request_count=0) -- no need to
            # drain it explicitly, the scan-by-type loop below skips past it.

            async with session.post(
                f"http://localhost:{port}/v1/requests",
                json={"requester": "viewer1", "artist": "Pet Shop Boys", "title": "Heart"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as req:
                assert req.status == 200

            added = None
            for _ in range(5):
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if frame["type"] == "request-added":
                    added = frame
                    break
            assert added is not None
            assert added["payload"]["artist"] == "Pet Shop Boys"
            reqid = added["payload"]["request_id"]

            async with session.delete(
                f"http://localhost:{port}/v1/requests/{reqid}",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as req:
                assert req.status == 200

            removed = None
            for _ in range(5):
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if frame["type"] == "request-removed":
                    removed = frame
                    break
            assert removed is not None
            assert removed["payload"]["request_id"] == reqid
            assert removed["payload"]["artist"] == "Pet Shop Boys"
            assert removed["payload"]["title"] == "Heart"


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_events_broadcasts_request_updated_on_respin(getwebserver):
    """An in-place UPDATE to an existing reqid (what respin does) -> request-updated,
    never a request-removed/request-added pair -- a consumer should never see a
    transient empty slot for a row that never actually left the queue."""
    config, _metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    config.cparser.setValue("settings/requests", True)
    config.cparser.sync()

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"http://localhost:{port}/v1/requests", timeout=aiohttp.ClientTimeout(total=5)
        ) as req:
            assert req.status == 200

        async with websockets.connect(f"ws://localhost:{port}/v1/events") as ws:
            await asyncio.wait_for(ws.recv(), timeout=10)  # connected

            async with session.post(
                f"http://localhost:{port}/v1/requests",
                json={"requester": "viewer1", "artist": "Pet Shop Boys", "title": "Heart"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as req:
                assert req.status == 200

            added = None
            for _ in range(5):
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if frame["type"] == "request-added":
                    added = frame
                    break
            assert added is not None
            reqid = added["payload"]["request_id"]

            # Respin's own UPDATE (trackrequests.py: user_roulette_request -> add_to_db
            # with reqid set) rewrites artist/title/etc. in place on the same row rather
            # than deleting and re-inserting. Drive that exact code path directly --
            # there is no REST endpoint for it, respin is only reachable from the
            # roulette poller -- against the same request.db the webserver subprocess
            # is watching, so this is a real UPDATE, not a simulated one.
            reqs = nowplaying.trackrequests.Requests(config)
            await reqs.add_to_db(
                {
                    "reqid": reqid,
                    "username": "viewer1",
                    "playlist": "",
                    "type": "Roulette",
                    "displayname": "",
                    "artist": "Pet Shop Boys",
                    "title": "West End Girls",
                }
            )

            updated = None
            saw_added_or_removed = False
            for _ in range(5):
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if frame["type"] == "request-updated":
                    updated = frame
                    break
                if frame["type"] in ("request-added", "request-removed"):
                    saw_added_or_removed = True
            assert not saw_added_or_removed
            assert updated is not None
            assert updated["payload"]["request_id"] == reqid
            assert updated["payload"]["artist"] == "Pet Shop Boys"
            assert updated["payload"]["title"] == "West End Girls"


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret_config,client_header,query_secret,expected_status",
    [
        (None, None, None, 200),
        ("test_secret", "test_secret", None, 200),
        ("test_secret", "wrong_secret", None, 403),
        ("test_secret", None, None, 401),
        # Header-preferred, ?secret= as the legacy fallback -- same contract as
        # every REST endpoint.  Not optional: the browser WebSocket() constructor
        # cannot set custom headers at all, so this is the only path a
        # browser-rendered consumer of this stream would ever have.
        ("test_secret", None, "test_secret", 200),
        ("test_secret", None, "wrong_secret", 403),
    ],
)
async def test_events_auth(
    getwebserver, secret_config, client_header, query_secret, expected_status
):
    """header preferred, ?secret= query param as the browser-compatible fallback"""
    config, _metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    if secret_config:
        config.cparser.setValue("remote/remote_key", secret_config)
    config.cparser.sync()

    headers = {}
    if client_header:
        headers[nowplaying.webserver.auth.CLIENT_AUTH_HEADER] = client_header
    url = f"ws://localhost:{port}/v1/events"
    if query_secret:
        url += f"?secret={query_secret}"

    if expected_status == 200:
        async with websockets.connect(url, additional_headers=headers) as ws:
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            assert frame["type"] == "connected"
    else:
        with pytest.raises(websockets.exceptions.InvalidStatus) as excinfo:
            async with websockets.connect(url, additional_headers=headers):
                pass
        assert excinfo.value.response.status_code == expected_status


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_events_ignores_client_messages(getwebserver):
    """publish-only: sending text from the client doesn't close the connection or do anything"""
    config, metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    async with websockets.connect(f"ws://localhost:{port}/v1/events") as ws:
        await asyncio.wait_for(ws.recv(), timeout=10)  # connected

        await ws.send("some arbitrary client text, not a command")

        await metadb.write_to_metadb(metadata={"artist": "Yazoo", "title": "Situation"})

        frame = None
        for _ in range(5):
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if frame["type"] == "track-update" and frame["payload"].get("artist") == "Yazoo":
                break
        assert frame is not None
        assert ws.close_code is None  # still open


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_wsstream_transcodes_banner_and_thumbnail(getwebserver):
    """/wsstream converts genuine artist banner/thumbnail JPEGs to PNG, not just the cover.

    Found by live testing: several bundled templates hardcode data:image/png for
    artistbannerbase64 and artistthumbnailbase64 too.  _wss_do_update's rebuild is
    gated on the DB watcher's updatetime (a genuine track change), unlike
    websocket_artistfanart_streamer's unconditional per-fanartdelay-tick rebuild, so
    opting these two in here does not reintroduce the per-tick re-encode cost that was
    walked back earlier.

    Fanart is deliberately excluded from utils_images.py's fixtures here: write_to_metadb
    nulls artistfanartraw unconditionally (db.py) -- it is populated live, per-connection,
    only inside websocket_artistfanart_streamer's own datacache lookup, never from metadb.
    The fanart-stays-untouched guarantee is exercised directly against _base64ifier in
    test_webserver_base64ifier.py, which does not go through metadb at all.
    """
    config, metadb = getwebserver
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")

    await metadb.write_to_metadb(
        metadata={
            "artist": "WNP Mock Artist",
            "title": "WNP Mock Song",
            "coverimageraw": jpeg_bytes(),
            "artistbannerraw": jpeg_bytes(color=(10, 10, 200)),
            "artistthumbnailraw": jpeg_bytes(color=(200, 10, 10)),
        }
    )

    async with websockets.connect(f"ws://localhost:{port}/wsstream") as ws:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))

    assert base64.b64decode(frame["artistbannerbase64"]).startswith(b"\x89PNG\r\n\x1a\n")
    assert base64.b64decode(frame["artistthumbnailbase64"]).startswith(b"\x89PNG\r\n\x1a\n")
    assert base64.b64decode(frame["coverimagebase64"]).startswith(b"\x89PNG\r\n\x1a\n")
