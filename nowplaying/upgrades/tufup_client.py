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

    class ProgressHook(Protocol):
        """tufup calls progress callbacks with keyword args, not positional."""

        def __call__(self, *, bytes_downloaded: int, bytes_expected: int) -> None: ...


logger = logging.getLogger(__name__)


def _default_state_dir() -> pathlib.Path:
    """Per-platform cache directory for tufup state.

    macOS:   ~/Library/Application Support/WhatsNowPlaying/tufup
    Windows: %LOCALAPPDATA%/WhatsNowPlaying/tufup
    Linux:   ~/.local/share/WhatsNowPlaying/tufup
    """
    locations = QStandardPaths.standardLocations(QStandardPaths.StandardLocation.AppLocalDataLocation)
    if not locations:
        logger.warning("QStandardPaths returned no AppLocalDataLocation; using home dir fallback")
        return pathlib.Path.home() / ".local" / "share" / "WhatsNowPlaying" / "tufup"
    return pathlib.Path(locations[0]) / "tufup"


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
        logger.warning("Bundled root.json not found at %s; auto-update disabled", src)
        return
    shutil.copy(src, dst)
    logger.info("Seeded TUF trust anchor: %s -> %s", src, dst)


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
            logger.info("tufup: update available on channel %s", channel)
            return client
        logger.debug("tufup: no update available on channel %s", channel)
    except Exception:  # pylint: disable=broad-except
        # tufup raises on metadata fetch failures, network errors, signature
        # mismatches, etc.  Swallow so the live app never blocks on auto-update.
        logger.exception("tufup: update check failed on channel %s", channel)
    return None


_WIN_BATCH_TEMPLATE = """@echo off
:: Wait for the parent process to release file handles before touching files.
timeout /t 5 /nobreak >nul
:: Rename the running exe aside so robocopy can place the new one at the
:: canonical path.  The new build uses a versioned _internal-{{new_ver}}/
:: directory baked at build time, so there is no conflict with the old
:: _internal-{{old_ver}}/ that stays alongside as a fallback.
if exist "{dst_dir}\\WhatsNowPlaying.exe" (
    rename "{dst_dir}\\WhatsNowPlaying.exe" "WhatsNowPlaying-{version}.exe"
)
echo Moving app files...
robocopy "{src_dir}" "{dst_dir}" /E /MOVE
echo Restarting...
start "" "{exe}"
(goto) 2>nul & del "%~f0"
"""


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
        script_text = _WIN_BATCH_TEMPLATE.format(
            src_dir=str(src_path),
            dst_dir=str(dst_path),
            version=current_version,
            exe=str(dst_path / "WhatsNowPlaying.exe"),
        )
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="tufup", suffix=".bat", delete=False
        ) as fh:
            fh.write(script_text)
            script_path = fh.name
        logger.debug("tufup install (win): batch=%s", script_path)
        subprocess.Popen([script_path], creationflags=subprocess.CREATE_NEW_CONSOLE)  # nosec: path is our own tempfile
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
            logger.debug("tufup install: renamed %s -> %s", src, dst)

    for item in src_path.iterdir():
        dest = dst_path / item.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(item, dest)
    logger.debug("tufup install: moved %s -> %s", src_path, dst_path)

    logger.debug("tufup install: spawning %s", new_exe)
    subprocess.Popen([str(new_exe)])  # nosec


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
