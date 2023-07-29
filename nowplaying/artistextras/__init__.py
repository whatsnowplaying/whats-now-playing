#!/usr/bin/env python3
''' Input Plugin definition '''

import contextlib
#import logging
import sys
import typing as t

from nowplaying.plugin import WNPBasePlugin


class ArtistExtrasPlugin(WNPBasePlugin):
    ''' base class of plugins '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype: str = 'artistextras'

#### Plug-in methods

    def download(self, metadata=None, imagecache=None) -> t.Optional[dict]:  #  pylint: disable=no-self-use,unused-argument
        ''' return metadata '''
        return None

    def providerinfo(self) -> t.Optional[list]:  # pylint: disable=no-self-use, unused-argument
        ''' return list of what is provided by this recognition system '''
        return None


#### Utilities

    def calculate_delay(self) -> float:
        ''' determine a reasonable, minimal delay '''

        delay: float = 10.0

        with contextlib.suppress(ValueError):
            delay = self.config.cparser.value('settings/delay', type=float, defaultValue=10.0)

        if sys.platform == 'win32':
            delay = max(delay / 2, 10)
        else:
            delay = max(delay / 2, 5)

        return delay
