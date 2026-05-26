"""tufup client wrapper for WNP in-place auto-update.

Wraps tufup.client.Client with WNP-specific configuration so the rest of
the app can call a single helper to check for and apply updates.

Metadata and target base URLs point at the production whatsnowplaying.com
proxy (see TUFUP_METADATA_BASE_URL / TUFUP_TARGET_BASE_URL below).  The TUF
trust anchor (root.json) is bundled inside the PyInstaller artifact under
resources/tufup/ and seeded into the writable state dir on first launch by
_seed_trust_anchor().

The UpgradeDialog in nowplaying/upgrade.py drives the full flow: the charts
API supplies the tufup channel, and run_auto_install() in autoinstall.py
handles the QThread worker and progress UI.
"""

import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module
import tufup.client

import nowplaying.frozen
import nowplaying.version  # pylint: disable=no-name-in-module, import-error

if TYPE_CHECKING:
    from typing import Protocol

    class ProgressHook(Protocol):  # pylint: disable=too-few-public-methods
        """tufup calls progress callbacks with keyword args, not positional."""

        def __call__(self, *, bytes_downloaded: int, bytes_expected: int) -> None: ...


def get_state_dir() -> pathlib.Path:
    """Public accessor for the default tufup state directory.

    Delegates to _default_state_dir() so callers (e.g. background.py) do not
    need to reference a private name and force a pylint suppression.
    """
    return _default_state_dir()


def _default_state_dir() -> pathlib.Path:
    """Per-platform cache directory for tufup state.

    macOS:   ~/Library/Application Support/WhatsNowPlaying/tufup
    Windows: %LOCALAPPDATA%/WhatsNowPlaying/tufup
    Linux:   ~/.local/share/WhatsNowPlaying/tufup
    """
    locations = QStandardPaths.standardLocations(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not locations:
        logging.warning("QStandardPaths returned no AppLocalDataLocation; using home dir fallback")
        return pathlib.Path.home() / ".local" / "share" / "WhatsNowPlaying" / "tufup"
    return pathlib.Path(locations[0]) / "tufup"


# Sentinel filename written to the targets dir by mark_prefetch_complete().
# Stores the version string that was successfully pre-fetched so that
# has_cached_update() can confirm the cached archive is for the right version.
_PREFETCH_SENTINEL = ".prefetch_version"


def mark_prefetch_complete(
    version: str,
    filename: str,
    state_dir: pathlib.Path | None = None,
) -> None:
    """Write the prefetch sentinel so has_cached_update() can detect a warm cache.

    Stores version and archive filename as JSON in targets/.prefetch_version.
    version is the charts-API latest_version string (both sides agree on it).
    filename is the archive basename from client.new_archive_local_path.name,
    used by has_cached_update() to confirm the specific file is still on disk.
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    sentinel = state_dir / "targets" / _PREFETCH_SENTINEL
    try:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(
            json.dumps({"version": version, "filename": pathlib.Path(filename).name}),
            encoding="utf-8",
        )
        logging.debug("prefetch: wrote sentinel for version %s (%s)", version, filename)
    except OSError:
        logging.warning("prefetch: could not write sentinel file %s", sentinel, exc_info=True)


def has_cached_update(version: str, state_dir: pathlib.Path | None = None) -> bool:
    """Return True if the background prefetch completed for exactly `version`
    and the specific archive file is still on disk.

    Two-step check — no network calls:
    1. Sentinel targets/.prefetch_version must record `version`.
    2. The archive filename stored in the sentinel must exist in targets/.
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    sentinel = state_dir / "targets" / _PREFETCH_SENTINEL
    try:
        data = json.loads(sentinel.read_text(encoding="utf-8"))
        if data.get("version") != version:
            return False
        raw = data.get("filename")
        if not raw:
            return False
        filename = pathlib.Path(raw).name
    except (OSError, json.JSONDecodeError):
        return False
    return (state_dir / "targets" / filename).exists()


_ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tar.bz2", ".tar.xz")


def _is_archive_file(path: pathlib.Path) -> bool:
    """Return True if path has a known tufup archive extension."""
    name = path.name
    return any(name.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES)


def cleanup_stale_targets(state_dir: pathlib.Path | None = None) -> None:
    """Delete archive files in targets/ that are not the current prefetched version.

    tufup never removes old archives after install (it has a # todo comment for
    this).  Each release is ~300 MB, so three releases = ~1 GB of waste.  We
    read the sentinel to find the current archive and delete only regular files
    with known archive extensions — logs, debug artifacts, and directories are
    left untouched.

    Called from upgrade() on every launch so the directory stays bounded to at
    most one archive regardless of how many versions were skipped.
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    target_dir = state_dir / "targets"
    if not target_dir.is_dir():
        return
    keep_name: str | None = None
    sentinel = target_dir / _PREFETCH_SENTINEL
    try:
        data = json.loads(sentinel.read_text(encoding="utf-8"))
        if filename := data.get("filename"):
            keep_name = pathlib.Path(filename).name
    except (OSError, json.JSONDecodeError):
        pass
    for item in target_dir.iterdir():
        if not item.is_file():
            continue
        if item.name == _PREFETCH_SENTINEL:
            continue
        if not _is_archive_file(item):
            continue
        if keep_name and item.name == keep_name:
            continue
        try:
            item.unlink()
            logging.debug("prefetch: removed stale archive %s", item.name)
        except OSError:
            logging.warning(
                "prefetch: could not remove stale archive %s", item.name, exc_info=True
            )


def _seed_trust_anchor(metadata_dir: pathlib.Path) -> None:
    """Copy the bundled root.json into metadata_dir if it isn't there yet.

    The bundled root.json is the TUF trust anchor that ships inside the
    PyInstaller artifact.  On first launch we need to plant it in the
    writable state dir so tufup can verify subsequent metadata fetches
    against it (and tufup will rotate it via TUF root signing when needed).
    """
    dst = metadata_dir / "root.json"
    if dst.exists():
        return
    bundledir = pathlib.Path(nowplaying.frozen.frozen_init(None))
    src = bundledir / "resources" / "tufup" / "root.json"
    if not src.exists():
        logging.warning("Bundled root.json not found at %s; auto-update disabled", src)
        return
    shutil.copy(src, dst)
    logging.info("Seeded TUF trust anchor: %s -> %s", src, dst)


# Public HTTPS endpoints fronted by the whatsnowplaying.com FastAPI app.
# Metadata: streaming proxy to gh-pages.  Targets: 302 to GH Releases.
# See docs/dev/tufup-hosting.md for the proxy contract.
TUFUP_METADATA_BASE_URL: str = "https://whatsnowplaying.com/tufup/metadata/"
TUFUP_TARGET_BASE_URL: str = "https://whatsnowplaying.com/tufup/targets/"


def build_client(
    install_dir: pathlib.Path,
    state_dir: pathlib.Path | None = None,
    *,
    channel: str,
) -> tufup.client.Client:
    """Construct a tufup Client wired to WNP's running version and state dirs.

    install_dir: where the running app actually lives on disk.  tufup writes
    the new version into this directory once the update is applied, so it
    must be the location PyInstaller deployed to (not the venv source tree).

    state_dir: where tufup caches metadata + downloaded archives across
    launches.  Defaults to the per-platform AppLocalDataLocation.

    channel: the TUF target-filename prefix to subscribe to (e.g.
    "WhatsNowPlaying_macos15_arm").  Comes from the charts server's
    `tufup_channel` field on /api/v1/check-version — the server is
    authoritative for channel routing (handles Rosetta-mismatch
    installs, EOL channel migration, prerelease tracks, etc.).  If
    the API is unreachable, we never get here in the first place;
    no client-side fallback.
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    metadata_dir = state_dir / "metadata"
    target_dir = state_dir / "targets"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    # First-launch trust anchor: copy the root.json shipped inside the
    # PyInstaller bundle into the writable metadata dir.  No-op on
    # subsequent launches.
    _seed_trust_anchor(metadata_dir)

    return tufup.client.Client(
        app_name=channel,
        app_install_dir=install_dir,
        current_version=nowplaying.version.__VERSION__,
        metadata_dir=metadata_dir,
        metadata_base_url=TUFUP_METADATA_BASE_URL,
        target_dir=target_dir,
        target_base_url=TUFUP_TARGET_BASE_URL,
        refresh_required=False,
    )


def check_for_update(
    install_dir: pathlib.Path,
    *,
    channel: str,
) -> "tufup.client.Client | None":
    """Return a tufup Client if an update is available, else None.

    The returned Client carries the update target metadata; call
    download_and_apply() on it (or client.download_and_apply_update()
    with the args your UI needs) to actually fetch and install.

    channel: required.  The charts API's `tufup_channel` field already
    encodes track (stable vs prerelease) via the channel name itself,
    so we don't pass tufup's `pre=` filter.
    """
    try:
        client = build_client(install_dir, channel=channel)
        if client.check_for_updates():
            logging.info("tufup: update available on channel %s", channel)
            return client
        logging.debug("tufup: no update available on channel %s", channel)
    except Exception:  # pylint: disable=broad-except
        # tufup raises on metadata fetch failures, network errors, signature
        # mismatches, etc.  Swallow so the live app never blocks on auto-update.
        logging.exception("tufup: update check failed on channel %s", channel)
    return None


_WIN_BATCH_TEMPLATE = """@echo off
:: Wait until the parent WNP process exits before touching any files.
:: Wait-Process blocks exactly until the pid is gone; no arbitrary sleep.
powershell -Command "Wait-Process -Id {pid} -ErrorAction SilentlyContinue"
:: Rename the running exe aside so robocopy can place the new one at the
:: canonical path.  The new build uses a versioned _internal-{{new_ver}}/
:: directory baked at build time, so there is no conflict with the old
:: _internal-{{old_ver}}/ that stays alongside as a fallback.
if exist "{dst_dir}\\WhatsNowPlaying.exe" (
    rename "{dst_dir}\\WhatsNowPlaying.exe" "WhatsNowPlaying-{version}.exe"
)
robocopy "{src_dir}" "{dst_dir}" /E /MOVE /R:3 /W:2
rd /s /q "{src_dir}" 2>nul
start "" "{exe}"
(goto) 2>nul & del "%~f0"
"""


def _win_install(
    src_path: pathlib.Path,
    dst_path: pathlib.Path,
    current_version: str,
) -> None:
    """Launch the detached batch script that performs the Windows in-place swap.

    tufup deletes its extraction dir after install() returns, so we stage the
    new build to a temp dir we own before launching the script.
    """
    staging = pathlib.Path(tempfile.mkdtemp(prefix="wnp-update-"))
    shutil.copytree(src_path, staging, dirs_exist_ok=True)
    script_text = _WIN_BATCH_TEMPLATE.format(
        pid=os.getpid(),
        src_dir=str(staging),
        dst_dir=str(dst_path),
        version=current_version,
        exe=str(dst_path / "WhatsNowPlaying.exe"),
    )
    with tempfile.NamedTemporaryFile(mode="w", prefix="tufup", suffix=".bat", delete=False) as fh:
        fh.write(script_text)
        script_path = fh.name
    logging.debug("tufup install (win): batch=%s", script_path)
    startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    startupinfo.wShowWindow = 0  # SW_HIDE
    _flags = (  # type: ignore[attr-defined]
        subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    )
    subprocess.Popen(  # nosec: path is our own tempfile  # pylint: disable=consider-using-with
        [script_path],
        creationflags=_flags,
        startupinfo=startupinfo,
        close_fds=True,
    )


def _install_without_sys_exit(
    src_dir: pathlib.Path | str,
    dst_dir: pathlib.Path | str,
    **_kwargs,
) -> None:
    """Replace the running install with the freshly extracted update.

    Uses a rename-aside strategy: the running binary/bundle is atomically
    renamed to a versioned backup name before the new copy is moved into
    the canonical path.  This sidesteps macOS Gatekeeper's code-signature
    page-hash validation (SIGKILL on mmapped file modification) because
    os.rename(2) changes only directory entries — it never touches the
    inode's data pages that the kernel has already mapped.

    The same strategy avoids Windows' file-in-use error on the .exe;
    the batch script handles the parent-process exit wait + relaunch.

    Tufup calls this from inside our UpdateWorker QThread; we return
    instead of sys.exit()-ing so that Qt can tear down the thread cleanly
    before upgrade()'s outer sys.exit(0) unwinds the main thread.
    """
    src_path = pathlib.Path(src_dir)
    dst_path = pathlib.Path(dst_dir)
    current_version = nowplaying.version.__VERSION__

    if sys.platform == "win32":
        _win_install(src_path, dst_path, current_version)
        return

    # macOS / Linux: rename running binary/bundle aside, then move new one in.
    if sys.platform == "darwin":
        # macOS: the .app bundle is self-contained; renaming it covers everything.
        old_path = dst_path / "WhatsNowPlaying.app"
        versioned_path = dst_path / f"WhatsNowPlaying-{current_version}.app"
        new_exe = dst_path / "WhatsNowPlaying.app" / "Contents" / "MacOS" / "WhatsNowPlaying"
        renames = [(old_path, versioned_path)]
    else:
        # Linux onedir layout: binary + versioned _internal-{ver}/ alongside it.
        # The new binary uses a different _internal-{new_ver}/ baked at build
        # time, so we only need to rename the binary aside.
        old_path = dst_path / "WhatsNowPlaying"
        versioned_path = dst_path / f"WhatsNowPlaying-{current_version}"
        new_exe = dst_path / "WhatsNowPlaying"
        renames = [(old_path, versioned_path)]

    for src, dst in renames:
        if src.exists():
            os.rename(src, dst)
            logging.debug("tufup install: renamed %s -> %s", src, dst)

    # No rollback if a move fails mid-way: the versioned-aside backup (above)
    # is the recovery path — the user can relaunch the old binary manually.
    # A proper atomic swap would require OS-level rename across volumes.
    for item in src_path.iterdir():
        dest = dst_path / item.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(item, dest)
    logging.debug("tufup install: moved %s -> %s", src_path, dst_path)

    logging.debug("tufup install: spawning %s", new_exe)
    subprocess.Popen([str(new_exe)])  # nosec  # pylint: disable=consider-using-with


def download_and_apply(
    client: tufup.client.Client,
    *,
    progress_hook: "ProgressHook | None" = None,
    skip_confirmation: bool = False,
) -> None:
    """Fetch the pending update and replace the running install in place.

    Returns to the caller after the move + spawn-replacement steps
    have completed.  The caller is expected to do a clean Qt /
    multiprocessing shutdown in the main thread (our `upgrade()`
    orchestrator handles this via its trailing `sys.exit(0)`).

    Passes our `_install_without_sys_exit` to tufup so the install
    callable does NOT exit the process from inside the worker
    thread -- see that function's docstring for why.
    """
    client.download_and_apply_update(
        skip_confirmation=skip_confirmation,
        progress_hook=progress_hook,
        install=_install_without_sys_exit,
        purge_dst_dir=False,
        exclude_from_purge=None,
        log_file_name="install.log",
    )
