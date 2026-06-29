#!/usr/bin/env python3
"""helper routines for UI"""

import os
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (  # pylint: disable=import-error, no-name-in-module
    QFileDialog,
    QTabWidget,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class UIHelp:
    """utility functions for GUI code"""

    def __init__(self, config, qtui):
        if not config:
            raise AssertionError("config cannot be empty")
        if not qtui:
            raise AssertionError("qtui cannot be empty")
        self.config = config
        self.qtui = qtui

    def template_picker(self, startfile=None, startdir=None, limit="*.txt"):
        """generic code to pick a template file"""
        if startfile:
            startdir = os.path.dirname(startfile)
        elif not startdir:
            startdir = str(self.config.templatedir)
        return UIHelp.open_file_dialog(self.qtui, "Open file", startdir, limit) or None

    def template_picker_lineedit(self, qwidget, limit="*.txt"):
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

    def dir_picker_lineedit(self, qwidget, title="Select directory", startdir=None):
        """Pick a directory and set the result in a QLineEdit widget."""
        start = qwidget.text() or (str(startdir) if startdir else ".")
        if result := UIHelp.open_dir_dialog(self.qtui, title, start):
            qwidget.setText(result)

    @staticmethod
    def open_file_dialog(parent: "QWidget", title: str, startdir: str, limit: str = "*") -> str:
        """Open a file-picker dialog; return the chosen path or empty string."""
        result, _ = QFileDialog.getOpenFileName(parent, title, startdir, limit)
        return result

    @staticmethod
    def open_dir_dialog(parent: "QWidget", title: str, startdir: str) -> str:
        """Open a directory-picker dialog; return the chosen path or empty string."""
        return QFileDialog.getExistingDirectory(parent, title, startdir)

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
