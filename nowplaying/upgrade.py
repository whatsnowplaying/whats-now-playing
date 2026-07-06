#!/usr/bin/env python3
"""Main upgrade entry point"""

import logging
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


class UpgradeDialog(QDialog):  # pylint: disable=too-few-public-methods
    """Qt Dialog for asking the user to upgrade"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New Version Available!")
        self.newversion: str | None = None
        self.oldversion: str | None = None
        dialogbuttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        self.buttonbox = QDialogButtonBox(dialogbuttons)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)
        release_notes_btn = self.buttonbox.addButton("Release Notes", QDialogButtonBox.ActionRole)
        release_notes_btn.clicked.connect(self._show_release_notes)
        self.layout = QVBoxLayout()

    def _show_release_notes(self) -> None:
        if self.newversion and self.oldversion:
            ReleaseNotesDialog(self.newversion, self.oldversion, parent=self).exec_()

    def fill_it_in(  # pylint: disable=too-many-arguments
        self,
        oldversion: str,
        newversion: str,
        platform_str: str | None = None,
        asset_name: str | None = None,
        asset_size_bytes: int | None = None,
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

        if asset_name and asset_size_bytes:
            messages.append("")
            messages.append(f"Found: {asset_name}")
            size_mb = asset_size_bytes / (1024 * 1024)
            messages.append(f"Size: {size_mb:.1f} MB")
            messages.append("")
            messages.append("Download new version?")
        else:
            messages.append("")
            messages.append("No direct download available.")
            messages.append("Open download page?")

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
            dialog = UpgradeDialog()
            dialog.fill_it_in(
                nowplaying.version.__VERSION__,  # pylint: disable=no-member
                data["latest_version"],
                platform_str=platform_str,
                asset_name=data.get("asset_name"),
                asset_size_bytes=data.get("asset_size_bytes"),
            )

            if dialog.exec():
                webbrowser.open(data["download_page_url"])
                logging.info("User wants to upgrade; exiting")
                sys.exit(0)
    except Exception as error:  # pylint: disable=broad-except
        logging.error(error)

    myupgrade = UpgradeConfig()  # pylint: disable=unused-variable
    myupgrade = UpgradeTemplates(bundledir=bundledir)
