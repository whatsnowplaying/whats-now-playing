#!/usr/bin/env python3
"""Tests for the web-based template editor API handlers."""

# pylint: disable=redefined-outer-name

import pathlib

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.template_colors
from nowplaying.processes.webserver import CONFIG_KEY
from nowplaying.webserver.template_editor import TemplateEditorHandler

DOMAIN = "com.github.whatsnowplaying.testsuite"

_KNOWN_STEM = "ws-webgl-wave"
_UNKNOWN_STEM = "does-not-exist"


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(loop_scope="function")
async def editor_client(tmp_path, pytestconfig):
    """In-process aiohttp test client wired to TemplateEditorHandler."""
    bundledir = pathlib.Path(pytestconfig.rootpath) / "nowplaying"
    nowplaying.bootstrap.set_qt_names(domain=DOMAIN, appname="testsuite")
    config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)

    # Redirect templatedir into tmp_path so saves/resets don't touch the real tree.
    config.templatedir = tmp_path / "templates"
    config.templatedir.mkdir(parents=True, exist_ok=True)

    app = web.Application()
    app[CONFIG_KEY] = config

    handler = TemplateEditorHandler(config_key=CONFIG_KEY)
    app.router.add_get("/api/v1/editor/templates", handler.api_templates_handler)
    app.router.add_get("/api/v1/editor/templates/{stem}/vars", handler.api_vars_handler)
    app.router.add_post("/api/v1/editor/templates/{stem}/save", handler.api_save_handler)
    app.router.add_post("/api/v1/editor/templates/{stem}/reset", handler.api_reset_handler)
    app.router.add_get("/api/v1/editor/templates/{stem}/timing", handler.api_timing_get_handler)
    app.router.add_post("/api/v1/editor/templates/{stem}/timing", handler.api_timing_save_handler)

    async with TestClient(TestServer(app)) as client:
        yield client, config


# ── /api/v1/editor/templates ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_templates_returns_families(editor_client):
    """All known template families appear in the response."""
    client, _ = editor_client
    resp = await client.get("/api/v1/editor/templates")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, dict)
    assert len(data) > 0
    # All known families are present
    for family in nowplaying.template_colors.TEMPLATE_FAMILIES:
        assert family in data


@pytest.mark.asyncio
async def test_api_templates_only_includes_existing_files(editor_client):
    """Every stem in the response maps to a real .htm file on disk."""
    client, _ = editor_client
    resp = await client.get("/api/v1/editor/templates")
    data = await resp.json()
    bundled = nowplaying.template_colors.BUNDLED_TEMPLATE_DIR
    for _family, effects in data.items():
        for _label, stem in effects.items():
            assert (bundled / f"{stem}.htm").exists(), f"{stem}.htm missing from bundle"


# ── /api/v1/editor/templates/{stem}/vars ──────────────────────────────────────


@pytest.mark.asyncio
async def test_api_vars_unknown_stem_returns_404(editor_client):
    """Requesting vars for an unknown stem yields HTTP 404."""
    client, _ = editor_client
    resp = await client.get(f"/api/v1/editor/templates/{_UNKNOWN_STEM}/vars")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_api_vars_returns_defaults(editor_client):
    """Each variable entry has the required default/type/label/group fields."""
    client, _ = editor_client
    resp = await client.get(f"/api/v1/editor/templates/{_KNOWN_STEM}/vars")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) > 0
    for name, info in data.items():
        assert "default" in info, f"{name} missing 'default'"
        assert "type" in info, f"{name} missing 'type'"
        assert "label" in info, f"{name} missing 'label'"
        assert "group" in info, f"{name} missing 'group'"
        assert info["user"] is None, f"{name} should have no user override initially"


@pytest.mark.asyncio
async def test_api_vars_user_field_none_before_save(editor_client):
    """Before any save, every variable's user field is None."""
    client, _ = editor_client
    resp = await client.get(f"/api/v1/editor/templates/{_KNOWN_STEM}/vars")
    data = await resp.json()
    for info in data.values():
        assert info["user"] is None


# ── /api/v1/editor/templates/{stem}/save ─────────────────────────────────────


@pytest.mark.asyncio
async def test_api_save_unknown_stem_returns_404(editor_client):
    """Saving to an unknown stem yields HTTP 404."""
    client, _ = editor_client
    resp = await client.post(
        f"/api/v1/editor/templates/{_UNKNOWN_STEM}/save",
        json={"vars": {"wnp-accent-color": "#ff0000"}},
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_api_save_bad_json_returns_400(editor_client):
    """A malformed JSON body on save yields HTTP 400."""
    client, _ = editor_client
    resp = await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/save",
        data=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_api_save_creates_custom_file(editor_client):
    """A successful save creates the custom template file on disk."""
    client, config = editor_client
    resp = await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/save",
        json={"vars": {"wnp-accent-color": "#aabbcc"}},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True

    custom_path = config.templatedir / "custom" / f"{_KNOWN_STEM}.htm"
    assert custom_path.exists(), "Custom template file was not created"


@pytest.mark.asyncio
async def test_api_save_roundtrip(editor_client):
    """Save a color then read it back via vars endpoint."""
    client, _ = editor_client
    save_resp = await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/save",
        json={"vars": {"wnp-accent-color": "#123456"}},
    )
    assert save_resp.status == 200

    vars_resp = await client.get(f"/api/v1/editor/templates/{_KNOWN_STEM}/vars")
    data = await vars_resp.json()
    assert "wnp-accent-color" in data
    assert data["wnp-accent-color"]["user"] == "#123456"


@pytest.mark.asyncio
async def test_api_save_preserves_unset_vars_as_none(editor_client):
    """Vars not included in the save payload should still have user=None."""
    client, _ = editor_client
    await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/save",
        json={"vars": {"wnp-accent-color": "#aabbcc"}},
    )
    vars_resp = await client.get(f"/api/v1/editor/templates/{_KNOWN_STEM}/vars")
    data = await vars_resp.json()
    # A var that was NOT in the save payload should have no user override
    for name, info in data.items():
        if name != "wnp-accent-color":
            assert info["user"] is None, f"{name} should be None after partial save"
            break


# ── /api/v1/editor/templates/{stem}/reset ────────────────────────────────────


@pytest.mark.asyncio
async def test_api_reset_unknown_stem_returns_404(editor_client):
    """Resetting an unknown stem yields HTTP 404."""
    client, _ = editor_client
    resp = await client.post(f"/api/v1/editor/templates/{_UNKNOWN_STEM}/reset")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_api_reset_no_custom_file_is_noop(editor_client):
    """Reset with no existing custom file should succeed silently."""
    client, _ = editor_client
    resp = await client.post(f"/api/v1/editor/templates/{_KNOWN_STEM}/reset")
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_api_reset_removes_custom_file(editor_client):
    """Reset deletes the previously saved custom template file."""
    client, config = editor_client
    # Save first
    await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/save",
        json={"vars": {"wnp-accent-color": "#ff0000"}},
    )
    custom_path = config.templatedir / "custom" / f"{_KNOWN_STEM}.htm"
    assert custom_path.exists()

    # Reset
    resp = await client.post(f"/api/v1/editor/templates/{_KNOWN_STEM}/reset")
    assert resp.status == 200
    assert not custom_path.exists(), "Custom file should be deleted after reset"


@pytest.mark.asyncio
async def test_api_reset_clears_user_overrides(editor_client):
    """After reset, vars endpoint should show user=None for all vars."""
    client, _ = editor_client
    await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/save",
        json={"vars": {"wnp-accent-color": "#ff0000"}},
    )
    await client.post(f"/api/v1/editor/templates/{_KNOWN_STEM}/reset")

    resp = await client.get(f"/api/v1/editor/templates/{_KNOWN_STEM}/vars")
    data = await resp.json()
    for name, info in data.items():
        assert info["user"] is None, f"{name} still has user override after reset"


# ── /api/v1/editor/templates/{stem}/timing ───────────────────────────────────


@pytest.mark.asyncio
async def test_api_timing_get_unknown_stem_returns_404(editor_client):
    """GET timing for an unknown stem yields HTTP 404."""
    client, _ = editor_client
    resp = await client.get(f"/api/v1/editor/templates/{_UNKNOWN_STEM}/timing")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_api_timing_get_defaults_to_zero(editor_client):
    """Timing values default to 0 when none have been saved."""
    client, _ = editor_client
    resp = await client.get(f"/api/v1/editor/templates/{_KNOWN_STEM}/timing")
    assert resp.status == 200
    data = await resp.json()
    assert data["hide_after"] == 0
    assert data["repeat_animation"] == 0
    assert data["delay_update"] == 0


@pytest.mark.asyncio
async def test_api_timing_save_unknown_stem_returns_404(editor_client):
    """POST timing for an unknown stem yields HTTP 404."""
    client, _ = editor_client
    resp = await client.post(
        f"/api/v1/editor/templates/{_UNKNOWN_STEM}/timing",
        json={"hide_after": 10},
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_api_timing_save_bad_json_returns_400(editor_client):
    """A malformed JSON body on timing save yields HTTP 400."""
    client, _ = editor_client
    resp = await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/timing",
        data=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_api_timing_save_json_array_returns_400(editor_client):
    """A valid JSON array body (not an object) on timing save yields HTTP 400."""
    client, _ = editor_client
    resp = await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/timing",
        json=[1, 2, 3],
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_api_timing_roundtrip(editor_client):
    """Save timing values and read them back."""
    client, _ = editor_client
    save_resp = await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/timing",
        json={"hide_after": 30, "repeat_animation": 60, "delay_update": 5},
    )
    assert save_resp.status == 200
    assert (await save_resp.json())["ok"] is True

    get_resp = await client.get(f"/api/v1/editor/templates/{_KNOWN_STEM}/timing")
    data = await get_resp.json()
    assert data["hide_after"] == 30
    assert data["repeat_animation"] == 60
    assert data["delay_update"] == 5


@pytest.mark.asyncio
async def test_api_timing_partial_save_zeros_missing_keys(editor_client):
    """Keys absent from the payload should be stored as 0."""
    client, _ = editor_client
    await client.post(
        f"/api/v1/editor/templates/{_KNOWN_STEM}/timing",
        json={"hide_after": 15},
    )
    resp = await client.get(f"/api/v1/editor/templates/{_KNOWN_STEM}/timing")
    data = await resp.json()
    assert data["hide_after"] == 15
    assert data["repeat_animation"] == 0
    assert data["delay_update"] == 0
