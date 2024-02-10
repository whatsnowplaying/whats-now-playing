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
    metadatain = {'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.mp3')}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['bitrate'] == 64000
    assert metadataout['imagecacheartist'] == 'nine inch nails'
    assert metadataout['track'] == '15'
    assert metadataout['title'] == '15 Ghosts II'
    assert metadataout['duration'] == 110


@pytest.mark.asyncio
async def test_15ghosts2_mp3_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_füllytâgged.mp3')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['acoustidid'] == '02d23182-de8b-493e-a6e1-e011bfdacbcf'
    assert metadataout['album'] == 'Ghosts I-IV'
    assert metadataout['albumartist'] == 'Nine Inch Nails'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['artistwebsites'] == ['https://www.nin.com/']
    assert metadataout['coverimagetype'] == 'png'
    assert metadataout['coverurl'] == 'cover.png'
    assert metadataout['date'] == '2008'
    assert metadataout['imagecacheartist'] == 'nine inch nails'
    assert metadataout['isrc'] == ['USTC40852243']
    assert metadataout['label'] == 'The Null Corporation'
    assert metadataout['musicbrainzalbumid'] == '3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a'
    assert metadataout['musicbrainzartistid'] == ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']
    assert metadataout['musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadataout['title'] == '15 Ghosts II'
    assert metadataout['duration'] == 110


@pytest.mark.asyncio
async def test_15ghosts2_flac_orig(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.flac')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['imagecacheartist'] == 'nine inch nails'
    assert metadataout['track'] == '15'
    assert metadataout['title'] == '15 Ghosts II'
    assert metadataout['duration'] == 113


@pytest.mark.asyncio
async def test_15ghosts2_m4a_orig(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.m4a')}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['bitrate'] == 705600
    assert metadataout['imagecacheartist'] == 'nine inch nails'
    assert metadataout['track'] == '15'
    assert metadataout['title'] == '15 Ghosts II'
    assert metadataout['duration'] == 113


@pytest.mark.asyncio
async def test_15ghosts2_aiff_orig(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.aiff')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['imagecacheartist'] == 'nine inch nails'
    assert metadataout['track'] == '15'
    assert metadataout['title'] == '15 Ghosts II'
    assert metadataout['duration'] == 113


@pytest.mark.asyncio
async def test_15ghosts2_flac_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_füllytâgged.flac')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )

    assert metadataout['acoustidid'] == '02d23182-de8b-493e-a6e1-e011bfdacbcf'
    assert metadataout['album'] == 'Ghosts I-IV'
    assert metadataout['albumartist'] == 'Nine Inch Nails'
    assert metadataout['artistwebsites'] == ['https://www.nin.com/']
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['coverimagetype'] == 'png'
    assert metadataout['coverurl'] == 'cover.png'
    assert metadataout['date'] == '2008-03-02'
    assert metadataout['imagecacheartist'] == 'nine inch nails'
    assert metadataout['isrc'] == ['USTC40852243']
    assert metadataout['label'] == 'The Null Corporation'
    assert metadataout['musicbrainzalbumid'] == '3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a'
    assert metadataout['musicbrainzartistid'] == ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']
    assert metadataout['musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadataout['title'] == '15 Ghosts II'
    assert metadataout['duration'] == 113


@pytest.mark.asyncio
async def test_15ghosts2_m4a_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_füllytâgged.m4a')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )

    assert metadataout['acoustidid'] == '02d23182-de8b-493e-a6e1-e011bfdacbcf'
    assert metadataout['album'] == 'Ghosts I-IV'
    assert metadataout['albumartist'] == 'Nine Inch Nails'
    assert metadataout['artistwebsites'] == ['https://www.nin.com/']
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['coverimagetype'] == 'png'
    assert metadataout['coverurl'] == 'cover.png'
    assert metadataout['date'] == '2008-03-02'
    assert metadataout['imagecacheartist'] == 'nine inch nails'
    assert metadataout['isrc'] == ['USTC40852243']
    assert metadataout['label'] == 'The Null Corporation'
    assert metadataout['musicbrainzalbumid'] == '3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a'
    assert metadataout['musicbrainzartistid'] == ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']
    assert metadataout['musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadataout['title'] == '15 Ghosts II'
    assert metadataout['duration'] == 113


@pytest.mark.asyncio
async def test_15ghosts2_aiff_fullytagged(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_füllytâgged.aiff')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )

    assert metadataout['album'] == 'Ghosts I-IV'
    assert metadataout['albumartist'] == 'Nine Inch Nails'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['coverimagetype'] == 'png'
    assert metadataout['coverurl'] == 'cover.png'
    assert metadataout['imagecacheartist'] == 'nine inch nails'
    assert metadataout['isrc'] == ['USTC40852243']
    assert metadataout['title'] == '15 Ghosts II'
    assert metadataout['duration'] == 113


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

    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    logging.debug(metadataout['artistshortbio'])
    assert metadataout['artistshortbio'] == shortbio
    assert metadataout['album'] == 'Ghosts I - IV'
    assert metadataout['artist'] == 'Nine Inch Nails'
    assert metadataout['bitrate'] == 64000
    assert metadataout['imagecacheartist'] == 'nine inch nails'
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
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
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
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
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
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
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
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
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
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
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
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['date'] == '1999'
    assert not metadataout.get('year')


@pytest.mark.asyncio
async def test_url_dedupe1(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', False)
    metadatain = {'artistwebsites': ['http://example.com', 'http://example.com/']}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['artistwebsites'] == ['http://example.com/']


@pytest.mark.asyncio
async def test_url_dedupe2(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', False)
    metadatain = {'artistwebsites': ['http://example.com', 'https://example.com/']}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['artistwebsites'] == ['https://example.com/']


@pytest.mark.asyncio
async def test_url_dedupe3(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', False)
    metadatain = {'artistwebsites': ['https://example.com', 'http://example.com/']}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['artistwebsites'] == ['https://example.com/']


@pytest.mark.asyncio
async def test_url_dedupe4(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', False)
    metadatain = {
        'artistwebsites':
        ['https://example.com', 'https://whatsnowplaying.github.io', 'http://example.com/']
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['artistwebsites'] == [
        'https://example.com/', 'https://whatsnowplaying.github.io/'
    ]


@pytest.mark.asyncio
async def test_broken_duration(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', False)
    metadatain = {'duration': '1 hour 10 minutes'}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert not metadataout.get('duration')


@pytest.mark.asyncio
async def test_str_duration(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('settings/stripextras', False)
    metadatain = {'duration': '1'}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['duration'] == 1


@pytest.mark.asyncio
async def test_year_zeronum(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    metadatain = {'date': 0}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert not metadataout.get('date')


@pytest.mark.asyncio
async def test_year_zerostr(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    metadatain = {'date': '0'}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert not metadataout.get('date')


@pytest.mark.asyncio
async def test_youtube(bootstrap):
    ''' test the stupid hack for youtube downloaded videos '''
    config = bootstrap
    metadatain = {
        'artist': 'fakeartist',
        'title': 'Pet Shop Boys - Can You Forgive Her?',
        'comments': 'http://youtube.com/watch?v=xxxxxxx'
    }
    mdp = nowplaying.metadata.MetadataProcessors(config=config)
    metadataout = await mdp.getmoremetadata(metadata=metadatain)
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )

    # might get either album or single
    assert metadataout['album'] in ['Very Relentless', 'Can You Forgive Her?']
    assert metadataout['artist'] == 'Pet Shop Boys'
    assert metadataout['imagecacheartist'] == 'pet shop boys'
    assert metadataout['label'] in ['EMI', 'Parlophone']
    assert metadataout['musicbrainzartistid'] == ['be540c02-7898-4b79-9acc-c8122c7d9e83']
    assert metadataout['musicbrainzrecordingid'] in [
        '0e0bc5b5-28d0-4f42-8bf8-1cf4187ee738', '2c0bb21b-805b-4e13-b2da-6a52d398f4f6'
    ]
    assert metadataout['title'] == 'Can You Forgive Her?'


@pytest.mark.asyncio
async def test_discogs_from_mb(bootstrap):  # pylint: disable=redefined-outer-name
    ''' noimagecache '''

    if not os.environ.get('DISCOGS_API_KEY'):
        return

    config = bootstrap
    config.cparser.setValue('acoustidmb/homepage', False)
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    config.cparser.setValue('musicbrainz/enabled', True)
    config.cparser.setValue('discogs/enabled', True)
    config.cparser.setValue('discogs/bio', True)
    config.cparser.setValue('musicbrainz/fallback', True)
    metadatain = {'artist': 'TR/ST', 'title': 'Iris'}
    mdp = nowplaying.metadata.MetadataProcessors(config=config)
    metadataout = await mdp.getmoremetadata(metadata=metadatain)
    del metadataout['coverimageraw']
    assert metadataout['album'] == 'Iris'
    assert metadataout['artistwebsites'] == ['https://www.discogs.com/artist/2028711']
    assert metadataout['artist'] == 'TR/ST'
    assert metadataout['date'] == '2019-07-25'
    assert metadataout['imagecacheartist'] == 'tr st'
    assert metadataout['label'] == 'House Arrest'
    assert metadataout['musicbrainzartistid'] == ['b8e3d1ae-5983-4af1-b226-aa009b294111']
    assert metadataout['musicbrainzrecordingid'] == '9ecf96f5-dbba-4fda-a5cf-7728837fb1b6'
    assert metadataout['title'] == 'Iris'


@pytest.mark.asyncio
async def test_keeptitle_despite_mb(bootstrap):  # pylint: disable=redefined-outer-name
    ''' noimagecache '''

    if not os.environ.get('DISCOGS_API_KEY'):
        return

    config = bootstrap
    config.cparser.setValue('acoustidmb/homepage', False)
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    config.cparser.setValue('musicbrainz/enabled', True)
    config.cparser.setValue('musicbrainz/fallback', True)
    metadatain = {
        'artist': 'Simple Minds',
        'title': 'Don\'t You (Forget About Me) (DJ Paulharwood Remix)'
    }
    mdp = nowplaying.metadata.MetadataProcessors(config=config)
    metadataout = await mdp.getmoremetadata(metadata=metadatain)
    assert not metadataout.get('album')
    assert metadataout['artistwebsites'] == ['https://www.discogs.com/artist/18547']
    assert metadataout['artist'] == 'Simple Minds'
    assert not metadataout.get('date')
    assert metadataout['imagecacheartist'] == 'simple minds'
    assert not metadataout.get('label')
    assert metadataout['musicbrainzartistid'] == ['f41490ce-fe39-435d-86c0-ab5ce098b423']
    assert not metadataout.get('musicbrainzrecordingid')
    assert metadataout['title'] == 'Don\'t You (Forget About Me) (DJ Paulharwood Remix)'


@pytest.mark.asyncio
async def test_15ghosts2_m4a_fake_origdate(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_fake_origdate.m4a')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['date'] == '1982-01-01'


@pytest.mark.asyncio
async def test_15ghosts2_m4a_fake_origyear(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_fake_origyear.m4a')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['date'] == '1983'


@pytest.mark.asyncio
async def test_15ghosts2_m4a_fake_both(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_fake_ody.m4a')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['date'] == '1982-01-01'


@pytest.mark.asyncio
async def test_15ghosts2_mp3_fake_origdate(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_fake_origdate.mp3')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['date'] == '1982'


@pytest.mark.asyncio
async def test_15ghosts2_mp3_fake_origyear(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_fake_origyear.mp3')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['date'] == '1983'


@pytest.mark.asyncio
async def test_15ghosts2_mp3_fake_origboth(bootstrap, getroot):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', False)
    metadatain = {
        'filename': os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_fake_ody.mp3')
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config
                                                               ).getmoremetadata(metadata=metadatain
                                                                                 )
    assert metadataout['date'] == '1982'
