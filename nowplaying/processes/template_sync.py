#!/usr/bin/env python3
"""Sync templates from the What's Now Playing charts server.

Two fire-and-forget tasks are launched from datacache startup:

sync_base_templates(config)
    Fetches /api/v1/templates/manifest (public endpoint) and downloads base
    .htm files newer than what the template chain currently serves into
    templatedir/synced/.  User-owned overrides are never touched; entries
    are removed again once a newer app bundle catches up.  Vendor assets
    (fonts, JS) are bundle-only and never synced at runtime.

sync_from_charts(config, client)
    Fetches /api/v1/editor/sync (requires API key), downloads base files
    via the datacache client, assembles user-customised named templates,
    and writes them to templatedir/synced/.  A manifest file
    (templatedir/synced/.wnp_sync_manifest.json) tracks written files so
    stale entries can be removed without touching user-placed files.
"""

import asyncio
import hashlib
import json
import logging
import pathlib
import ssl
from typing import TYPE_CHECKING

import httpx
import truststore
import wnp_templates._version

import nowplaying.datacache
import nowplaying.upgrades
import nowplaying.template_colors
import nowplaying.utils.charts_api
import nowplaying.utils.templatepaths

if TYPE_CHECKING:
    import nowplaying.config
    import nowplaying.datacache.client

_MANIFEST_NAME = ".wnp_sync_manifest.json"


def _safe_filename(name: str) -> bool:
    """True when a server-supplied name is a plain filename.

    Server data must never influence where we write or unlink: no path
    separators, no traversal, no hidden files (our manifests are dotfiles).
    """
    return bool(name) and pathlib.PurePath(name).name == name and not name.startswith(".")


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
    # a template whose base download failed transiently is still listed on
    # the server: keep serving the previous copy instead of unlinking it
    expected_names = {
        entry.get("name", "").strip() for entry in configs if entry.get("name", "").strip()
    }
    keep_names = written_names | (_read_manifest(synced_dir) & expected_names)
    _cleanup_stale(synced_dir, keep_names)
    _write_manifest(synced_dir, keep_names)
    logging.debug("Template sync: wrote %d template(s)", len(written_names))


async def _fetch_manifest(url: str, api_key: str) -> dict | None:
    ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        async with httpx.AsyncClient(verify=ssl_ctx, follow_redirects=True) as session:
            headers = {"X-WNP-Charts-Key": api_key} if api_key else None
            resp = await session.get(
                url,
                headers=headers,
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
        if not _safe_filename(name) or stem not in base_html:
            logging.warning("Template sync: rejecting unsafe template name %r", name)
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
        if not _safe_filename(stale_name):
            continue
        stale_path = synced_dir / f"{stale_name}.htm"
        if stale_path.exists():
            stale_path.unlink()
            logging.debug("Template sync: removed stale template %r", stale_name)


async def sync_base_templates(config: "nowplaying.config.ConfigFile") -> None:
    """Download newer base .htm files from the charts manifest into synced/.

    Runs as a fire-and-forget background task on startup.  Safe to call even
    when charts is unreachable — all errors are logged and swallowed.
    Vendor assets are intentionally not synced: the webserver serves them
    from the bundle only, so runtime downloads would never be used.

    Sync only ever writes inside synced/ — everything else in the user's
    templates tree is user-owned and never touched.  A template is
    downloaded only when the server version differs from what the chain
    currently serves AND the current file is not the user's own override.
    Entries whose bundled stock catches up (a new app release) are removed
    again, tracked via a manifest of what this sync wrote.
    """
    base_url = nowplaying.utils.charts_api.get_charts_base_url(config)
    manifest_data = await _fetch_manifest(f"{base_url}/api/v1/templates/manifest", "")
    if not manifest_data:
        return

    synced_dir = pathlib.Path(config.templatedir) / "synced"
    synced_dir.mkdir(parents=True, exist_ok=True)

    allow_downloads = _server_is_newer(manifest_data.get("wnp_templates_version", ""))

    ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    async with httpx.AsyncClient(
        verify=ssl_ctx, follow_redirects=True, timeout=httpx.Timeout(_DOWNLOAD_TIMEOUT)
    ) as client:
        await _sync_base_htms(
            config,
            client,
            manifest_data.get("templates", {}),
            synced_dir,
            allow_downloads=allow_downloads,
        )


def _server_is_newer(server_version: str) -> bool:
    """True when the charts server ships a newer wnp-templates than we bundle.

    A manifest without a version (older charts deployment) never triggers
    downloads — direction cannot be established, and syncing an older
    server's templates over a newer bundle would move users backward.
    """
    if not server_version:
        logging.debug("Base template sync: server manifest has no version, downloads disabled")
        return False
    local_version = wnp_templates._version.__version__  # pylint: disable=protected-access
    try:
        newer = nowplaying.upgrades.Version(server_version) > nowplaying.upgrades.Version(
            local_version
        )
    except ValueError:
        logging.warning(
            "Base template sync: cannot compare versions (server=%r local=%r)",
            server_version,
            local_version,
        )
        return False
    logging.debug(
        "Base template sync: server wnp-templates %s vs local %s -> downloads %s",
        server_version,
        local_version,
        "enabled" if newer else "disabled",
    )
    return newer


_BASE_SYNC_MANIFEST = ".wnp_base_sync.json"


def _read_base_sync_manifest(synced_dir: pathlib.Path) -> dict[str, str]:
    manifest_path = synced_dir / _BASE_SYNC_MANIFEST
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _sync_base_htms(  # pylint: disable=too-many-branches,too-many-locals
    config: "nowplaying.config.ConfigFile",
    client: httpx.AsyncClient,
    templates: dict[str, dict],
    synced_dir: pathlib.Path,
    allow_downloads: bool = True,
) -> None:
    written = _read_base_sync_manifest(synced_dir)
    keep: dict[str, str] = {}
    wanted: list[tuple[str, str]] = []
    for stem, info in templates.items():
        url = info.get("url", "")
        expected = info.get("checksum", "")
        if not _safe_filename(stem) or not url or not expected or not allow_downloads:
            continue
        name = f"{stem}.htm"
        current = nowplaying.utils.templatepaths.resolve_template(config, name)
        if current and _sha256(current) == expected:
            if current.parent == synced_dir:
                # bundled stock may have caught up (new app release);
                # if so the synced copy is redundant — let cleanup drop it
                bundled = nowplaying.template_colors.BUNDLED_TEMPLATE_DIR / name
                if not (bundled.exists() and _sha256(bundled) == expected):
                    keep[stem] = expected
            continue
        if current and nowplaying.utils.templatepaths.is_user_template(config, current):
            logging.debug("Base template sync: %s is user-owned, skipping", name)
            continue
        wanted.append((stem, url))

    async def _download(stem: str, url: str) -> None:
        name = f"{stem}.htm"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            (synced_dir / name).write_bytes(resp.content)
            keep[stem] = hashlib.sha256(resp.content).hexdigest()
            logging.debug("Base template sync: downloaded %s", name)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Base template sync: failed to download %s", name)

    if wanted:
        await asyncio.gather(*(_download(stem, url) for stem, url in wanted))

    # remove synced copies we wrote ONLY when the bundled stock provably
    # carries the same content; anything else keeps serving (a manifest
    # without a version or an older server must never regress users)
    for stem, oldhash in written.items():
        if stem in keep or not _safe_filename(stem):
            continue
        stale = synced_dir / f"{stem}.htm"
        if not stale.exists():
            continue
        if _sha256(stale) != oldhash:
            # not the file we wrote; leave it, stop tracking it
            continue
        bundled = nowplaying.template_colors.BUNDLED_TEMPLATE_DIR / f"{stem}.htm"
        if bundled.exists() and _sha256(bundled) == oldhash:
            stale.unlink()
            logging.debug("Base template sync: removed %s (bundle current)", stale.name)
        else:
            keep[stem] = oldhash

    (synced_dir / _BASE_SYNC_MANIFEST).write_text(
        json.dumps(keep, sort_keys=True), encoding="utf-8"
    )
