#!/usr/bin/env python3
''' Input Plugin definition '''

import logging
from nowplaying.exceptions import PluginVerifyError


class InputPlugin():
    ''' base class of input plugins '''

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

#### Autoinstallation methods ####

    def install(self):  # pylint: disable=no-self-use
        ''' if a fresh install, run this '''
        return False

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

    def desc_settingsui(self, qwidget):
        ''' provide a description for the plugins page '''
        raise NotImplementedError

#### Mix Mode menu item methods

    def validmixmodes(self):  #pylint: disable=no-self-use
        ''' tell ui valid mixmodes '''
        #return ['newest', 'oldest']

        raise NotImplementedError

    def setmixmode(self, mixmode):  #pylint: disable=no-self-use
        ''' handle user switching the mix mode: TBD '''
        #return mixmode

        raise NotImplementedError

    def getmixmode(self):  #pylint: disable=no-self-use
        ''' return what the current mixmode is set to '''

        # mixmode may only be allowed to be in one state
        # depending upon other configuration that may be in
        # play

        #return 'newest'

        raise NotImplementedError

#### Data feed methods

    async def getplayingtrack(self):
        ''' Get the currently playing track '''
        raise NotImplementedError

    async def getrandomtrack(self, playlist):
        ''' Get the files associated with a playlist, crate, whatever '''
        raise NotImplementedError


#### Control methods

    async def start(self):
        ''' any initialization before actual polling starts '''
        raise NotImplementedError

    async def stop(self):
        ''' stopping either the entire program or just this
            input '''
        raise NotImplementedError
