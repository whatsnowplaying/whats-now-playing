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

from nowplaying.upgrades import UpgradeBinary
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

    def fill_it_in(
        self,
        oldversion,
        newversion,
        platform_str: str | None = None,
        asset_info: dict | None = None,
    ) -> None:
        """fill in the upgrade versions and message"""
        messages = [
            f"Your version: {oldversion}",
            f"New version: {newversion}",
        ]

        if platform_str:
            messages.append(f"Your platform: {platform_str}")

        if asset_info:
            messages.append("")  # Blank line
            messages.append(f"Found: {asset_info['name']}")
            size_mb = asset_info["size"] / (1024 * 1024)
            messages.append(f"Size: {size_mb:.1f} MB")
            messages.append("")  # Blank line
            messages.append("Download new version?")
        else:
            messages.append("")  # Blank line
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
        upgradebin = UpgradeBinary()

        if data := upgradebin.get_upgrade_data():
            # Detect platform and find matching asset
            platform_info = PlatformDetector.get_platform_info()
            platform_str = PlatformDetector.get_platform_display_string()
            asset = PlatformDetector.find_best_matching_asset(data, platform_info)

            dialog = UpgradeDialog()
            dialog.fill_it_in(
                upgradebin.myversion, data["tag_name"], platform_str=platform_str, asset_info=asset
            )

            if dialog.exec():
                # Open charts download page with platform hint for accurate detection
                os_type = platform_info.get("os", "unknown")
                chipset = platform_info.get("chipset", "")
                macos_version = platform_info.get("macos_version", "")

                base_url = "https://whatsnowplaying.com/download"
                url = f"{base_url}?os={os_type}&version={upgradebin.myversion}"
                if chipset:
                    url += f"&chipset={chipset}"
                if macos_version:
                    url += f"&macos_version={macos_version}"

                logging.info("Opening download page: %s", url)
                webbrowser.open(url)

                logging.info("User wants to upgrade; exiting")
                sys.exit(0)
    except Exception as error:  # pylint: disable=broad-except
        logging.error(error)

    myupgrade = UpgradeConfig()  # pylint: disable=unused-variable
    myupgrade = UpgradeTemplates(bundledir=bundledir)
