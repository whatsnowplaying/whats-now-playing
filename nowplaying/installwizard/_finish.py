#!/usr/bin/env python3
"""Finish / summary page for the installation wizard."""

# pylint: disable=no-name-in-module,too-few-public-methods

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QWizardPage


class _FinishPage(QWizardPage):
    """Confirmation page shown before committing settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Setup Complete")
        layout = QVBoxLayout()
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._summary)
        note = QLabel(
            "\nAll settings can be adjusted later via the What's Now Playing Settings menu."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.setLayout(layout)

    def nextId(self) -> int:  # pylint: disable=invalid-name,no-self-use
        """Terminal page — returning -1 makes Qt show the Finish button."""
        return -1

    def set_summary(
        self,
        input_display: str,
        extra_names: list[str],
        output_names: list[str],
    ) -> None:
        """Populate the summary with chosen input, artist extras, and outputs."""
        extras = ", ".join(extra_names) if extra_names else "none selected"
        outputs = ", ".join(output_names) if output_names else "none selected"
        self._summary.setText(
            f"<b>Input source:</b>  {input_display}<br><br>"
            f"<b>Artist information:</b>  {extras}<br><br>"
            f"<b>Outputs:</b>  {outputs}<br><br>"
            "Click <b>Finish</b> to save these settings and start "
            "What's Now Playing."
        )
