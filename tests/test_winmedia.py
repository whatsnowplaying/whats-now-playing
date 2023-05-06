#!/usr/bin/env python3
''' test winmedia ... ok, not really. '''

import sys

import pytest
import nowplaying.inputs.winmedia  # pylint: disable=import-error

@pytest.mark.asyncio
async def test_winmedia():
    ''' entry point as a standalone app'''
    plugin = nowplaying.inputs.winmedia.Plugin()
    if metadata := await plugin.getplayingtrack():
        if 'coverimageraw' in metadata:
            del metadata['coverimageraw']

    if sys.platform == 'win32':
        assert plugin.available
    else:
        assert not plugin.available
