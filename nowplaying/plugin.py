#!/usr/bin/env python3
''' Input Plugin definition '''

import logging


class WNPBasePlugin:
    ''' base class of plugins '''

    def __init__(self, config=None, qsettings=None):
        self.available = True
        self.plugintype = None
        self.config = config
        self.qwidget = None
        self.uihelp = None
        self.displayname = None

        if qsettings:
            self.defaults(qsettings)
            return

        if not self.config:
            logging.debug('Plugin was not called with config')


#### Settings UI methods

    def defaults(self, qsettings):
        ''' (re-)set the default configuration values for this plugin '''

    def connect_settingsui(self, qwidget, uihelp):
        ''' connect any UI elements such as buttons '''
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget):
        ''' load values from config and populate page '''

    def verify_settingsui(self, qwidget):  #pylint: disable=no-self-use
        ''' verify the values in the UI prior to saving '''

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
