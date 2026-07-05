#!/usr/bin/env python3
"""Main upgrade entry point"""

import enum
import logging
import os
import pathlib
import sys
import webbrowser

from PySide6.QtCore import Qt, QSettings  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

import nowplaying.upgrades
import nowplaying.upgrades.autoinstall
import nowplaying.upgrades.tufup_client
import nowplaying.version  # pylint: disable=import-error, no-name-in-module
from nowplaying.upgrades.config import UpgradeConfig
from nowplaying.upgrades.platform import PlatformDetector
from nowplaying.upgrades.templates import UpgradeTemplates


class ReleaseNotesDialog(QDialog):  # pylint: disable=too-few-public-methods
    """Modal child dialog showing aggregated release notes since from_version."""

    def __init__(self, newversion: str, from_version: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"What's New in v{newversion}")
        self.resize(660, 540)

        entries = nowplaying.upgrades.fetch_release_notes(from_version) or []

        content = QWidget()
        clayout = QVBoxLayout(content)
        clayout.setSpacing(12)
        clayout.setContentsMargins(16, 16, 16, 16)

        for i, entry in enumerate(entries):
            self._build_entry(clayout, entry, add_separator=i > 0)

        if not entries:
            fallback = QLabel(
                f"Release notes for v{newversion} could not be loaded.\n"
                "Check the project's GitHub releases page for details."
            )
            fallback.setWordWrap(True)
            clayout.addWidget(fallback)

        clayout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll)
        main_layout.addWidget(close_box)

    @staticmethod
    def _build_entry(clayout: QVBoxLayout, entry: dict, *, add_separator: bool) -> None:
        if add_separator:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFrameShadow(QFrame.Shadow.Sunken)
            clayout.addWidget(sep)

        ver = entry.get("version", "")
        date = entry.get("date", "")
        is_pre = entry.get("is_prerelease", False)
        notes_text = (entry.get("notes") or "").replace("\r\n", "\n").strip()

        pre_badge = (
            " <span style='color:#b45309; font-size:small;'>(pre-release)</span>" if is_pre else ""
        )
        hdr = QLabel(f"<span style='font-size:14pt; font-weight:bold;'>v{ver}</span>{pre_badge}")
        hdr.setTextFormat(Qt.TextFormat.RichText)
        clayout.addWidget(hdr)

        if date:
            date_lbl = QLabel(date)
            date_lbl.setStyleSheet("color: gray;")
            clayout.addWidget(date_lbl)

        if notes_text:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setFrameShape(QFrame.Shape.NoFrame)
            browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            browser.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
            browser.setMarkdown(notes_text)
            browser.document().documentLayout().documentSizeChanged.connect(
                lambda sz, b=browser: b.setFixedHeight(int(sz.height()) + 4)
            )
            clayout.addWidget(browser)



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
        self.newversion: str | None = None
        self.oldversion: str | None = None

        self.buttonbox = QDialogButtonBox()
        # Caller is responsible for setting offer_auto_install only when
        # all three preconditions hold: packaged binary, writable install
        # dir, and a non-null tufup_channel from the charts API.  See
        # _writable_install_dir() and upgrade() below.
        if offer_auto_install:
            install_btn = self.buttonbox.addButton("Install Now", QDialogButtonBox.AcceptRole)
            install_btn.clicked.connect(self._install_now)
        release_notes_btn = self.buttonbox.addButton("Release Notes", QDialogButtonBox.ActionRole)
        release_notes_btn.clicked.connect(self._show_release_notes)
        downloads_btn = self.buttonbox.addButton("View Downloads", QDialogButtonBox.ActionRole)
        downloads_btn.clicked.connect(self._view_downloads)
        later_btn = self.buttonbox.addButton("Remind Me Later", QDialogButtonBox.RejectRole)
        later_btn.clicked.connect(self.reject)

        self.layout = QVBoxLayout()

    def _install_now(self) -> None:
        self.action = _UpgradeAction.INSTALL_NOW
        self.accept()

    def _show_release_notes(self) -> None:
        if self.newversion and self.oldversion:
            ReleaseNotesDialog(self.newversion, self.oldversion, parent=self).exec_()

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
        cached: bool = False,
    ) -> None:
        """fill in the upgrade versions and message"""
        self.newversion = newversion
        self.oldversion = oldversion
        messages = [
            f"Your version: {oldversion}",
            f"New version: {newversion}",
        ]

        if platform_str:
            messages.append(f"Your platform: {platform_str}")

        if asset_name and (cached or asset_size_bytes is not None):
            messages.append("")
            messages.append(f"Found: {asset_name}")
            if cached:
                messages.append("Ready to install — no download needed")
            elif asset_size_bytes is not None:
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
        nowplaying.upgrades.tufup_client.cleanup_stale_targets()
        if data := nowplaying.upgrades.check_for_update(
            platform_info, prefer_prerelease=prefer_prerelease
        ):
            channel = data.get("tufup_channel")
            install_dir = _writable_install_dir()
            offer_auto_install = bool(channel and install_dir)
            cached = offer_auto_install and nowplaying.upgrades.tufup_client.has_cached_update(
                data["latest_version"]
            )
            if cached:
                logging.debug("upgrade: update archive is pre-cached — install will skip download")
            dialog = UpgradeDialog(
                offer_auto_install=offer_auto_install,
            )
            dialog.fill_it_in(
                nowplaying.version.__VERSION__,  # pylint: disable=no-member
                data["latest_version"],
                platform_str=platform_str,
                asset_name=data.get("asset_name"),
                asset_size_bytes=data.get("asset_size_bytes"),
                cached=cached,
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
                    if url := data.get("download_page_url"):
                        webbrowser.open(url)
                    sys.exit(0)
                # tufup relaunches on success; we should not get here, but
                # exit defensively if we do.
                sys.exit(0)

            if dialog.action == _UpgradeAction.VIEW_DOWNLOADS:
                if url := data.get("download_page_url"):
                    webbrowser.open(url)
                logging.info("User wants to upgrade via browser; exiting")
                sys.exit(0)
    except Exception as error:  # pylint: disable=broad-except
        logging.error(error)

    UpgradeConfig()
    UpgradeTemplates(bundledir=bundledir)
