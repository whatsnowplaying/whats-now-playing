#!/usr/bin/env python3
''' Input Plugin definition '''

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget  # pylint: disable=import-error, no-name-in-module

if TYPE_CHECKING:
    import nowplaying.config
    from PySide6.QtCore import QSettings # pylint: disable=no-name-in-module

class WNPBasePlugin:
    ''' base class of plugins '''

    def __init__(self,
                 config: "nowplaying.config.ConfigFile | None" = None,
                 qsettings: QWidget | None = None):
        self.available: bool = True
        self.plugintype: str = ''
        self.config: "nowplaying.config.ConfigFile | None" = config
        self.qwidget: QWidget | None = None
        self.uihelp: object | None = None
        self.displayname: str = ''
        self.priority: int = 0

        if qsettings:
            self.defaults(qsettings)
            return

        if not self.config:
            logging.debug('Plugin was not called with config')


#### Settings UI methods

    def defaults(self, qsettings: "QSettings") -> None:
        ''' (re-)set the default configuration values for this plugin '''

    def connect_settingsui(self, qwidget: QWidget, uihelp: object) -> None:
        ''' connect any UI elements such as buttons '''
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget: QWidget) -> None:
        ''' load values from config and populate page '''

    def verify_settingsui(self, qwidget: QWidget) -> bool:  #pylint: disable=no-self-use, unused-argument
        ''' verify the values in the UI prior to saving '''
        return True

    def save_settingsui(self, qwidget: QWidget) -> None:
        ''' take the settings page and save it '''
