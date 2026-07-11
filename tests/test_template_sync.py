#!/usr/bin/env python3
"""tests for charts base-template sync decision logic"""

# pylint: disable=redefined-outer-name

import hashlib
import json
import types

import pytest
import wnp_templates

from nowplaying.processes import template_sync

SERVER_CONTENT = b"<html>server-newer</html>"
SERVER_HASH = hashlib.sha256(SERVER_CONTENT).hexdigest()


class _StubResponse:  # pylint: disable=too-few-public-methods
    content = SERVER_CONTENT

    def raise_for_status(self) -> None:
        """always OK"""


class _StubClient:  # pylint: disable=too-few-public-methods
    def __init__(self):
        self.calls: list[str] = []

    async def get(self, url: str) -> _StubResponse:
        """record and serve stub content"""
        self.calls.append(url)
        return _StubResponse()


@pytest.fixture
def syncdirs(bootstrap, tmp_path):
    """conftest-bootstrapped config with an isolated user template tree"""
    bootstrap.templatedir = tmp_path / "templates"
    synced = bootstrap.templatedir / "synced"
    synced.mkdir(parents=True)
    (bootstrap.templatedir / "web").mkdir()
    return bootstrap, synced


def _wheel_hash(stem: str) -> str:
    path = wnp_templates.BUNDLED_TEMPLATE_DIR / f"{stem}.htm"
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _run_sync(config, synced, manifest, allow_downloads=True):
    client = _StubClient()
    await template_sync._sync_base_htms(  # pylint: disable=protected-access
        config, client, manifest, synced, allow_downloads=allow_downloads
    )
    return client.calls


@pytest.mark.asyncio
async def test_basesync_bundle_current_no_download(syncdirs):
    """manifest matching the bundled wheel downloads nothing"""
    config, synced = syncdirs
    calls = await _run_sync(
        config, synced, {"ws-mtv": {"url": "u", "checksum": _wheel_hash("ws-mtv")}}
    )
    assert not calls
    assert not list(synced.glob("*.htm"))


@pytest.mark.asyncio
async def test_basesync_server_newer_downloads_to_synced(syncdirs):
    """a newer server version lands in synced/ and is tracked"""
    config, synced = syncdirs
    calls = await _run_sync(config, synced, {"ws-mtv": {"url": "u", "checksum": SERVER_HASH}})
    assert calls == ["u"]
    assert (synced / "ws-mtv.htm").read_bytes() == SERVER_CONTENT
    manifest = json.loads((synced / ".wnp_base_sync.json").read_text())
    assert manifest == {"ws-mtv": SERVER_HASH}


@pytest.mark.asyncio
async def test_basesync_idempotent(syncdirs):
    """second run with the same manifest downloads nothing"""
    config, synced = syncdirs
    await _run_sync(config, synced, {"ws-mtv": {"url": "u", "checksum": SERVER_HASH}})
    calls = await _run_sync(config, synced, {"ws-mtv": {"url": "u", "checksum": SERVER_HASH}})
    assert not calls
    assert (synced / "ws-mtv.htm").exists()


@pytest.mark.asyncio
async def test_basesync_no_downloads_keeps_synced_copy(syncdirs):
    """downloads disabled (no server version) must never delete synced content"""
    config, synced = syncdirs
    await _run_sync(config, synced, {"ws-mtv": {"url": "u", "checksum": SERVER_HASH}})
    calls = await _run_sync(
        config, synced, {"ws-mtv": {"url": "u", "checksum": SERVER_HASH}}, allow_downloads=False
    )
    assert not calls
    assert (synced / "ws-mtv.htm").exists(), "cleanup must not regress users to older bundle"


@pytest.mark.asyncio
async def test_basesync_server_rollback_keeps_newer_copy(syncdirs):
    """server rolling back must not delete a synced copy the bundle lacks"""
    config, synced = syncdirs
    await _run_sync(config, synced, {"ws-mtv": {"url": "u", "checksum": SERVER_HASH}})
    await _run_sync(config, synced, {"ws-mtv": {"url": "u", "checksum": _wheel_hash("ws-mtv")}})
    assert (synced / "ws-mtv.htm").exists()


@pytest.mark.asyncio
async def test_basesync_user_override_never_touched(syncdirs):
    """a user-owned override blocks download and overwrite"""
    config, synced = syncdirs
    override = config.templatedir / "web" / "ws-mtv.htm"
    override.write_text("MY CUSTOM")
    calls = await _run_sync(config, synced, {"ws-mtv": {"url": "u", "checksum": SERVER_HASH}})
    assert not calls
    assert override.read_text() == "MY CUSTOM"
    assert not (synced / "ws-mtv.htm").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("stem", ["../evil", "/abs", "sub/dir", ".hidden", ""])
async def test_basesync_rejects_unsafe_stems(syncdirs, stem):
    """server-supplied stems must be plain filenames"""
    config, synced = syncdirs
    calls = await _run_sync(config, synced, {stem: {"url": "u", "checksum": SERVER_HASH}})
    assert not calls
    assert not list(config.templatedir.parent.rglob("evil.htm"))


@pytest.mark.parametrize(
    "server_version,expected",
    [
        ("0.0.1", False),
        ("999.0.0", True),
        ("", False),
        ("garbage", False),
    ],
)
def test_server_is_newer(server_version, expected):
    """direction gate: only strictly-newer servers enable downloads"""
    assert (
        template_sync._server_is_newer(server_version)  # pylint: disable=protected-access
        is expected
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        ("cooltheme", True),
        ("../evil", False),
        ("sub/dir", False),
        (".wnp_base_sync", False),
        ("", False),
    ],
)
def test_safe_filename(name, expected):
    """server-supplied names must be plain filenames"""
    assert template_sync._safe_filename(name) is expected  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_namedsync_transient_failure_keeps_previous(syncdirs, monkeypatch):
    """a transient base-download failure must not unlink a still-listed template"""
    config, synced = syncdirs
    config.cparser.setValue("charts/charts_key", "k" * 32)
    monkeypatch.setattr(
        template_sync.nowplaying.utils.charts_api, "is_valid_api_key", lambda key: True
    )
    monkeypatch.setattr(
        template_sync.nowplaying.utils.charts_api, "get_charts_base_url", lambda cfg: "http://x"
    )

    manifest = {
        "configs": [
            {"name": "good", "base_stem": "ws-mtv", "css_vars": {}},
            {"name": "flaky", "base_stem": "ws-broken", "css_vars": {}},
        ],
        "bases": {
            "ws-mtv": {"url": "http://x/a", "checksum": None},
            "ws-broken": {"url": "http://x/b", "checksum": None},
        },
        "missing": [],
    }

    async def fake_fetch(_url, _api_key):
        return manifest

    monkeypatch.setattr(template_sync, "_fetch_manifest", fake_fetch)

    # previous successful run: flaky.htm exists and is tracked; gone.htm was
    # tracked but the server no longer lists it
    (synced / "flaky.htm").write_text("previous good copy")
    (synced / "gone.htm").write_text("no longer on server")
    (synced / ".wnp_sync_manifest.json").write_text('["flaky", "gone"]')

    class StubDataCache:  # pylint: disable=too-few-public-methods
        """datacache client stub"""

        @staticmethod
        async def get_or_fetch(request):
            """base for 'good' succeeds; base for 'flaky' transiently fails"""
            if request.url.endswith("/a"):
                entry = types.SimpleNamespace(status_code=200, data=b"<html><body></body></html>")
                await request.on_complete(request.url, entry)
            else:
                await request.on_complete(request.url, None)

    await template_sync.sync_from_charts(config, StubDataCache())

    assert (synced / "good.htm").exists(), "successful assembly written"
    assert (synced / "flaky.htm").exists(), "transient failure must not unlink"
    assert not (synced / "gone.htm").exists(), "server-dropped template removed"
    manifest_names = json.loads((synced / ".wnp_sync_manifest.json").read_text())
    assert sorted(manifest_names) == ["flaky", "good"]


def test_assemble_rejects_unsafe_names(tmp_path):
    """server-supplied named-template names must be plain filenames"""
    configs = [
        {"name": "../evil", "base_stem": "s", "css_vars": {}},
        {"name": ".hidden", "base_stem": "s", "css_vars": {}},
        {"name": "fine", "base_stem": "s", "css_vars": {}},
    ]
    written = template_sync._assemble_templates(  # pylint: disable=protected-access
        configs, {"s": "<html><body></body></html>"}, tmp_path
    )
    assert written == {"fine"}
    assert not (tmp_path.parent / "evil.htm").exists()


def test_cleanup_stale_skips_unsafe_manifest_names(tmp_path):
    """hostile names in a manifest file must never drive unlinks"""
    (tmp_path / ".wnp_sync_manifest.json").write_text('["../evil", "old"]')
    (tmp_path / "old.htm").write_text("x")
    template_sync._cleanup_stale(tmp_path, set())  # pylint: disable=protected-access
    assert not (tmp_path / "old.htm").exists()
