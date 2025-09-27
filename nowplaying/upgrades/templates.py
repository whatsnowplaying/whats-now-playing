#!/usr/bin/env python3
"""Template upgrade logic"""

import json
import logging
import pathlib
import shutil

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication,
    QStandardPaths,
)
from PySide6.QtWidgets import QMessageBox  # pylint: disable=no-name-in-module

# Import unified checksum function and exclusion list
from nowplaying.utils.checksum import checksum, EXCLUDED_FILES


class UpgradeTemplates:
    """Upgrade templates"""

    def __init__(
        self,
        bundledir: str | pathlib.Path | None = None,
        testdir: str | pathlib.Path | None = None,
    ):
        self.bundledir = pathlib.Path(bundledir)
        self.apptemplatedir = self.bundledir.joinpath("templates")
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
        self.usertemplatedir.mkdir(parents=True, exist_ok=True)
        self.alert = False
        self.copied: list[str] = []
        self.oldshas: dict[str, dict[str, str]] = {}

        self.setup_templates()

        if self.alert and not self.testdir:
            msgbox = QMessageBox()
            msgbox.setText("Updated templates have been placed.")
            msgbox.setModal(True)
            msgbox.setWindowTitle("What's Now Playing Templates")
            msgbox.show()
            msgbox.exec()

    def preload(self) -> None:
        """preload the known hashes for bundled templates"""
        shafile = self.bundledir.joinpath("resources", "updateshas.json")
        if shafile.exists():
            with open(shafile, encoding="utf-8") as fhin:
                self.oldshas = json.loads(fhin.read())
        else:
            logging.error("%s file is missing.", shafile)

    def check_preload(self, filename: str, userhash: str) -> str | None:
        """check if the given file matches a known hash"""
        found = None
        hexdigest = None

        if not self.oldshas:
            logging.error("updateshas.json file was not loaded.")
            return None

        if filename in self.oldshas:
            for version, hexdigest in self.oldshas[filename].items():
                if userhash == hexdigest:
                    found = version
        logging.debug(
            "filename = %s, found = %s userhash = %s hexdigest = %s",
            filename,
            found,
            userhash,
            hexdigest,
        )
        return found

    def setup_templates(self) -> None:
        """copy templates to either existing or as a new one"""

        self.preload()
        self._process_template_directory(self.apptemplatedir, self.usertemplatedir)

    def _process_template_directory(
        self,
        app_dir: str | pathlib.Path,
        user_dir: pathlib.Path,
    ) -> None:
        """recursively process template directories"""

        for apppath in pathlib.Path(app_dir).iterdir():
            # Skip files/directories that shouldn't be copied
            if apppath.name in EXCLUDED_FILES:
                continue

            if apppath.is_dir():
                # Handle subdirectories recursively
                user_subdir = user_dir / apppath.name
                user_subdir.mkdir(parents=True, exist_ok=True)
                self._process_template_directory(apppath, user_subdir)
                continue

            userpath = user_dir / apppath.name

            if not userpath.exists():
                shutil.copyfile(apppath, userpath)
                # Use relative path for logging
                relative_path = apppath.relative_to(self.apptemplatedir)
                logging.info("Added %s to %s", relative_path, user_dir)
                continue

            apphash = checksum(apppath)
            userhash = checksum(userpath)

            # If either checksum failed, treat as different to trigger replacement
            if apphash is None or userhash is None:
                logging.warning(
                    "Checksum failed for %s or %s, treating as different", apppath, userpath
                )
            elif apphash == userhash:
                continue

            # Use relative path for hash lookup
            relative_path = apppath.relative_to(self.apptemplatedir)
            if version := self.check_preload(str(relative_path), userhash):
                userpath.unlink()
                shutil.copyfile(apppath, userpath)
                logging.info("Replaced %s from %s with %s", relative_path, version, user_dir)
                continue

            destpath = userpath.with_suffix(".new")
            if destpath.exists():
                userhash = checksum(destpath)
                # Only skip if both checksums succeeded and match
                if apphash is not None and userhash is not None and apphash == userhash:
                    continue
                # If we can't checksum the .new file, or checksums don't match, overwrite it
                destpath.unlink()

            self.alert = True
            logging.info("New version of %s copied to %s", relative_path, destpath)
            shutil.copyfile(apppath, destpath)
            self.copied.append(str(relative_path))
