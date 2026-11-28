#!/usr/bin/env python3
"""test the /vendor/ handler"""

import pathlib

import aiohttp.test_utils
import pytest
from aiohttp import web

import nowplaying.config
import nowplaying.webserver.static_handlers

# pylint: disable=redefined-outer-name

CONFIG_KEY = web.AppKey("config", nowplaying.config.ConfigFile)


@pytest.fixture
def vendordirs(
    bootstrap: nowplaying.config.ConfigFile,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[nowplaying.config.ConfigFile, pathlib.Path, pathlib.Path]:
    """point the bundle and user templates at empty temp dirs"""
    config = bootstrap
    bundledir = tmp_path.joinpath("bundle")
    bundlevendor = bundledir.joinpath("templates", "vendor")
    bundlevendor.mkdir(parents=True)
    monkeypatch.setattr(nowplaying.config.ConfigFile, "BUNDLEDIR", bundledir)
    config.templatedir = tmp_path.joinpath("user", "templates")
    uservendor = config.templatedir.joinpath("vendor")
    uservendor.mkdir(parents=True)
    return config, bundlevendor, uservendor


async def _get_vendor(
    config: nowplaying.config.ConfigFile, vendor_file: str
) -> tuple[int, str, bytes]:
    """request a vendor file through the handler; return status, content type, body"""
    app = web.Application()
    app[CONFIG_KEY] = config
    handler = nowplaying.webserver.static_handlers.StaticContentHandler(
        config_key=CONFIG_KEY,
        ic_key=web.AppKey("ic"),
        metadb_key=web.AppKey("metadb"),
        remotedb_key=web.AppKey("remotedb"),
        metadata_key=web.AppKey("metadata"),
        http_session_key=web.AppKey("http_session"),
    )
    app.router.add_get("/vendor/{vendor_file}", handler.vendor_handler)
    async with (
        aiohttp.test_utils.TestClient(aiohttp.test_utils.TestServer(app)) as client,
        client.get(f"/vendor/{vendor_file}") as response,
    ):
        return response.status, response.content_type, await response.read()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "vendor_file,content,content_type",
    [
        ("userfont.woff2", b"\x00user-woff2", "font/woff2"),
        ("custom.woff", b"\x00user-woff", "font/woff"),
        ("custom.ttf", b"\x00user-ttf", "font/ttf"),
        ("custom.js", b"console.log('user');", "application/javascript"),
    ],
)
async def test_vendor_user_only(
    vendordirs: tuple[nowplaying.config.ConfigFile, pathlib.Path, pathlib.Path],
    vendor_file: str,
    content: bytes,
    content_type: str,
) -> None:
    """files missing from the bundle are served from the user's templates"""
    config, _, uservendor = vendordirs
    uservendor.joinpath(vendor_file).write_bytes(content)

    status, got_type, body = await _get_vendor(config, vendor_file)

    assert status == 200
    assert got_type == content_type
    assert body == content


@pytest.mark.asyncio
async def test_vendor_bundle_wins(
    vendordirs: tuple[nowplaying.config.ConfigFile, pathlib.Path, pathlib.Path],
) -> None:
    """the bundle's copy is served when both have the file"""
    config, bundlevendor, uservendor = vendordirs
    bundlevendor.joinpath("userfont.woff2").write_bytes(b"bundle")
    uservendor.joinpath("userfont.woff2").write_bytes(b"user")

    status, _, body = await _get_vendor(config, "userfont.woff2")

    assert status == 200
    assert body == b"bundle"


@pytest.mark.asyncio
async def test_vendor_missing(
    vendordirs: tuple[nowplaying.config.ConfigFile, pathlib.Path, pathlib.Path],
) -> None:
    """a file in neither place is a 404"""
    config, _, _ = vendordirs

    status, _, _ = await _get_vendor(config, "userfont.woff2")

    assert status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "vendor_file,status",
    [
        ("..%2Fsecret.woff2", 403),
        ("..%5Csecret.woff2", 403),
        ("a%5Csecret.woff2", 403),
        ("..secret.woff2", 403),
        ("sub%2Fsecret.woff2", 403),
        ("C%3Asecret.woff2", 403),
        ("secret.htm", 404),
    ],
)
async def test_vendor_rejects_bad_names(
    vendordirs: tuple[nowplaying.config.ConfigFile, pathlib.Path, pathlib.Path],
    vendor_file: str,
    status: int,
) -> None:
    """encoded traversal and disallowed extensions are rejected even if the file exists"""
    config, _, uservendor = vendordirs
    uservendor.parent.joinpath("secret.woff2").write_bytes(b"secret")
    uservendor.joinpath("sub").mkdir()
    uservendor.joinpath("sub", "secret.woff2").write_bytes(b"secret")
    uservendor.joinpath("secret.htm").write_bytes(b"secret")

    got_status, _, body = await _get_vendor(config, vendor_file)

    assert got_status == status
    assert body != b"secret"


@pytest.mark.asyncio
async def test_vendor_symlink_escape(
    vendordirs: tuple[nowplaying.config.ConfigFile, pathlib.Path, pathlib.Path],
) -> None:
    """a symlink in the user's vendor/ pointing outside it is not served"""
    config, _, uservendor = vendordirs
    outside = uservendor.parent.joinpath("secret.woff2")
    outside.write_bytes(b"secret")
    try:
        uservendor.joinpath("link.woff2").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not available")

    status, _, body = await _get_vendor(config, "link.woff2")

    assert status == 404
    assert body != b"secret"
