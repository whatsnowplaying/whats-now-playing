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

import nowplaying.utils.qt
import nowplaying.utils.sqlite
import nowplaying.utils.templatepaths
from nowplaying.utils.checksum import EXCLUDED_FILES, checksum

LAYOUT_MARKER = ".wnp_layout"
LAYOUT_VERSION = "6"
ARCHIVE_NAME = "templates_pre6"

# user-owned function subdirectories created in the new layout
SUBDIRS = ("twitch", "kick", "setlist", "web", "synced", "guessgame")

# directories never carried forward (bundle-only content)
_SKIP_DIRS = {"vendor"}

# junk suffixes never carried forward (.new conflict files from the old
# upgrade system, editor swap/backup files)
_SKIP_SUFFIXES = (".new", ".swp", ".swo", "~")


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

        archive = self._archive_old()
        self._ensure_structure()
        self._load_ledger()
        self._carry_user_content(archive)

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

    def _ensure_structure(self) -> None:
        """Create the 6.0 layout directories and marker."""
        self.usertemplatedir.mkdir(parents=True, exist_ok=True)
        for subdir in SUBDIRS:
            self.usertemplatedir.joinpath(subdir).mkdir(exist_ok=True)
        marker = self.usertemplatedir / LAYOUT_MARKER
        if not marker.exists():
            marker.write_text(LAYOUT_VERSION, encoding="utf-8")

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
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(oldpath, dest)
            self.carried.append(str(relpath))
            logging.info("Template migration: carried %s -> %s", relpath, dest)
