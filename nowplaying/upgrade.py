#!/usr/bin/env python3
"""Main upgrade entry point"""

import logging
import pathlib
import sys
import webbrowser

from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

import nowplaying.upgrades
import nowplaying.version  # pylint: disable=import-error, no-name-in-module
from nowplaying.upgrades.config import UpgradeConfig
from nowplaying.upgrades.platform import PlatformDetector
from nowplaying.upgrades.templates import UpgradeTemplates


class UpgradeDialog(QDialog):  # pylint: disable=too-few-public-methods
    """Qt Dialog for asking the user to upgrade"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New Version Available!")
        dialogbuttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        self.buttonbox = QDialogButtonBox(dialogbuttons)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)
        self.layout = QVBoxLayout()

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

        if data := nowplaying.upgrades.check_for_update(platform_info):
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
