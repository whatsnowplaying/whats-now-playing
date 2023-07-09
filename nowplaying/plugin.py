#!/usr/bin/env python3
''' Input Plugin definition '''

import logging
import typing as t

from PySide6.QtWidgets import QWidget  # pylint: disable=import-error, no-name-in-module


class WNPBasePlugin:
    ''' base class of plugins '''

    def __init__(self,
                 config: t.Optional['nowplaying.config.ConfigFile'] = None,
                 qsettings: t.Optional[QWidget] = None):
        self.available: bool = True
        self.plugintype: str = ''
        self.config = config
        self.qwidget: t.Optional[QWidget] = None
        self.uihelp = None
        self.displayname: str = ''
        self.priority = 0

        if qsettings:
            self.defaults(qsettings)
            return

        if not self.config:
            logging.debug('Plugin was not called with config')


#### Settings UI methods

    def defaults(self, qsettings: QWidget):
        ''' (re-)set the default configuration values for this plugin '''

    def connect_settingsui(self, qwidget: QWidget, uihelp):
        ''' connect any UI elements such as buttons '''
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget: QWidget):
        ''' load values from config and populate page '''

    def verify_settingsui(self, qwidget: QWidget) -> bool:  #pylint: disable=no-self-use, unused-argument
        ''' verify the values in the UI prior to saving '''
        return True

    def save_settingsui(self, qwidget: QWidget):
        ''' take the settings page and save it '''
