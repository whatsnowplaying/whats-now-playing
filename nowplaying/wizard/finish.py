#!/usr/bin/env python3
"""Closing page for a feature setup wizard."""

from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QLabel,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)


class FinishPage(QWizardPage):  # pylint: disable=too-few-public-methods
    """A title and a paragraph, with nothing to fill in.

    Not to be confused with the setup wizard's own finish page, which builds a
    summary from what the user chose along the way.
    """

    def __init__(self, title: str, body: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle(title)
        label = QLabel(body)
        label.setWordWrap(True)
        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addStretch()
        self.setLayout(layout)
