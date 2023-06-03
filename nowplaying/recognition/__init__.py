#!/usr/bin/env python3
''' Input Plugin definition '''

import sys
import typing as t

#from nowplaying.exceptions import PluginVerifyError
from nowplaying.plugin import WNPBasePlugin


class RecognitionPlugin(WNPBasePlugin):
    ''' base class of recognition plugins '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype = 'recognition'

#### Recognition methods

    def recognize(self, metadata=None) -> t.Optional[dict]:  #pylint: disable=no-self-use
        ''' return metadata '''
        raise NotImplementedError

    def providerinfo(self) -> dict:
        ''' return list of what is provided by this recognition system '''
        raise NotImplementedError


#### Utilities

    def calculate_delay(self):
        ''' determine a reasonable, minimal delay '''

        try:
            delay = self.config.cparser.value('settings/delay', type=float, defaultValue=10.0)
        except ValueError:
            delay = 10.0

        if sys.platform == 'win32':
            delay = max(delay / 2, 10)
        else:
            delay = max(delay / 2, 5)

        return delay
