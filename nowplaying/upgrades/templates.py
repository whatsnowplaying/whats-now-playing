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

            # Use relative path for logging/lookup
            relative_path = apppath.relative_to(self.apptemplatedir)

            # Debug: log actual paths being hashed
            logging.debug(
                "%s: apppath=%s (hash=%s), userpath=%s (hash=%s)",
                relative_path,
                apppath,
                apphash,
                userpath,
                userhash,
            )

            # If either checksum failed, treat as different to trigger replacement
            if apphash is None or userhash is None:
                logging.warning(
                    "Checksum failed for %s or %s, treating as different", apppath, userpath
                )
            elif apphash == userhash:
                logging.debug("%s: user file matches current template, skipping", relative_path)
                continue

            logging.debug("%s: user file differs from current template", relative_path)

            # Check if user's file matches a known old version - if so, replace it
            if version := self.check_preload(str(relative_path), userhash):
                userpath.unlink()
                shutil.copyfile(apppath, userpath)
                logging.info("Replaced %s from %s with current version", relative_path, version)
                continue

            logging.debug("%s: user file is customized (not a known version)", relative_path)

            # Check if .new file already exists and matches current template
            destpath = userpath.with_suffix(".new")
            if destpath.exists():
                logging.debug("%s: .new file exists, checking if current", relative_path)
                newhash = checksum(destpath)
                # Only skip if both checksums succeeded and match
                if apphash is not None and newhash is not None and apphash == newhash:
                    logging.debug(
                        "%s: .new file already has current template, skipping alert", relative_path
                    )
                    continue
                # If we can't checksum the .new file, or checksums don't match, overwrite it
                logging.debug(
                    "%s: .new file outdated, will overwrite (app=%s, new=%s)",
                    relative_path,
                    apphash,
                    newhash,
                )
                destpath.unlink()

            self.alert = True
            logging.info("New version of %s copied to %s", relative_path, destpath)

            # Debug: check file sizes before copy
            app_size = apppath.stat().st_size
            logging.debug("%s: app file size = %s bytes", relative_path, app_size)

            shutil.copyfile(apppath, destpath)

            # Verify the hash immediately after copying
            dest_size = destpath.stat().st_size
            verify_hash = checksum(destpath)
            logging.debug(
                "%s: verified .new file after copy (apppath=%s, destpath=%s, app=%s, new=%s, match=%s, app_size=%s, dest_size=%s)",
                relative_path,
                apppath,
                destpath,
                apphash,
                verify_hash,
                apphash == verify_hash,
                app_size,
                dest_size,
            )

            # If hashes don't match, try reading both files to see what's different
            if apphash != verify_hash:
                try:
                    with open(apppath, "rb") as f:
                        app_bytes = f.read()
                    with open(destpath, "rb") as f:
                        dest_bytes = f.read()
                    logging.warning(
                        "%s: files differ after copy! app has %s bytes, dest has %s bytes, first diff at byte %s",
                        relative_path,
                        len(app_bytes),
                        len(dest_bytes),
                        next((i for i, (a, b) in enumerate(zip(app_bytes, dest_bytes)) if a != b), -1)
                    )
                except Exception as e:  # pylint: disable=broad-except
                    logging.warning("%s: couldn't compare file contents: %s", relative_path, e)

            self.copied.append(str(relative_path))
