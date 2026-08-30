#!/usr/bin/env python3
"""Welcome page for the setup wizard."""

# pylint: disable=no-name-in-module,too-few-public-methods

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QWizardPage

from nowplaying.setupwizard._constants import PAGE_MULTIPC


class _WelcomePage(QWizardPage):
    """Introductory page shown at wizard start."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Welcome to What's Now Playing")
        layout = QVBoxLayout()
        intro = QLabel(
            "You will pick the DJ software to read from, confirm that What's Now "
            "Playing can see the current track, and choose where that "
            "information goes.\n\n"
            "Everything else can be changed later in Settings.\n\n"
            "Click Next to begin."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addStretch()
        self.setLayout(layout)

    def nextId(self) -> int:  # pylint: disable=invalid-name,no-self-use
        """Go to the multi-PC question before anything else."""
        return PAGE_MULTIPC
