#!/usr/bin/env python3
''' test metadata '''

import os
import logging

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


def test_artistshortio(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    metadata = {
        'filename':
        os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.mp3'),
        'artistlongbio':
        '''
Industrial rock band Nine Inch Nails (abbreviated as NIN and stylized as NIИ) was
formed in 1988 by Trent Reznor in Cleveland, Ohio. Reznor has served as the main
producer, singer, songwriter, instrumentalist, and sole member of Nine Inch Nails
for 28 years. This changed in December 2016 when Atticus Ross officially became
the second member of the band. Nine Inch Nails straddles a wide range of many
styles of rock music and other genres that
require an electronic sound, which can often cause drastic changes in sound from
album to album. However NIN albums in general have many identifiable characteristics
in common, such as recurring leitmotifs, chromatic melodies, dissonance, terraced
dynamics and common lyrical themes. Nine Inch Nails is most famously known for the
melding of industrial elements with pop sensibilities in their first albums. This
move was considered instrumental in
bringing the industrial genre as a whole into the mainstream, although genre purists
and Trent Reznor alike have refused to identify NIN as an industrial band.
'''
    }

    shortbio = \
'Industrial rock band Nine Inch Nails (abbreviated as NIN and stylized as NIИ) was formed' \
' in 1988 by Trent Reznor in Cleveland, Ohio. Reznor has served as the main producer, singer,' \
' songwriter, instrumentalist, and sole member of Nine Inch Nails for 28 years. This changed' \
' in December 2016 when Atticus Ross officially became the second member of the band.'

    myclass = nowplaying.metadata.MetadataProcessors(metadata=metadata,
                                                     config=config)
    metadata = myclass.metadata
    logging.debug(metadata['artistshortbio'])
    assert metadata['artistshortbio'] == shortbio
    assert metadata['album'] == 'Ghosts I - IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['bitrate'] == 64000
    assert metadata['track'] == '15'
    assert metadata['title'] == '15 Ghosts II'
