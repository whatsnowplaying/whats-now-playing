#!/usr/bin/env python3
"""One-time migration of the user's templates directory to the 6.0 layout.

Pre-6.0, app-owned stock templates were copied into the user's templates
directory at every startup, with a checksum ledger (updateshas.json) and
``.new`` conflict files to manage upgrades.  6.0 serves stock from the
bundle through the template resolution chain, so the user directory only
contains files the user actually owns.

This migration runs once:

* untouched stock copies (hash matches any ledger version or current
  bundled stock) are dropped — the chain serves them from the bundle
* everything else is the user's work and is carried into the new layout,
  classified by filename (twitchbot_* -> twitch/, kickbot_* -> kick/,
  setlist-* -> setlist/, *.htm -> web/); subdirectory content keeps its
  relative location
* ``.new`` conflict files and vendor/ are not carried
* the original directory is preserved as ``templates_pre6``

A ``.wnp_layout`` marker file records the layout version so the
migration never runs twice.
"""

import json
import logging
import pathlib
import shutil

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication,
    QStandardPaths,
)
from PySide6.QtWidgets import QMessageBox  # pylint: disable=no-name-in-module

import wnp_templates

import nowplaying.upgrades.config
import nowplaying.utils.config_json
import nowplaying.utils.qt
import nowplaying.utils.sqlite
import nowplaying.utils.templatepaths
from nowplaying.utils.checksum import EXCLUDED_FILES, checksum

LAYOUT_MARKER = ".wnp_layout"
LAYOUT_VERSION = "6"
ARCHIVE_NAME = "templates_pre6"

# user-owned function subdirectories created in the new layout
SUBDIRS = nowplaying.utils.templatepaths.USER_LAYOUT_SUBDIRS

# directories never carried forward (bundle-only content)
_SKIP_DIRS = {"vendor"}

# junk suffixes never carried forward (.new conflict files from the old
# upgrade system, editor swap/backup files)
_SKIP_SUFFIXES = (".new", ".swp", ".swo", "~")

# pre-6.0 stock templates that no longer ship -> nearest 6.0 equivalent.
# Applied ONCE here: config keys pointing at an unmodified (dropped) copy
# are repointed; modified copies are carried and keep their references.
# Post-migration these names simply do not exist anywhere.
RETIRED_TEMPLATES = {
    "ws-basicblack.htm": "ws-basic-text.htm",
    "ws-basicblue.htm": "ws-basic-text.htm",
    "ws-basicwhite.htm": "ws-basic-text.htm",
    "ws-basicyellow.htm": "ws-basic-text.htm",
    "ws-basic-web.htm": "ws-basic-text.htm",
    "ws-explodeblack.htm": "ws-basic-text-explode.htm",
    "ws-explodewhite.htm": "ws-basic-text-explode.htm",
    "ws-slidedownup-black.htm": "ws-basic-text-slide.htm",
    "ws-slidedownup-white.htm": "ws-basic-text-slide.htm",
    "ws-spinblack.htm": "ws-basic-text-spin.htm",
    "ws-spinwhite.htm": "ws-basic-text-spin.htm",
    "ws-anime-bounce.htm": "ws-basic-text-anime-bounce.htm",
    "ws-anime-elastic.htm": "ws-basic-text-anime-elastic.htm",
    "ws-anime-stagger.htm": "ws-basic-text-anime-stagger.htm",
    "ws-mtv-nofade.htm": "ws-mtv.htm",
    "ws-mtv-cover-nofade.htm": "ws-mtv.htm",
    "ws-mtv-cover-fade.htm": "ws-mtv-fade.htm",
    "ws-cover-title-artist.htm": "ws-mtv.htm",
    "ws-cookie-cutter-dj.htm": "ws-generic-dj.htm",
    "ws-unoriginal-dj-clone.htm": "ws-generic-dj.htm",
    "ws-basic-bro-vibes.htm": "ws-generic-dj.htm",
    "ws-webgl-particles.htm": "ws-canvas-particles.htm",
}

# fallback for a dangling htm reference with no specific successor
_DEFAULT_HTM = "ws-basic-text.htm"

# every config key that may reference a template file: the canonical
# export/import path-key list plus keys it does not cover
_TEMPLATE_CONFIG_KEYS = tuple(
    sorted(
        nowplaying.utils.config_json.PATH_KEYS
        | {
            "textoutput/txttemplate",
            "twitchbot/streamtitle",
            "realtimesetlist/template",
            "discord/channel_template",
        }
    )
)


class TemplateDirMigration:  # pylint: disable=too-few-public-methods
    """Migrate the user's templates directory to the 6.0 layout."""

    def __init__(
        self,
        bundledir: str | pathlib.Path | None = None,
        testdir: str | pathlib.Path | None = None,
    ):
        self.bundledir = pathlib.Path(bundledir) if bundledir else None
        self.testdir = testdir
        if testdir:
            self.usertemplatedir = pathlib.Path(testdir).joinpath(
                QCoreApplication.applicationName(), "templates"
            )
        else:  # pragma: no cover
            self.usertemplatedir = pathlib.Path(
                QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
                QCoreApplication.applicationName(),
            ).joinpath("templates")
        self.oldshas: dict[str, dict[str, str]] = {}
        self.carried: list[str] = []
        self.dropped: list[str] = []

        self.run()

    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the migration if the directory still has the pre-6.0 layout."""
        marker = self.usertemplatedir / LAYOUT_MARKER
        if marker.exists():
            self._ensure_structure()
            return

        if not self.usertemplatedir.exists() or not any(self.usertemplatedir.iterdir()):
            self._ensure_structure()
            return

        try:
            archive = self._archive_old()
        except OSError:
            # Windows: OneDrive/AV can hold the directory even after
            # retries.  The pre-6.0 layout still works through the
            # resolution chain, so leave it and retry next launch.
            logging.exception(
                "Template migration: could not archive %s; retrying next launch",
                self.usertemplatedir,
            )
            return

        try:
            self._ensure_structure(write_marker=False)
            self._load_ledger()
            self._carry_user_content(archive)
            self._repoint_retired()
            # marker written only after user content is carried, so a crash
            # mid-migration re-runs instead of silently reverting to stock
            self._write_marker()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Template migration failed mid-run; rolling back")
            self._rollback(archive)
            return

        logging.info(
            "Template migration: carried %d user file(s), dropped %d stock copy/copies; "
            "originals archived in %s",
            len(self.carried),
            len(self.dropped),
            archive,
        )
        if self.carried and not self.testdir:  # pragma: no cover
            msgbox = QMessageBox()
            msgbox.setText(
                "Your templates folder has been reorganized for this release.\n"
                f"Your customized templates were moved into place and the\n"
                f"original folder was saved as {ARCHIVE_NAME}."
            )
            msgbox.setModal(True)
            msgbox.setWindowTitle("What's Now Playing Templates")
            nowplaying.utils.qt.focus_window(msgbox)
            msgbox.exec()

    # ------------------------------------------------------------------

    def _ensure_structure(self, write_marker: bool = True) -> None:
        """Create the 6.0 layout directories (and, by default, the marker)."""
        self.usertemplatedir.mkdir(parents=True, exist_ok=True)
        for subdir in SUBDIRS:
            self.usertemplatedir.joinpath(subdir).mkdir(exist_ok=True)
        if write_marker:
            self._write_marker()

    def _write_marker(self) -> None:
        marker = self.usertemplatedir / LAYOUT_MARKER
        if not marker.exists():
            marker.write_text(LAYOUT_VERSION, encoding="utf-8")

    def _rollback(self, archive: pathlib.Path) -> None:
        """Best-effort restore of the pre-migration layout after a failure.

        The partially-built new tree only contains copies of archive
        content, so it is safe to discard before renaming the archive back.
        """
        try:
            if self.usertemplatedir.exists():
                shutil.rmtree(self.usertemplatedir)
            nowplaying.utils.sqlite.retry_file_operation(
                lambda: archive.rename(self.usertemplatedir)
            )
            logging.info("Template migration: rolled back; will retry next launch")
        except OSError:
            logging.exception(
                "Template migration: rollback failed; original templates remain in %s", archive
            )

    def _archive_old(self) -> pathlib.Path:
        """Rename the old templates directory aside; return the archive path."""
        base = self.usertemplatedir.with_name(ARCHIVE_NAME)
        archive = base
        counter = 1
        while archive.exists():
            counter += 1
            archive = base.with_name(f"{ARCHIVE_NAME}-{counter}")
        nowplaying.utils.sqlite.retry_file_operation(lambda: self.usertemplatedir.rename(archive))
        return archive

    def _load_ledger(self) -> None:
        """Load the historical stock-template checksum ledger."""
        if not self.bundledir:
            return
        shafile = self.bundledir.joinpath("resources", "updateshas.json")
        if not shafile.exists():
            logging.error("%s file is missing.", shafile)
            return
        try:
            self.oldshas = json.loads(shafile.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logging.exception("Cannot read %s", shafile)

    def _is_stock(self, relpath: pathlib.Path, filehash: str | None) -> bool:
        """True when the file matches a known stock version (ledger or current)."""
        if filehash is None:
            return False
        if versions := self.oldshas.get(relpath.as_posix()):
            if filehash in versions.values():
                return True
        # also match current bundled stock (e.g. refreshed by an early sync)
        if self.bundledir:
            bundled = self.bundledir.joinpath("templates", relpath)
            if bundled.exists() and checksum(bundled) == filehash:
                return True
        wheelstock = wnp_templates.BUNDLED_TEMPLATE_DIR / relpath.name
        if wheelstock.exists() and checksum(wheelstock) == filehash:
            return True
        return False

    @staticmethod
    def _classify(relpath: pathlib.Path) -> pathlib.Path:
        """Return the new-layout relative path for a carried file."""
        if len(relpath.parts) > 1:
            # subdirectory content (guessgame/, oauth/, synced/, custom dirs)
            # keeps its relative location
            return relpath
        return nowplaying.utils.templatepaths.classify_template_name(relpath.name)

    def _repoint_retired(self) -> None:
        """Repoint config keys referencing retired stock templates.

        Only fires when the old copy was unmodified stock (dropped by the
        carry pass); a carried customization keeps its reference and keeps
        working through the resolution chain.
        """
        carried_names = {pathlib.PurePath(entry).name for entry in self.carried}
        settings = nowplaying.upgrades.config.get_user_settings()
        for key in _TEMPLATE_CONFIG_KEYS:
            value = settings.value(key)
            if not value:
                continue
            oldname = pathlib.PurePath(str(value)).name
            if oldname in carried_names or self._name_in_stock(oldname):
                # carried customizations and still-shipping stock resolve
                # through the chain; the reference keeps working
                continue
            newname = RETIRED_TEMPLATES.get(oldname)
            if not newname:
                if not oldname.endswith((".htm", ".html")):
                    continue
                newname = _DEFAULT_HTM
            settings.setValue(key, newname)
            logging.info(
                "Template migration: %s repointed from retired %s to %s", key, oldname, newname
            )
        settings.sync()

    def _name_in_stock(self, name: str) -> bool:
        """True when a bare template name still ships in current stock."""
        if (wnp_templates.BUNDLED_TEMPLATE_DIR / name).exists():
            return True
        return bool(self.bundledir and self.bundledir.joinpath("templates", name).exists())

    def _carry_user_content(self, archive: pathlib.Path) -> None:
        """Copy the user's own files from the archive into the new layout."""
        for oldpath in sorted(archive.rglob("*")):
            if not oldpath.is_file():
                continue
            relpath = oldpath.relative_to(archive)
            if oldpath.name in EXCLUDED_FILES:
                continue
            if oldpath.name.endswith(_SKIP_SUFFIXES):
                continue
            if relpath.parts[0] in _SKIP_DIRS:
                continue
            if self._is_stock(relpath, checksum(oldpath)):
                self.dropped.append(str(relpath))
                continue
            dest = self.usertemplatedir / self._classify(relpath)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(oldpath, dest)
            except OSError:
                logging.exception("Template migration: could not carry %s", relpath)
                continue
            self.carried.append(str(relpath))
            logging.info("Template migration: carried %s -> %s", relpath, dest)
