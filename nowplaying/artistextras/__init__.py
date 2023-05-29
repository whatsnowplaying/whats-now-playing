#!/usr/bin/env python3
''' Input Plugin definition '''

import logging
import sys
import typing as t

from nowplaying.plugin import WNPBasePlugin


class ArtistExtrasPlugin(WNPBasePlugin):
    ''' base class of plugins '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype: str = 'artistextras'

#### Plug-in methods

    def download(self, metadata: t.Optional[dict[str, t.Any]] = None, imagecache=None) -> dict:  # pylint: disable=no-self-use,unused-argument
        ''' return metadata '''
        return {}

    def providerinfo(self) -> list:  #pylint: disable=no-self-use, unused-argument
        ''' return list of what is provided by this recognition system '''
        return []


#### Utilities

    def calculate_delay(self) -> float:
        ''' determine a reasonable, minimal delay '''

        delay: float = 10.0

        try:
            delay = self.config.cparser.value('settings/delay', type=float, defaultValue=10.0)
        except ValueError:
            pass

        if sys.platform == 'win32':
            delay = max(delay / 2, 10)
        else:
            delay = max(delay / 2, 5)

        return delay
