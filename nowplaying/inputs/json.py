#!/usr/bin/env python3
''' JSON Input Plugin definition, used for testing '''

import asyncio
import json
import logging
import pathlib

from nowplaying.inputs import InputPlugin


class Plugin(InputPlugin):
    ''' base class of input plugins '''

    def __init__(self, config=None, qsettings=None):
        ''' no custom init '''
        super().__init__(config=config, qsettings=qsettings)

    def install(self):
        ''' auto-install '''
        return False

#### Settings UI methods

    def defaults(self, qsettings):
        ''' (re-)set the default configuration values for this plugin '''

    def connect_settingsui(self, qwidget):
        ''' connect any UI elements such as buttons '''

    def load_settingsui(self, qwidget):
        ''' load values from config and populate page '''

    def verify_settingsui(self, qwidget):  #pylint: disable=no-self-use
        ''' verify the values in the UI prior to saving '''

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

    def desc_settingsui(self, qwidget):
        ''' provide a description for the plugins page '''

#### Mix Mode menu item methods

    def validmixmodes(self):  #pylint: disable=no-self-use
        ''' tell ui valid mixmodes '''
        return ['newest']

    def setmixmode(self, mixmode):  #pylint: disable=no-self-use
        ''' handle user switching the mix mode: TBD '''
        return 'newest'

    def getmixmode(self):  #pylint: disable=no-self-use
        ''' return what the current mixmode is set to '''
        return 'newest'

#### Data feed methods

    async def getplayingtrack(self):
        ''' Get the currently playing track '''
        await asyncio.sleep(
            self.config.cparser.value('jsoninput/delay',
                                      type=int,
                                      defaultValue=5))
        filepath = pathlib.Path(
            self.config.cparser.value('jsoninput/filename'))

        if not filepath.exists():
            logging.debug('%s does not exist', filepath)
            return {}

        try:
            with open(filepath, mode='r', encoding='utf-8') as fhin:
                return json.load(fhin)
        except Exception as error:  # pylint: disable=broad-except
            logging.debug(error)

        return {}


#### Control methods

    async def start(self):
        ''' any initialization before actual polling starts '''

    async def stop(self):
        ''' stopping either the entire program or just this
            input '''
