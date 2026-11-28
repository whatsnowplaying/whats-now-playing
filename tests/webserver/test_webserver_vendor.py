#!/usr/bin/env python3
"""tests for the /vendor/ route: bundle first, then the user's templates/vendor/"""

# pylint: disable=redefined-outer-name

import pathlib

import aiohttp.test_utils
import pytest
from aiohttp import web

import nowplaying.config
import nowplaying.webserver.static_handlers

CONFIG_KEY = web.AppKey("config", nowplaying.config.ConfigFile)

VendorDirs = tuple[nowplaying.config.ConfigFile, pathlib.Path, pathlib.Path]


@pytest.fixture
def vendor_dirs(
    bootstrap: nowplaying.config.ConfigFile,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> VendorDirs:
    """point the bundle and user template dirs at empty scratch vendor dirs"""
    bundledir = tmp_path / "bundle"
    bundlevendor = bundledir / "templates" / "vendor"
    bundlevendor.mkdir(parents=True)
    uservendor = tmp_path / "user" / "templates" / "vendor"
    uservendor.mkdir(parents=True)
    monkeypatch.setattr(nowplaying.config.ConfigFile, "BUNDLEDIR", bundledir)
    monkeypatch.setattr(bootstrap, "templatedir", uservendor.parent)
    return bootstrap, bundlevendor, uservendor


async def _get(config: nowplaying.config.ConfigFile, name: str) -> tuple[int, bytes, str]:
    """GET /vendor/<name> through the real handler"""
    handler = nowplaying.webserver.static_handlers.StaticContentHandler(
        config_key=CONFIG_KEY,
        metadb_key=web.AppKey("metadb"),
        remotedb_key=web.AppKey("remotedb"),
        metadata_key=web.AppKey("metadata"),
        http_session_key=web.AppKey("http_session"),
        dc_storage_key=web.AppKey("dc_storage"),
    )
    app = web.Application()
    app[CONFIG_KEY] = config
    app.router.add_get("/vendor/{vendor_file}", handler.vendor_handler)
    async with aiohttp.test_utils.TestClient(aiohttp.test_utils.TestServer(app)) as client:
        resp = await client.get(f"/vendor/{name}")
        return resp.status, await resp.read(), resp.headers.get("Content-Type", "")


@pytest.mark.asyncio
async def test_vendor_user_only_file_served(vendor_dirs: VendorDirs) -> None:
    """a file only in the user's vendor/ is served from there"""
    config, _bundlevendor, uservendor = vendor_dirs
    (uservendor / "userfont.woff2").write_bytes(b"user font")
    status, body, ctype = await _get(config, "userfont.woff2")
    assert status == 200
    assert body == b"user font"
    assert ctype == "font/woff2"


@pytest.mark.asyncio
async def test_vendor_bundle_wins(vendor_dirs: VendorDirs) -> None:
    """when both have the file, the bundle copy is served"""
    config, bundlevendor, uservendor = vendor_dirs
    (bundlevendor / "jquery.min.js").write_bytes(b"bundle js")
    (uservendor / "jquery.min.js").write_bytes(b"user js")
    status, body, ctype = await _get(config, "jquery.min.js")
    assert status == 200
    assert body == b"bundle js"
    assert ctype == "application/javascript"


@pytest.mark.asyncio
async def test_vendor_missing_is_404(vendor_dirs: VendorDirs) -> None:
    """a file in neither location is a 404"""
    config, _bundlevendor, _uservendor = vendor_dirs
    status, _body, _ctype = await _get(config, "userfont.woff2")
    assert status == 404


@pytest.mark.parametrize(
    "name,expected",
    [
        ("notes.txt", 404),
        ("..%5Cuserfont.woff2", 403),
        ("a%5Cuserfont.woff2", 403),
        ("..userfont.woff2", 403),
        ("C%3Asecret.woff2", 403),
        ("sub%2Ffont.woff2", 403),
    ],
)
@pytest.mark.asyncio
async def test_vendor_rejects_bad_names(vendor_dirs: VendorDirs, name: str, expected: int) -> None:
    """disallowed extensions and traversal names never reach the user dir"""
    config, _bundlevendor, uservendor = vendor_dirs
    (uservendor / "notes.txt").write_bytes(b"not a vendor type")
    status, _body, _ctype = await _get(config, name)
    assert status == expected
