#!/usr/bin/env python3
"""Wizard infrastructure shared between the install wizard and input plugins."""

import pathlib

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

        def __init__(
            self,
            title: str,
            placeholder: str = "",
            file_filter: str = "",
            startdir: "pathlib.Path | str | None" = None,
            parent: "QWidget | None" = None,
        ) -> None:
            super().__init__(parent)
            self._title = title
            self._file_filter = file_filter
            self._startdir = str(startdir) if startdir is not None else None

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
            if self._file_filter:
                result = nowplaying.uihelp.UIHelp.open_file_dialog(
                    self, self._title, start, self._file_filter
                )
            else:
                result = nowplaying.uihelp.UIHelp.open_dir_dialog(self, self._title, start)
            if result:
                self._edit.setText(result)

    def commit(self) -> None:
        """Write this page's settings to QSettings. Called when wizard is accepted."""
