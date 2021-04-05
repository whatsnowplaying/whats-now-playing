#!/usr/bin/env python3
''' Input Plugin definition '''

import logging

import nowplaying.config


class InputPlugin():
    ''' base class of input plugins '''
    def __init__(self, config=None, qsettings=None):
        self.plugintype = 'input'
        if config:
            self.config = config
            logging.debug('set config')

        if qsettings:
            self.defaults(qsettings)
            return

        if not config:
            self.config = nowplaying.config.ConfigFile()

    def getplayingtrack(self):
        ''' Get the currently playing track '''
        raise NotImplementedError

    def getplayingmetadata(self):
        ''' Get the metadata of the currently playing track '''
        raise NotImplementedError

    def defaults(self, qsettings):
        ''' set the default configuration values for this plugin '''
        raise NotImplementedError

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

    def stop(self):
        ''' stopping either the entire program or just this
            input '''

        raise NotImplementedError

    def load_settingsui(self, qtui):
        ''' draw the plugin's settings page '''
        raise NotImplementedError

    def save_settingsui(self, qtui):
        ''' take the settings page and save it '''
        raise NotImplementedError
