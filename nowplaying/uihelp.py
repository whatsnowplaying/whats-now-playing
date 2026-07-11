#!/usr/bin/env python3
"""helper routines for UI"""

import os
import pathlib
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=import-error, no-name-in-module
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

import nowplaying.utils.templatepaths

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class TemplateChooserDialog(QDialog):  # pylint: disable=too-few-public-methods
    """Pick a template from the union of the resolution chain.

    Lists every template matching *limit* across synced, user, and bundled
    locations; user copies are marked ``(customized)``.  The "Customize a
    Copy" button materializes the selected stock template into the user's
    templates tree so it can be hand-edited.
    """

    def __init__(
        self,
        parent: "QWidget",
        config,
        limit: str | list[str] = "*.txt",
        current: str = "",
    ):
        super().__init__(parent)
        self.config = config
        # legacy QFileDialog-style filter strings may hold several
        # space-separated patterns (e.g. "*.htm *.html")
        self.patterns: list[str] = limit.split() if isinstance(limit, str) else list(limit)
        self.selected_name: str | None = None
        self.setWindowTitle("Choose template")
        self.resize(420, 420)

        layout = QVBoxLayout(self)
        self.listwidget = QListWidget()
        layout.addWidget(self.listwidget)
        self.pathlabel = QLabel("")
        self.pathlabel.setWordWrap(True)
        layout.addWidget(self.pathlabel)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.customize_button = QPushButton("Customize a Copy")
        buttons.addButton(self.customize_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.browse_button = QPushButton("Browse…")
        buttons.addButton(self.browse_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        self.customize_button.clicked.connect(self._customize_selection)
        self.browse_button.clicked.connect(self._browse_external)
        layout.addWidget(buttons)

        self.listwidget.currentItemChanged.connect(self._selection_changed)
        self.listwidget.itemDoubleClicked.connect(lambda _: self._accept_selection())
        self._populate(current)

    def _populate(self, current: str) -> None:
        self.listwidget.clear()
        current_name = pathlib.PurePath(current).name if current else ""
        # chain precedence is enforced inside list_templates(); a name
        # matching two patterns returns the identical path either way
        union: dict[str, pathlib.Path] = {}
        for pattern in self.patterns:
            union |= nowplaying.utils.templatepaths.list_templates(self.config, pattern)
        for name, path in sorted(union.items()):
            label = name
            if nowplaying.utils.templatepaths.is_user_template(self.config, path):
                label += "  (customized)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.listwidget.addItem(item)
            if name == current_name:
                self.listwidget.setCurrentItem(item)

    def _current_name(self) -> str | None:
        item = self.listwidget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self, *_) -> None:
        if name := self._current_name():
            path = nowplaying.utils.templatepaths.resolve_template(self.config, name)
            self.pathlabel.setText(str(path) if path else "")

    def _accept_selection(self) -> None:
        if name := self._current_name():
            self.selected_name = name
            self.accept()

    def _browse_external(self) -> None:
        """Pick a template file outside the chain; absolute paths stay honored."""
        filters = " ".join(self.patterns)
        result, _ = QFileDialog.getOpenFileName(
            self, "Open template file", str(self.config.templatedir), filters
        )
        if result:
            self.selected_name = result
            self.accept()

    def _customize_selection(self) -> None:
        name = self._current_name()
        if not name:
            return
        dest = nowplaying.utils.templatepaths.customize_template(self.config, name)
        if not dest:
            return
        QMessageBox.information(
            self,
            "Template copied",
            f"A copy you can edit is now at:\n{dest}\n\n"
            "Your copy overrides the built-in template.",
        )
        self._populate(name)


class UIHelp:
    """utility functions for GUI code"""

    def __init__(self, config, qtui):
        if not config:
            raise AssertionError("config cannot be empty")
        if not qtui:
            raise AssertionError("qtui cannot be empty")
        self.config = config
        self.qtui = qtui

    def template_picker(self, startfile=None, startdir=None, limit: str | list[str] = "*.txt"):  # pylint: disable=unused-argument
        """pick a template by name from the resolution chain"""
        dialog = TemplateChooserDialog(
            self.qtui, self.config, limit=limit, current=startfile or ""
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_name
        return None

    def template_picker_lineedit(self, qwidget, limit: str | list[str] = "*.txt"):
        """generic code to pick a template file"""
        if filename := self.template_picker(startfile=qwidget.text(), limit=limit):
            qwidget.setText(filename)

    def save_file_picker(
        self, title="Save file", startfile=None, startdir=None, filter_str="*.txt"
    ):
        """generic code to pick a save file location"""
        if startfile:
            startdir = os.path.dirname(startfile)
        elif not startdir:
            startdir = "."
        if filename := QFileDialog.getSaveFileName(self.qtui, title, startdir, filter_str):
            return filename[0]
        return None

    def save_file_picker_lineedit(self, qwidget, title="Save file", filter_str="*.txt"):
        """generic code to pick a save file location and set it in a line edit"""
        if filename := self.save_file_picker(
            title=title, startfile=qwidget.text(), filter_str=filter_str
        ):
            qwidget.setText(filename)

    def file_picker_lineedit(self, qwidget, title="Open file", limit="*", startdir=None):
        """Pick a file and set the result in a QLineEdit widget."""
        start = qwidget.text() or (str(startdir) if startdir else ".")
        if result := UIHelp.open_file_dialog(self.qtui, title, start, limit):
            qwidget.setText(result)

    def dir_picker_lineedit(
        self, qwidget, title="Select directory", startdir=None, allow_bundles: bool = False
    ):
        """Pick a directory and set the result in a QLineEdit widget."""
        start = qwidget.text() or (str(startdir) if startdir else ".")
        if result := UIHelp.open_dir_dialog(self.qtui, title, start, allow_bundles=allow_bundles):
            qwidget.setText(result)

    @staticmethod
    def open_file_dialog(parent: "QWidget", title: str, startdir: str, limit: str = "*") -> str:
        """Open a file-picker dialog; return the chosen path or empty string."""
        result, _ = QFileDialog.getOpenFileName(parent, title, startdir, limit)
        return result

    @staticmethod
    def open_dir_dialog(
        parent: "QWidget", title: str, startdir: str, allow_bundles: bool = False
    ) -> str:
        """Open a directory-picker dialog; return the chosen path or empty string.

        Pass allow_bundles=True on macOS when the target directory has a bundle
        extension (.djayMediaLibrary, .app, etc.) — the native picker treats those
        as files.  DontUseNativeDialog makes Qt show its own picker, which exposes
        them as plain directories.
        """
        opts = QFileDialog.Option.ShowDirsOnly
        if allow_bundles:
            opts |= QFileDialog.Option.DontUseNativeDialog
        return QFileDialog.getExistingDirectory(parent, title, startdir, opts)

    @staticmethod
    def find_widget_in_tabs(widget_container: "QWidget", widget_name: str) -> "QWidget | None":
        """Find a widget by name across tabs or in a single widget

        Args:
            widget_container: Container widget that may be a QTabWidget or regular widget
            widget_name: Name of the widget attribute to find

        Returns:
            The widget if found, None otherwise
        """
        # If the container is a QTabWidget, search across all tabs
        if isinstance(widget_container, QTabWidget):
            for i in range(widget_container.count()):
                tab_widget = widget_container.widget(i)
                if hasattr(tab_widget, widget_name):
                    return getattr(tab_widget, widget_name)
            return None

        # If it's a regular widget, search directly
        if hasattr(widget_container, widget_name):
            return getattr(widget_container, widget_name)

        return None

    @staticmethod
    def find_tab_by_identifier(
        widget_container: "QWidget", identifier_attr: str
    ) -> "QWidget | None":
        """Find a tab by checking for a specific identifier attribute

        Args:
            widget_container: Container widget that may be a QTabWidget or regular widget
            identifier_attr: Attribute name that uniquely identifies the desired tab

        Returns:
            The tab widget if found, the widget itself if not a QTabWidget, or None if not found

        Raises:
            AttributeError: If widget_container is a QTabWidget but identifier not found
        """
        if isinstance(widget_container, QTabWidget):
            # Find tab by iterating tabs and checking for identifier
            for i in range(widget_container.count()):
                tab = widget_container.widget(i)
                if hasattr(tab, identifier_attr):
                    return tab
            raise AttributeError(
                f"Tab with identifier '{identifier_attr}' not found in QTabWidget"
            )
        return widget_container
