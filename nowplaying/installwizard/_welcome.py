#!/usr/bin/env python3
"""Welcome page for the installation wizard."""

# pylint: disable=no-name-in-module,too-few-public-methods

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QWizardPage


class _WelcomePage(QWizardPage):
    """Introductory page shown at wizard start."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Welcome to What's Now Playing")
        layout = QVBoxLayout()
        intro = QLabel(
            "This wizard will help you get started quickly.\n\n"
            "You will choose your DJ software source, configure "
            "artist information services, and select outputs. "
            "Everything can be changed later via Preferences.\n\n"
            "Click Next to begin."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addStretch()
        self.setLayout(layout)
