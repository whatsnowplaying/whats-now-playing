#!/usr/bin/env python3
''' JSON Input Plugin definition, used for testing '''

import asyncio
import json
import logging
import pathlib
import random

from nowplaying.inputs import InputPlugin


class Plugin(InputPlugin):
    ''' base class of input plugins '''

    def __init__(self, config=None, qsettings=None):
        ''' no custom init '''
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "JSONReader"
        self.available = False
        self.playlists = None


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
            logging.error('%s does not exist', filepath)
            return {}

        try:
            with open(filepath, mode='rb') as fhin:
                return json.load(fhin)
        except Exception as error:  # pylint: disable=broad-except
            logging.error(error)

        return {}

    async def getrandomtrack(self, playlist):
        ''' return a random track '''
        if not self.playlists or not self.playlists.get(playlist):
            return None

        return random.choice(self.playlists[playlist])

    def load_playlists(self, dirpath, playlistfile):
        ''' load a playlist file '''
        with open(playlistfile, mode='rb') as fhin:
            datain = json.load(fhin)

        self.playlists = {}
        for listname, filelist in datain.items():
            self.playlists[listname] = [
                value.replace(
                    'ROOTPATH',
                    str(dirpath),
                ) for value in filelist
            ]
