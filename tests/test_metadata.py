#!/usr/bin/env python3
''' test metadata '''

import os
import logging

import pytest

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.metadata  # pylint: disable=import-error
import nowplaying.upgrade  # pylint: disable=import-error


@pytest.mark.asyncio
async def test_15ghosts2_mp3_orig(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename':
        os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.mp3')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['bitrate'] == 64000
    assert metadataout['track'] == '15'
    assert metadataout['title'] == '15 Ghosts II'


@pytest.mark.asyncio
async def test_15ghosts2_mp3_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename':
        os.path.join(getroot, 'tests', 'audio',
                     '15_Ghosts_II_64kb_füllytâgged.mp3')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['acoustidid'] == '02d23182-de8b-493e-a6e1-e011bfdacbcf'
    assert metadataout['album'] == 'Ghosts I-IV'
    assert metadataout['albumartist'] == 'Nine Inch Nails'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['artistwebsites'] == ['https://www.nin.com/']
    assert metadataout['coverimagetype'] == 'png'
    assert metadataout['coverurl'] == 'cover.png'
    assert metadataout['date'] == '2008'
    assert metadataout['isrc'] == ['USTC40852243']
    assert metadataout['label'] == 'The Null Corporation'
    assert metadataout[
        'musicbrainzalbumid'] == '3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a'
    assert metadataout['musicbrainzartistid'] == [
        'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    ]
    assert metadataout[
        'musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadataout['title'] == '15 Ghosts II'


@pytest.mark.asyncio
async def test_15ghosts2_flac_orig(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename':
        os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.flac')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['track'] == '15'
    assert metadataout['title'] == '15 Ghosts II'


@pytest.mark.asyncio
async def test_15ghosts2_m4a_orig(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename':
        os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.m4a')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['bitrate'] == 705600
    assert metadataout['track'] == '15'
    assert metadataout['title'] == '15 Ghosts II'


@pytest.mark.asyncio
async def test_15ghosts2_aiff_orig(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename':
        os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.aiff')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['track'] == '15'
    assert metadataout['title'] == '15 Ghosts II'


@pytest.mark.asyncio
async def test_15ghosts2_flac_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename':
        os.path.join(getroot, 'tests', 'audio',
                     '15_Ghosts_II_64kb_füllytâgged.flac')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)

    assert metadataout['acoustidid'] == '02d23182-de8b-493e-a6e1-e011bfdacbcf'
    assert metadataout['album'] == 'Ghosts I-IV'
    assert metadataout['albumartist'] == 'Nine Inch Nails'
    assert metadataout['artistwebsites'] == ['https://www.nin.com/']
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['coverimagetype'] == 'png'
    assert metadataout['coverurl'] == 'cover.png'
    assert metadataout['date'] == '2008-03-02'
    assert metadataout['isrc'] == ['USTC40852243']
    assert metadataout['label'] == 'The Null Corporation'
    assert metadataout[
        'musicbrainzalbumid'] == '3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a'
    assert metadataout['musicbrainzartistid'] == [
        'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    ]
    assert metadataout[
        'musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadataout['title'] == '15 Ghosts II'


@pytest.mark.asyncio
async def test_15ghosts2_m4a_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename':
        os.path.join(getroot, 'tests', 'audio',
                     '15_Ghosts_II_64kb_füllytâgged.m4a')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)

    assert metadataout['acoustidid'] == '02d23182-de8b-493e-a6e1-e011bfdacbcf'
    assert metadataout['album'] == 'Ghosts I-IV'
    assert metadataout['albumartist'] == 'Nine Inch Nails'
    assert metadataout['artistwebsites'] == ['https://www.nin.com/']
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['coverimagetype'] == 'png'
    assert metadataout['coverurl'] == 'cover.png'
    assert metadataout['date'] == '2008-03-02'
    assert metadataout['isrc'] == ['USTC40852243']
    assert metadataout['label'] == 'The Null Corporation'
    assert metadataout[
        'musicbrainzalbumid'] == '3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a'
    assert metadataout['musicbrainzartistid'] == [
        'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    ]
    assert metadataout[
        'musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadataout['title'] == '15 Ghosts II'


@pytest.mark.asyncio
async def test_15ghosts2_aiff_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename':
        os.path.join(getroot, 'tests', 'audio',
                     '15_Ghosts_II_64kb_füllytâgged.aiff')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)

    assert metadataout['album'] == 'Ghosts I-IV'
    assert metadataout['albumartist'] == 'Nine Inch Nails'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['coverimagetype'] == 'png'
    assert metadataout['coverurl'] == 'cover.png'
    assert metadataout['isrc'] == ['USTC40852243']
    assert metadataout['title'] == '15 Ghosts II'


@pytest.mark.asyncio
async def test_artistshortio(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
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

    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    logging.debug(metadataout['artistshortbio'])
    assert metadataout['artistshortbio'] == shortbio
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['bitrate'] == 64000
    assert metadataout['track'] == '15'
    assert metadataout['title'] == '15 Ghosts II'


@pytest.mark.asyncio
async def test_stripre_cleandash(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', True)
    nowplaying.upgrade.upgrade_filters(config.cparser)
    metadatain = {'title': 'Test - Clean'}
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['title'] == 'Test'


@pytest.mark.asyncio
async def test_stripre_nocleandash(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', False)
    nowplaying.upgrade.upgrade_filters(config.cparser)
    metadatain = {'title': 'Test - Clean'}
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['title'] == 'Test - Clean'


@pytest.mark.asyncio
async def test_stripre_cleanparens(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', True)
    nowplaying.upgrade.upgrade_filters(config.cparser)
    metadatain = {'title': 'Test (Clean)'}
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['title'] == 'Test'


@pytest.mark.asyncio
async def test_stripre_cleanextraparens(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', True)
    nowplaying.upgrade.upgrade_filters(config.cparser)
    metadatain = {'title': 'Test (Clean) (Single Mix)'}
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['title'] == 'Test (Single Mix)'


@pytest.mark.asyncio
async def test_publisher_not_label(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', False)
    nowplaying.upgrade.upgrade_filters(config.cparser)
    metadatain = {'publisher': 'Cool Music Publishing'}
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['label'] == 'Cool Music Publishing'
    assert not metadataout.get('publisher')


@pytest.mark.asyncio
async def test_year_not_date(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', False)
    metadatain = {'year': '1999'}
    metadataout = await nowplaying.metadata.MetadataProcessors(
        config=config).getmoremetadata(metadata=metadatain)
    assert metadataout['date'] == '1999'
    assert not metadataout.get('year')
