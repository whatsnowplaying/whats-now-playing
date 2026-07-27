#!/usr/bin/env python3
"""Webserver tests for the Lumia song-request queue API"""

import sys

import aiohttp
import pytest

import nowplaying.webserver.auth
from tests.webserver.conftest import wait_for_webserver_ready

REQUEST_URL = "/v1/requests"


async def _ready(config):
    port = config.cparser.value("weboutput/httpport", type=int)
    if not await wait_for_webserver_ready(port, timeout=10.0):
        raise RuntimeError(f"Webserver on port {port} failed to respond within 10 seconds")
    return port


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_requests_enqueue_and_list(getwebserver):  # pylint: disable=redefined-outer-name
    """a Lumia-originated request is enqueued and appears in the queue snapshot"""
    config, _ = getwebserver
    config.cparser.setValue("settings/requests", True)
    config.cparser.sync()
    port = await _ready(config)

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 200

        async with session.post(
            f"http://localhost:{port}{REQUEST_URL}",
            json={
                "requester": "viewer1",
                "user_platform": "kick",
                "artist": "Radiohead",
                "title": "Creep",
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200
            data = await req.json()
            assert data["accepted"] is True
            assert data["track_id"]

        async with session.get(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 200
            data = await req.json()
            items = data["requests"]
            assert any(item["title"] == "Creep" for item in items)
            match = next(item for item in items if item["title"] == "Creep")
            assert match["request_origin"] == "lumia"
            assert match["user_platform"] == "kick"
            assert match["requester"] == "viewer1"


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret_config,request_secret,auth_location,expected_status",
    [
        (None, None, None, 200),
        ("test_secret", "test_secret", "header", 200),
        ("test_secret", "wrong_secret", "header", 403),
        ("test_secret", "test_secret", "body", 200),
        ("test_secret", "wrong_secret", "body", 403),
        ("test_secret", None, None, 403),
    ],
)
async def test_requests_authentication(
    getwebserver, secret_config, request_secret, auth_location, expected_status
):  # pylint: disable=redefined-outer-name
    """POST /v1/requests honors the shared secret via header or legacy body field"""
    config, _ = getwebserver
    config.cparser.setValue("settings/requests", True)
    if secret_config:
        config.cparser.setValue("remote/remote_key", secret_config)
    config.cparser.sync()
    port = await _ready(config)

    body = {"requester": "viewer1", "artist": "Radiohead", "title": "Creep"}
    headers = {}
    if request_secret and auth_location == "header":
        headers[nowplaying.webserver.auth.CLIENT_AUTH_HEADER] = request_secret
    elif request_secret and auth_location == "body":
        body["secret"] = request_secret

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"http://localhost:{port}{REQUEST_URL}",
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == expected_status


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_requests_header_auth_avoids_query_string(getwebserver):  # pylint: disable=redefined-outer-name
    """GET and DELETE authenticate via header, so the secret stays out of the URL"""
    config, _ = getwebserver
    config.cparser.setValue("settings/requests", True)
    config.cparser.setValue("remote/remote_key", "test_secret")
    config.cparser.sync()
    port = await _ready(config)

    headers = {nowplaying.webserver.auth.CLIENT_AUTH_HEADER: "test_secret"}
    async with aiohttp.ClientSession() as session:
        # No secret at all is rejected on the query-parameter endpoints
        async with session.get(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 403

        async with session.get(
            f"http://localhost:{port}{REQUEST_URL}",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200

        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200

        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}/999999",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            # authenticated, so we get past 403 to a genuine "no such request"
            assert req.status == 404


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_requests_disabled(getwebserver):  # pylint: disable=redefined-outer-name
    """mutations are refused when disabled; the read returns an empty queue"""
    config, _ = getwebserver
    config.cparser.setValue("settings/requests", False)
    config.cparser.sync()
    port = await _ready(config)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"http://localhost:{port}{REQUEST_URL}",
            json={"requester": "viewer1", "artist": "Radiohead", "title": "Creep"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 403

        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 403

        async with session.get(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 200
            assert (await req.json())["requests"] == []


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_requests_delete_and_clear(getwebserver):  # pylint: disable=redefined-outer-name
    """single delete removes one entry; clear empties the queue"""
    config, _ = getwebserver
    config.cparser.setValue("settings/requests", True)
    config.cparser.sync()
    port = await _ready(config)

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 200

        for artist, title in (("Radiohead", "Creep"), ("Nirvana", "Breed")):
            async with session.post(
                f"http://localhost:{port}{REQUEST_URL}",
                json={"requester": "viewer1", "artist": artist, "title": title},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as req:
                assert req.status == 200

        async with session.get(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            items = (await req.json())["requests"]
            assert len(items) == 2
            victim = items[0]["request_id"]

        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}/{victim}",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200
            body = await req.json()
            assert body["deleted"] == 1
            assert body["request_id"] == victim

        async with session.get(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            items = (await req.json())["requests"]
            assert len(items) == 1

        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 200

        async with session.get(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            items = (await req.json())["requests"]
            assert items == []


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_requests_delete_by_identity(getwebserver):  # pylint: disable=redefined-outer-name
    """DELETE with artist/title/requester removes only that requester's request"""
    config, _ = getwebserver
    config.cparser.setValue("settings/requests", True)
    config.cparser.sync()
    port = await _ready(config)

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 200

        for requester in ("viewer1", "viewer2"):
            async with session.post(
                f"http://localhost:{port}{REQUEST_URL}",
                json={"requester": requester, "artist": "Radiohead", "title": "Creep"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as req:
                assert req.status == 200

        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}",
            params={"artist": "Radiohead", "title": "Creep", "requester": "viewer1"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200
            assert (await req.json())["deleted"] == 1

        async with session.get(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            items = (await req.json())["requests"]
            assert len(items) == 1
            assert items[0]["requester"] == "viewer2"


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_requests_delete_partial_identity_rejected(getwebserver):  # pylint: disable=redefined-outer-name
    """a partial identity (no artist+title) is a 400, never a broad delete or a clear-all"""
    config, _ = getwebserver
    config.cparser.setValue("settings/requests", True)
    config.cparser.sync()
    port = await _ready(config)

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 200

        async with session.post(
            f"http://localhost:{port}{REQUEST_URL}",
            json={"requester": "viewer1", "artist": "Radiohead", "title": "Creep"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 200

        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}",
            params={"requester": "viewer1"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 400

        async with session.get(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert len((await req.json())["requests"]) == 1


@pytest.mark.xfail(sys.platform == "darwin", reason="timeouts on macos CI")
@pytest.mark.asyncio
async def test_requests_delete_no_match_404(getwebserver):  # pylint: disable=redefined-outer-name
    """deleting a nonexistent request is a 404, not a silent deleted:0 — by id and by identity"""
    config, _ = getwebserver
    config.cparser.setValue("settings/requests", True)
    config.cparser.sync()
    port = await _ready(config)

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}", timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            assert req.status == 200

        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}",
            params={"artist": "Nobody", "title": "Nothing", "requester": "ghost"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 404

        async with session.delete(
            f"http://localhost:{port}{REQUEST_URL}/999999",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as req:
            assert req.status == 404
