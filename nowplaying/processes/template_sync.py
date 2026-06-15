#!/usr/bin/env python3
"""Sync named templates from the What's Now Playing charts server.

On datacache startup, sync_from_charts(config, client) is launched as a
fire-and-forget asyncio task.  It fetches the sync manifest from the charts
server, enqueues stale base .htm file downloads through the datacache client
(with per-download callbacks), and assembles the final HTML once all bases
are ready.  Assembled templates are written to templatedir/synced/.

A manifest file (templatedir/synced/.wnp_sync_manifest.json) tracks which
files we wrote so stale entries can be deleted without touching files the user
placed there manually.
"""

import asyncio
import json
import logging
import pathlib
import ssl
from typing import TYPE_CHECKING

import httpx
import truststore

import nowplaying.datacache
import nowplaying.template_colors
import nowplaying.utils.charts_api

if TYPE_CHECKING:
    import nowplaying.config
    import nowplaying.datacache.client

_MANIFEST_NAME = ".wnp_sync_manifest.json"
_SYNC_TIMEOUT = 30.0
_DOWNLOAD_TIMEOUT = 60.0
_TTL = 7 * 24 * 3600


async def sync_from_charts(  # pylint: disable=too-many-locals
    config: "nowplaying.config.ConfigFile",
    client: "nowplaying.datacache.client.DataCacheClient",
) -> None:
    """Fetch named templates from charts server and write to templatedir/synced/."""
    api_key = str(config.cparser.value("charts/charts_key", defaultValue=""))
    if not nowplaying.utils.charts_api.is_valid_api_key(api_key):
        logging.debug("Template sync: no valid charts API key, skipping")
        return

    base_url = nowplaying.utils.charts_api.get_charts_base_url(config)
    manifest_data = await _fetch_manifest(f"{base_url}/api/v1/editor/sync", api_key)
    if not manifest_data:
        return

    configs = manifest_data.get("configs", [])
    bases = manifest_data.get("bases", {})
    missing = manifest_data.get("missing", [])
    if missing:
        logging.warning(
            "Template sync: server dropped %d named template(s) with missing base files: %s",
            len(missing),
            ", ".join(repr(n) for n in missing),
        )

    if not configs:
        logging.debug("Template sync: no named templates on server")
        return

    synced_dir = pathlib.Path(config.templatedir) / "synced"
    synced_dir.mkdir(parents=True, exist_ok=True)

    pending: set[str] = set()
    downloaded: dict[str, str] = {}
    url_to_stem: dict[str, str] = {}
    all_done = asyncio.Event()

    async def on_base_ready(url: str, entry: nowplaying.datacache.CachedEntry | None) -> None:
        stem = url_to_stem.get(url, "")
        if entry and entry.status_code == 200:
            downloaded[stem] = entry.data.decode("utf-8")
        else:
            logging.warning("Template sync: failed to download base for stem %r", stem)
        pending.discard(stem)
        if not pending:
            all_done.set()

    for stem, info in bases.items():
        url = info.get("url", "")
        checksum = info.get("checksum", "") or None
        if not url:
            continue
        url_to_stem[url] = stem
        pending.add(stem)
        await client.get_or_fetch(
            nowplaying.datacache.FetchRequest(
                url=url,
                identifier="wnp-template-sync",
                data_type="template_base",
                provider="charts",
                ttl_seconds=_TTL,
                immediate=False,
                expected_checksum=checksum,
                on_complete=on_base_ready,
            )
        )

    if not pending:
        all_done.set()

    try:
        await asyncio.wait_for(all_done.wait(), timeout=_DOWNLOAD_TIMEOUT)
    except asyncio.TimeoutError:
        logging.warning("Template sync: timed out waiting for base downloads")
        if not downloaded:
            return

    written_names = _assemble_templates(configs, downloaded, synced_dir)
    _cleanup_stale(synced_dir, written_names)
    _write_manifest(synced_dir, written_names)
    logging.debug("Template sync: wrote %d template(s)", len(written_names))


async def _fetch_manifest(url: str, api_key: str) -> dict | None:
    ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        async with httpx.AsyncClient(verify=ssl_ctx, follow_redirects=True) as session:
            resp = await session.get(
                url,
                headers={"X-WNP-Charts-Key": api_key},
                timeout=httpx.Timeout(_SYNC_TIMEOUT),
            )
            if resp.status_code == 401:
                logging.warning("Template sync: API key rejected by charts server")
                return None
            if resp.status_code != 200:
                logging.warning(
                    "Template sync: unexpected status %d from charts server", resp.status_code
                )
                return None
            return resp.json()
    except httpx.HTTPError:
        logging.warning("Template sync: could not reach charts server", exc_info=True)
        return None
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("Template sync: unexpected error fetching manifest")
        return None


def _assemble_templates(
    configs: list[dict],
    base_html: dict[str, str],
    synced_dir: pathlib.Path,
) -> set[str]:
    written: set[str] = set()
    for entry in configs:
        name = entry.get("name", "").strip()
        stem = entry.get("base_stem", "")
        if not name or stem not in base_html:
            continue
        css_vars = entry.get("css_vars") or {}
        if not isinstance(css_vars, dict):
            css_vars = {}
        try:
            html = nowplaying.template_colors.assemble_named_template(
                base_html=base_html[stem],
                css_vars=css_vars,
                hide_after=int(entry.get("hide_after", 0)),
                repeat_animation=int(entry.get("repeat_animation", 0)),
                delay_update=int(entry.get("delay_update", 0)),
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Template sync: failed to assemble %r", name)
            continue
        (synced_dir / f"{name}.htm").write_text(html, encoding="utf-8")
        written.add(name)
    return written


def _read_manifest(synced_dir: pathlib.Path) -> set[str]:
    manifest_path = synced_dir / _MANIFEST_NAME
    if not manifest_path.exists():
        return set()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except Exception:  # pylint: disable=broad-exception-caught
        return set()


def _write_manifest(synced_dir: pathlib.Path, names: set[str]) -> None:
    (synced_dir / _MANIFEST_NAME).write_text(json.dumps(sorted(names)), encoding="utf-8")


def _cleanup_stale(synced_dir: pathlib.Path, current_names: set[str]) -> None:
    for stale_name in _read_manifest(synced_dir) - current_names:
        stale_path = synced_dir / f"{stale_name}.htm"
        if stale_path.exists():
            stale_path.unlink()
            logging.debug("Template sync: removed stale template %r", stale_name)
