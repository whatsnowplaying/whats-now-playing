#!/usr/bin/env python3
''' helper routines for UI '''

import os
import typing as t

from PySide6.QtWidgets import QFileDialog, QWidget  # pylint: disable=import-error, no-name-in-module


class UIHelp:
    ''' utility functions for GUI code'''

    def __init__(self, config, qtui: t.Optional[QWidget]):
        if not qtui:
            raise AssertionError('qtui cannot be empty')
        self.config = config
        self.qtui = qtui

    def template_picker(self,
                        startfile: t.Optional[str] = None,
                        startdir: t.Optional[str] = None,
                        limit: str = '*.txt') -> t.Optional[str]:
        ''' generic code to pick a template file '''
        if startfile:
            startdir = os.path.dirname(startfile)
        elif not startdir:
            startdir = os.path.join(self.config.templatedir, "templates")
        if filename := QFileDialog.getOpenFileName(self.qtui, 'Open file', startdir, limit):
            return filename[0]
        return None

    def template_picker_lineedit(self, qwidget: QWidget, limit: str = '*.txt'):
        ''' generic code to pick a template file '''
        if filename := self.template_picker(startfile=qwidget.text(), limit=limit):
            qwidget.setText(filename)
