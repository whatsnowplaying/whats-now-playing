#!/usr/bin/env python3
''' Input Plugin definition '''

#import logging
import typing as t

#from nowplaying.exceptions import PluginVerifyError
from nowplaying.plugin import WNPBasePlugin


class InputPlugin(WNPBasePlugin):
    ''' base class of input plugins '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype = 'input'

#### Additional UI method

    def desc_settingsui(self, qwidget):  # pylint: disable=no-self-use
        ''' description of this input '''
        qwidget.setText('No description available.')

#### Autoinstallation methods ####

    def install(self) -> bool:  # pylint: disable=no-self-use
        ''' if a fresh install, run this '''
        return False

#### Mix Mode menu item methods

    def validmixmodes(self) -> list[str]:  # pylint: disable=no-self-use
        ''' tell ui valid mixmodes '''
        #return ['newest', 'oldest']
        return ['newest']

    def setmixmode(self, mixmode: str) -> str:  # pylint: disable=no-self-use, unused-argument
        ''' handle user switching the mix mode: TBD '''
        return 'newest'

    def getmixmode(self) -> str:  # pylint: disable=no-self-use
        ''' return what the current mixmode is set to '''

        # mixmode may only be allowed to be in one state
        # depending upon other configuration that may be in
        # play

        return 'newest'

#### Data feed methods

    async def getplayingtrack(self) -> t.Optional[dict]:
        ''' Get the currently playing track '''
        raise NotImplementedError

    async def getrandomtrack(self, playlist: str) -> t.Optional[str]:
        ''' Get a file associated with a playlist, crate, whatever '''
        raise NotImplementedError


#### Control methods

    async def start(self):
        ''' any initialization before actual polling starts '''

    async def stop(self):
        ''' stopping either the entire program or just this
            input '''
