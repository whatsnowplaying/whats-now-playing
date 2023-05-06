#!/usr/bin/env python3
''' test winmedia '''

import sys

import pytest

import nowplaying.inputs.winmedia  # pylint: disable=import-error


@pytest.mark.skipif(sys.platform != "win32", reason="needs windows")
@pytest.mark.asyncio
async def test_winmedia():
    ''' entry point as a standalone app'''
    plugin = nowplaying.inputs.winmedia.Plugin()
    if metadata := await plugin.getplayingtrack():
        if 'coverimageraw' in metadata:
            del metadata['coverimageraw']
    assert metadata
