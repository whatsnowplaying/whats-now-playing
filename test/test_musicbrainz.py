#!/usr/bin/env python3
''' test acoustid '''

import os

import logging
import logging.config
import logging.handlers

import nowplaying.bootstrap # pylint: disable=import-error
import nowplaying.config # pylint: disable=import-error
import nowplaying.metadata # pylint: disable=import-error


def bootstrap():
    ''' bootstrap test '''
    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names(appname='testsuite')
    return nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)


def test_15ghosts2_orig():
    ''' automated integration test '''
    config = bootstrap()
    metadata = {'filename': 'test/audio/15_Ghosts_II_64kb_orig.mp3'}
    myclass = nowplaying.metadata.MetadataProcessors(metadata=metadata, config=config)
    metadata = myclass.metadata
    config.cparser.clear()
    assert metadata['album'] == 'Ghosts I - IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['bitrate'] == 64000
    assert metadata['track'] == '15'
    assert metadata['title'] == '15 Ghosts II'



def test_15ghosts2_fullytagged():
    ''' automated integration test '''
    config = bootstrap()
    metadata = {'filename': 'test/audio/15_Ghosts_II_64kb_fullytagged.mp3'}
    myclass = nowplaying.metadata.MetadataProcessors(metadata=metadata, config=config)
    metadata = myclass.metadata
    config.cparser.clear()
    assert metadata['acoustidid'] == '02d23182-de8b-493e-a6e1-e011bfdacbcf'
    assert metadata['album'] == 'Ghosts I-IV'
    assert metadata['albumartist'] == 'Nine Inch Nails'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['coverimagetype'] == 'png'
    assert metadata['coverurl'] == 'cover.png'
    assert metadata['date'] == '2008'
    assert metadata['isrc'] == 'USTC40852243'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata['musicbrainzalbumid'] == '3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a'
    assert metadata['musicbrainzartistid'] == 'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    assert metadata['musicbrainzrecordingid'] == '168cb2db-5626-30c5-b822-dbf2324c2f49'
    assert metadata['title'] == '15 Ghosts II'


if __name__ == "__main__":
    test_15ghosts2_orig()
    test_15ghosts2_fullytagged()
