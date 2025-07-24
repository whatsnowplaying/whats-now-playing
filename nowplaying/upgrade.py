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
    ) -> None:
        """fill in the upgrade versions and message"""
        messages = [
            f"Your version: {oldversion}",
            f"New version: {newversion}",
            "Download new version?",
        ]

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
            dialog = UpgradeDialog()
            dialog.fill_it_in(upgradebin.myversion, data["tag_name"])
            if dialog.exec():
                webbrowser.open(data["html_url"])
                logging.info("User wants to upgrade; exiting")
                sys.exit(0)
    except Exception as error:  # pylint: disable=broad-except
        logging.error(error)

    myupgrade = UpgradeConfig()  # pylint: disable=unused-variable
    myupgrade = UpgradeTemplates(bundledir=bundledir)
