#!/usr/bin/env python3
"""Guided setup wizard for the OBS WebSocket output.

Launched from OBS WebSocket settings. Collects the connection details OBS
reports under Tools -> obs-websocket Settings, plus the name of the Text source
to write into.
"""

# pylint: disable=too-few-public-methods

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

import nowplaying.wizard
from nowplaying.wizard.finish import FinishPage

if TYPE_CHECKING:
    import nowplaying.config

_DEFAULT_PORT = "4455"

_FINISH_BODY = (
    "OBS WebSocket will be enabled when you save your settings.\n\n"
    "Pick the template that formats the text in Settings. The default is a "
    "plain text template."
)


class _ConnectPage(QWizardPage):
    """Collects host, port and password from OBS's own connect info."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setTitle("Connect to OBS Studio")
        self.setSubTitle(
            "In OBS, open Tools → obs-websocket Settings, enable the server, then "
            "click Show Connect Info and copy the values across."
        )

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("localhost")
        self.host_edit.setText(
            str(config.cparser.value("obsws/host", defaultValue="localhost") or "localhost")
        )

        self.port_edit = nowplaying.wizard.WizardPage.port_edit(_DEFAULT_PORT)
        self.port_edit.setText(
            str(config.cparser.value("obsws/port", type=str, defaultValue=_DEFAULT_PORT))
            or _DEFAULT_PORT
        )

        self.secret_edit = QLineEdit()
        self.secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_edit.setPlaceholderText("Server password, if you set one")
        self.secret_edit.setText(str(config.cparser.value("obsws/secret", defaultValue="") or ""))

        note = QLabel(
            "Requires OBS Studio 28 or later. Use localhost as the host if OBS and "
            "What's Now Playing run on the same machine."
        )
        note.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Host:", self.host_edit)
        form.addRow("Port:", self.port_edit)
        form.addRow("Password:", self.secret_edit)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addStretch()
        self.setLayout(layout)


class _SourcePage(QWizardPage):
    """Collects the name of the OBS Text source to write into."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setTitle("Choose the Text Source")
        self.setSubTitle(
            "WNP writes track text into an existing OBS Text source. Add one in "
            "your scene first, then enter its name exactly as it appears in OBS."
        )

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Name of the Text source in OBS")
        self.source_edit.setText(str(config.cparser.value("obsws/source", defaultValue="") or ""))
        self.source_edit.textChanged.connect(self.completeChanged)

        form = QFormLayout()
        form.addRow("Source Name:", self.source_edit)

        note = QLabel(
            "The name must match exactly, including capitalisation. WNP replaces "
            "the whole contents of that source on every track change."
        )
        note.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addStretch()
        self.setLayout(layout)

    def isComplete(self) -> bool:  # pylint: disable=invalid-name
        """Without a source name there is nowhere to write, so require one."""
        return bool(self.source_edit.text().strip())


class ObsWsWizard(QWizard):
    """Step-by-step setup wizard for the OBS WebSocket output."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Set Up OBS WebSocket")
        self.setModal(True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)

        self._connect_page = _ConnectPage(config)
        self._source_page = _SourcePage(config)

        self.addPage(self._connect_page)
        self.addPage(self._source_page)
        self.addPage(FinishPage("OBS WebSocket Setup Complete", _FINISH_BODY))

    def accept(self) -> None:
        """Write the collected values, then let the launching page reload them.

        Written on accept rather than per page so that cancelling halfway leaves
        the existing configuration alone.
        """
        cparser = self._config.cparser
        cparser.setValue("obsws/host", self._connect_page.host_edit.text().strip() or "localhost")
        cparser.setValue(
            "obsws/port", self._connect_page.port_edit.text().strip() or _DEFAULT_PORT
        )
        cparser.setValue("obsws/secret", self._connect_page.secret_edit.text())
        cparser.setValue("obsws/source", self._source_page.source_edit.text().strip())
        cparser.setValue("obsws/enabled", True)
        super().accept()
