#!/usr/bin/env python3
"""Wizard infrastructure shared between the install wizard and input plugins."""

import pathlib

from PySide6.QtGui import QIntValidator  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
    QWizardPage,
)

import nowplaying.uihelp


class WizardPage(QWizardPage):  # pylint: disable=too-few-public-methods
    """Base class for plugin-provided first-run wizard pages.

    Plugin files define a subclass, then assign:
        self.wizardpage = _TheirPageClass
    in Plugin.__init__().  The install wizard instantiates it as:
        plugin.wizardpage(config=...)
    """

    class PathEdit(QWidget):
        """QLineEdit + Browse button for file or directory pickers.

        Pass file_filter (e.g. '*.nml') for a file picker; omit it (or pass '')
        for a directory picker.  Pass startdir for a smarter initial browse
        location when the field is empty.
        """

        def __init__(  # pylint: disable=too-many-arguments
            self,
            title: str,
            placeholder: str = "",
            file_filter: str = "",
            startdir: "pathlib.Path | str | None" = None,
            allow_bundles: bool = False,
            parent: "QWidget | None" = None,
        ) -> None:
            super().__init__(parent)
            self._title = title
            self._file_filter = file_filter
            self._startdir = str(startdir) if startdir is not None else None
            self._allow_bundles = allow_bundles

            self._edit = QLineEdit()
            self._edit.setPlaceholderText(placeholder)

            browse_btn = QPushButton("Browse…")
            browse_btn.clicked.connect(self._browse)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self._edit)
            layout.addWidget(browse_btn)

        def text(self) -> str:
            """Return the current path text."""
            return self._edit.text()

        def setText(self, text: str) -> None:  # pylint: disable=invalid-name
            """Set the path text."""
            self._edit.setText(text)

        def _browse(self) -> None:
            start = self._edit.text() or self._startdir or str(pathlib.Path.home())
            parent = self.window() or self
            if self._file_filter:
                result = nowplaying.uihelp.UIHelp.open_file_dialog(
                    parent, self._title, start, self._file_filter
                )
            else:
                result = nowplaying.uihelp.UIHelp.open_dir_dialog(
                    parent, self._title, start, allow_bundles=self._allow_bundles
                )
            if result:
                self._edit.setText(result)

    @staticmethod
    def port_edit(placeholder: str = "", width: int = 120) -> QLineEdit:
        """Return a QLineEdit pre-validated for TCP port numbers (1–65535)."""
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setMaximumWidth(width)
        edit.setValidator(QIntValidator(1, 65535))
        return edit

    def nextId(self) -> int:  # pylint: disable=invalid-name
        """Route to the page the wizard set up for after input config, or the default."""
        wizard = self.wizard()
        override = getattr(wizard, "after_input_config_page", None)
        if override is not None:
            return override
        return super().nextId()

    def commit(self) -> None:
        """Write this page's settings to QSettings. Called when wizard is accepted."""
