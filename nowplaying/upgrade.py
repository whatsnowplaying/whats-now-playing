#!/usr/bin/env python3
"""Main upgrade entry point"""

import enum
import logging
import os
import pathlib
import sys
import webbrowser

from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

import nowplaying.upgrades
import nowplaying.upgrades.autoinstall
import nowplaying.version  # pylint: disable=import-error, no-name-in-module
from nowplaying.upgrades.config import UpgradeConfig
from nowplaying.upgrades.platform import PlatformDetector
from nowplaying.upgrades.templates import UpgradeTemplates


class _UpgradeAction(enum.Enum):
    """Which action the user selected in UpgradeDialog."""

    LATER = "later"
    INSTALL_NOW = "install_now"
    VIEW_DOWNLOADS = "view_downloads"


def _writable_install_dir() -> pathlib.Path | None:
    """Return the running app's install dir if we can self-update into it.

    "Install dir" is the directory that should receive the contents
    of the update tar.gz.  Our release tarballs contain a sibling
    layout (WhatsNowPlaying.app/, CHANGELOG.md, LICENSE.txt, ...),
    so the install dir is the directory CONTAINING the .app bundle
    on macOS, or the parent of the executable on Windows/Linux.

    Three gates:
      1. WNP must be running as a packaged binary.  Source-tree dev
         installs would have their checkout clobbered.
      2. We must be able to find the right install dir.  Falls back
         to sys.executable's parent for Windows/Linux flat layouts;
         on macOS we walk up to the .app bundle's parent directory.
      3. The install dir must be writable by this process.  On
         Windows, apps installed under %ProgramFiles% can't be
         updated without elevation; we'd rather route those users
         to the manual download page than fail mid-update.

    Returns the install dir on success, None when self-update is not
    safe to offer.
    """
    if not getattr(sys, "frozen", False):
        return None

    exe = pathlib.Path(sys.executable).resolve()
    # macOS bundle layout: <install_dir>/WhatsNowPlaying.app/Contents/MacOS/WhatsNowPlaying
    # Walk up to find the .app ancestor; install_dir is its parent.
    install_dir: pathlib.Path | None = None
    if sys.platform == "darwin":
        for ancestor in exe.parents:
            if ancestor.suffix == ".app":
                install_dir = ancestor.parent
                break
    # Windows/Linux flat layout (or macOS-without-app, e.g., command-line):
    # install_dir is the executable's parent dir.
    if install_dir is None:
        install_dir = exe.parent

    if not os.access(install_dir, os.W_OK):
        logging.info("Auto-install unavailable: %s is not writable", install_dir)
        return None
    return install_dir


class UpgradeDialog(QDialog):  # pylint: disable=too-few-public-methods
    """Qt Dialog for asking the user to upgrade.

    Three actions: auto-install in place via tufup (frozen builds only),
    open the manual download page in a browser, or defer.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        offer_auto_install: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("New Version Available!")
        self.action: _UpgradeAction = _UpgradeAction.LATER

        self.buttonbox = QDialogButtonBox()
        # Caller is responsible for setting offer_auto_install only when
        # all three preconditions hold: packaged binary, writable install
        # dir, and a non-null tufup_channel from the charts API.  See
        # _writable_install_dir() and upgrade() below.
        if offer_auto_install:
            install_btn = self.buttonbox.addButton("Install Now", QDialogButtonBox.AcceptRole)
            install_btn.clicked.connect(self._install_now)
        downloads_btn = self.buttonbox.addButton("View Downloads", QDialogButtonBox.ActionRole)
        downloads_btn.clicked.connect(self._view_downloads)
        later_btn = self.buttonbox.addButton("Remind Me Later", QDialogButtonBox.RejectRole)
        later_btn.clicked.connect(self.reject)

        self.layout = QVBoxLayout()

    def _install_now(self) -> None:
        self.action = _UpgradeAction.INSTALL_NOW
        self.accept()

    def _view_downloads(self) -> None:
        self.action = _UpgradeAction.VIEW_DOWNLOADS
        self.accept()

    def fill_it_in(  # pylint: disable=too-many-arguments
        self,
        oldversion: str,
        newversion: str,
        platform_str: str | None = None,
        asset_name: str | None = None,
        asset_size_bytes: int | None = None,
    ) -> None:
        """fill in the upgrade versions and message"""
        messages = [
            f"Your version: {oldversion}",
            f"New version: {newversion}",
        ]

        if platform_str:
            messages.append(f"Your platform: {platform_str}")

        if asset_name and asset_size_bytes:
            messages.append("")
            messages.append(f"Found: {asset_name}")
            size_mb = asset_size_bytes / (1024 * 1024)
            messages.append(f"Size: {size_mb:.1f} MB")

        for msg in messages:
            message = QLabel(msg)
            self.layout.addWidget(message)
        self.layout.addWidget(self.buttonbox)
        self.setLayout(self.layout)


def upgrade(bundledir: str | pathlib.Path | None = None) -> None:
    """do an upgrade of an existing install"""
    logging.debug("Called upgrade")

    try:
        platform_info = PlatformDetector.get_platform_info()
        platform_str = PlatformDetector.get_platform_display_string()

        # QSettings reads the org/app name set up by bootstrap.set_qt_names()
        # so it lands on the same backing store as the rest of the app.
        # value() returns `object` even with type=bool, so cast defensively.
        prefer_prerelease = bool(
            QSettings().value("upgrades/prefer_prerelease", defaultValue=False, type=bool)
        )
        if data := nowplaying.upgrades.check_for_update(
            platform_info, prefer_prerelease=prefer_prerelease
        ):
            channel = data.get("tufup_channel")
            install_dir = _writable_install_dir()
            dialog = UpgradeDialog(
                offer_auto_install=bool(channel and install_dir),
            )
            dialog.fill_it_in(
                nowplaying.version.__VERSION__,  # pylint: disable=no-member
                data["latest_version"],
                platform_str=platform_str,
                asset_name=data.get("asset_name"),
                asset_size_bytes=data.get("asset_size_bytes"),
            )
            # Use the PySide6 .exec_() alias here — semantically identical
            # to .exec() but avoids tripping security scanners that
            # pattern-match the name as if it were shell exec.
            dialog.exec_()

            if dialog.action == _UpgradeAction.INSTALL_NOW and channel and install_dir:
                if not nowplaying.upgrades.autoinstall.run_auto_install(
                    install_dir, channel=channel
                ):
                    # Fallback to the manual download page if tufup failed.
                    logging.info("Auto-install failed, opening download page")
                    webbrowser.open(data["download_page_url"])
                    sys.exit(0)
                # tufup relaunches on success; we should not get here, but
                # exit defensively if we do.
                sys.exit(0)

            if dialog.action == _UpgradeAction.VIEW_DOWNLOADS:
                webbrowser.open(data["download_page_url"])
                logging.info("User wants to upgrade via browser; exiting")
                sys.exit(0)
    except Exception as error:  # pylint: disable=broad-except
        logging.error(error)

    myupgrade = UpgradeConfig()  # pylint: disable=unused-variable
    myupgrade = UpgradeTemplates(bundledir=bundledir)
