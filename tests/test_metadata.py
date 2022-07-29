#!/usr/bin/env python3
''' test metadata '''

import os

import nowplaying.metadata  # pylint: disable=import-error


def test_15ghosts2_mp3_orig(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    metadata = {
        'filename':
        os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.mp3')
    }
    myclass = nowplaying.metadata.MetadataProcessors(metadata=metadata,
                                                     config=config)
    metadata = myclass.metadata
    assert metadata['album'] == 'Ghosts I - IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['bitrate'] == 64000
    assert metadata['track'] == '15'
    assert metadata['title'] == '15 Ghosts II'


def test_15ghosts2_mp3_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    metadata = {
        'filename':
        os.path.join(getroot, 'tests', 'audio',
                     '15_Ghosts_II_64kb_füllytâgged.mp3')
    }
    myclass = nowplaying.metadata.MetadataProcessors(metadata=metadata,
                                                     config=config)
    metadata = myclass.metadata
    assert metadata['acoustidid'] == '02d23182-de8b-493e-a6e1-e011bfdacbcf'
    assert metadata['album'] == 'Ghosts I-IV'
    assert metadata['albumartist'] == 'Nine Inch Nails'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['coverimagetype'] == 'png'
    assert metadata['coverurl'] == 'cover.png'
    assert metadata['date'] == '2008'
    assert metadata['isrc'] == 'USTC40852243'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata[
        'musicbrainzalbumid'] == '3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a'
    assert metadata[
        'musicbrainzartistid'] == 'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    assert metadata[
        'musicbrainzrecordingid'] == '168cb2db-5626-30c5-b822-dbf2324c2f49'
    assert metadata['title'] == '15 Ghosts II'


def test_15ghosts2_flac_orig(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    metadata = {
        'filename':
        os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.flac')
    }
    myclass = nowplaying.metadata.MetadataProcessors(metadata=metadata,
                                                     config=config)
    metadata = myclass.metadata
    assert metadata['album'] == 'Ghosts I - IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['track'] == '15'
    assert metadata['title'] == '15 Ghosts II'


def test_15ghosts2_flac_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    metadata = {
        'filename':
        os.path.join(getroot, 'tests', 'audio',
                     '15_Ghosts_II_64kb_füllytâgged.flac')
    }
    myclass = nowplaying.metadata.MetadataProcessors(metadata=metadata,
                                                     config=config)
    metadata = myclass.metadata

    assert metadata['acoustidid'] == '02d23182-de8b-493e-a6e1-e011bfdacbcf'
    assert metadata['album'] == 'Ghosts I-IV'
    assert metadata['albumartist'] == 'Nine Inch Nails'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['coverimagetype'] == 'png'
    assert metadata['coverurl'] == 'cover.png'
    assert metadata['date'] == '2008-03-02'
    assert metadata['isrc'] == 'USTC40852243'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata[
        'musicbrainzalbumid'] == '3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a'
    assert metadata[
        'musicbrainzartistid'] == 'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    assert metadata[
        'musicbrainzrecordingid'] == '168cb2db-5626-30c5-b822-dbf2324c2f49'
    assert metadata['title'] == '15 Ghosts II'
