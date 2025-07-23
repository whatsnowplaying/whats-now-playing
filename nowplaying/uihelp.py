#!/usr/bin/env python3
"""helper routines for UI"""

import os

from PySide6.QtWidgets import QFileDialog  # pylint: disable=import-error, no-name-in-module


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
        if filename := QFileDialog.getOpenFileName(self.qtui, "Open file", startdir, limit):
            return filename[0]
        return None

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
