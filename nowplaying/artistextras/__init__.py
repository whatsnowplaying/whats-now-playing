#!/usr/bin/env python3
''' Input Plugin definition '''

import logging

from nowplaying.exceptions import PluginVerifyError


class ArtistExtrasPlugin():
    ''' base class of plugins '''

    def __init__(self, config=None, qsettings=None):
        self.plugintype = 'input'
        self.config = config
        self.qwidget = None
        self.uihelp = None

        if qsettings:
            self.defaults(qsettings)
            return

        if not self.config:
            logging.debug('Plugin was not called with config')

#### Settings UI methods

    def defaults(self, qsettings):
        ''' (re-)set the default configuration values for this plugin '''
        raise NotImplementedError

    def connect_settingsui(self, qwidget, uihelp):
        ''' connect any UI elements such as buttons '''
        raise NotImplementedError

    def load_settingsui(self, qwidget):
        ''' load values from config and populate page '''
        raise NotImplementedError

    def verify_settingsui(self, qwidget):  #pylint: disable=no-self-use
        ''' verify the values in the UI prior to saving '''
        raise PluginVerifyError('Plugin did not implement verification.')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        raise NotImplementedError


#### Plug-in methods

    def download(self, metadata=None, imagecache=None):  #pylint: disable=no-self-use
        ''' return metadata '''
        raise NotImplementedError

    def providerinfo(self):
        ''' return list of what is provided by this recognition system '''
        raise NotImplementedError
