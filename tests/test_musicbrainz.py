#!/usr/bin/env python3
''' test musicbrainz '''

import pytest

import nowplaying.musicbrainz  # pylint: disable=import-error

# either one of these is valid for Computer Blue
COMPBLUERID = [
    'a65e5f7f-6ebc-4a2b-b476-1a10bee5b822',  # regular
    '4df9885e-6aec-4f11-8180-64d4c133d57c'  # remaster
]


@pytest.fixture
def getmusicbrainz(bootstrap):
    ''' set up MB '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', True)
    config.cparser.setValue('acoustidmb/websites', True)
    for site in ['bandcamp', 'homepage', 'lastfm', 'discogs']:
        config.cparser.setValue(f'acoustidmb/{site}', True)
    config.cparser.setValue('acoustidmb/emailaddress', 'aw+wnptest@effectivemachines.com')
    return nowplaying.musicbrainz.MusicBrainzHelper(config=config)


def test_15ghosts2_orig(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test just a recording id '''
    mbhelper = getmusicbrainz
    metadata = mbhelper.recordingid('2d7f08e1-be1c-4b86-b725-6e675b7b6de0')
    assert metadata['album'] == 'Ghosts I–IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['date'] == '2008-03-02'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata['musicbrainzartistid'] == ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']
    assert metadata['musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadata['title'] == '15 Ghosts II'


def test_15ghosts2_fullytagged(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test an isrc '''
    mbhelper = getmusicbrainz
    metadata = mbhelper.isrc(['USTC40852243'])
    assert metadata['album'] == 'Ghosts I–IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['date'] == '2008-03-02'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata['musicbrainzartistid'] == ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']
    assert metadata['musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadata['title'] == '15 Ghosts II'


def test_fallback_nin(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test standard/well known name+title '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Nine Inch Nails', 'title': '15 Ghosts II'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['artist'] == 'Nine Inch Nails'
    assert newdata['title'] == '15 Ghosts II'
    assert newdata['musicbrainzartistid'] == ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']
    assert newdata['album'] == 'Ghosts I–IV'


def test_fallback_dansesociety(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test slightly wrong artist (missing the) + semi-obscure single '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Danse Society', 'title': 'Somewhere'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == ['75ede374-68bb-4429-85fb-4b3b1421dbd1']
    assert newdata['album'] == 'Somewhere'


@pytest.mark.xfail(reason='Returns wrong data')
def test_fallback_prince_compblue(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test technically wrong artist, missing album '''
    mbhelper = getmusicbrainz
    #
    # MB has this (correctly) classified as Prince & The Revolution. But if someone has it
    # misclassified, they really should get no data. But there is an album out there
    # that lists it as Prince soooo....
    #
    metadata = {'artist': 'Prince', 'title': 'Computer Blue'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert not newdata.get('musicbrainzartistid')


def test_fallback_prince_compblue_purplerain(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' same, but with album '''
    mbhelper = getmusicbrainz
    #
    # With the album and the new filtering code, this one should also fail
    # because the only Purple Rain requires The Revolution
    #
    metadata = {'artist': 'Prince', 'title': 'Computer Blue', 'album': 'Purple Rain'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert not newdata.get('musicbrainzartistid')


def test_fallback_princeandther_compblue_purplerain(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' same, but with album '''
    mbhelper = getmusicbrainz
    #
    # With the album and the new filtering code, this one should now work
    # because the only Purple Rain requires The Revolution
    #
    metadata = {
        'artist': 'Prince & The Revolution',
        'title': 'Computer Blue',
        'album': 'Purple Rain'
    }
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata.get('musicbrainzartistid') == [
        '070d193a-845c-479f-980e-bef15710653e', '4c8ead39-b9df-4c56-a27c-51bc049cfd48'
    ]
    assert newdata.get('musicbrainzrecordingid') in COMPBLUERID


def test_fallback_princeandther_compblue(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' same, but without album '''
    mbhelper = getmusicbrainz
    #
    # this one should also work
    #
    metadata = {'artist': 'Prince & The Revolution', 'title': 'Computer Blue'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata.get('musicbrainzartistid') == [
        '070d193a-845c-479f-980e-bef15710653e', '4c8ead39-b9df-4c56-a27c-51bc049cfd48'
    ]
    assert newdata.get('musicbrainzrecordingid') in COMPBLUERID


def test_fallback_snapvsmartin(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test compilation + two artists '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Snap! vs. Martin Eyerer', 'title': 'Green Grass Grows'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == [
        'cd23732d-ffd2-444e-8884-53475d7ac7d9', '55c59886-1b2c-43ab-b83f-af62dce35bec'
    ]
    assert newdata['album'] == 'The Cult of Snap! 1990>>2003'


def test_fallback_sandervsrobbie(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test two artists + single '''
    mbhelper = getmusicbrainz
    metadata = {
        'artist': 'Sander van Doorn vs. Robbie Williams',
        'title': 'Close My Eyes (radio edit)'
    }
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == [
        '733a2394-e003-43cb-88a6-02f3b57e345b', 'db4624cf-0e44-481e-a9dc-2142b833ec2f'
    ]
    assert newdata['album'] == 'Close My Eyes'


def test_fallback_klfvsent(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test two artists + remix '''
    mbhelper = getmusicbrainz
    metadata = {
        'artist': 'The KLF vs. E.N.T.',
        'title': '3 A.M. Eternal (The KLF vs. E.N.T. Radio Freedom edit)'
    }
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == [
        '8092b8b7-235e-4844-9f72-95a9d5a73dbf', '709af0d0-dcb6-4858-b76d-05a13fc9a0a6'
    ]
    assert newdata['album'] == 'Solid State Logik 1'


def test_fallback_mareux(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test single but w/wrong remix '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Mareux', 'title': 'The Perfect Girl (Live at Coachella 2023)'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == ['09095919-c549-4f33-9555-70df9dd941e1']


def test_fallback_trslashst(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test TR/ST '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'TR/ST', 'title': 'Iris'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == ['b8e3d1ae-5983-4af1-b226-aa009b294111']
    assert newdata['musicbrainzrecordingid'] == '9ecf96f5-dbba-4fda-a5cf-7728837fb1b6'
    assert newdata['album'] == 'Iris'


def test_fallback_queen(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test large output '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Queen', 'title': 'We Will Rock You'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == ['0383dadf-2a4e-4d10-a46a-e9e041da8eb3']
    assert newdata['album'] == 'News of the World'


def test_fallback_grimesfeatjanelle(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test feat '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Grimes feat Janelle Monáe', 'title': 'Venus Fly'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == [
        '7e5a2a59-6d9f-4a17-b7c2-e1eedb7bd222', 'ee190f6b-7d98-43ec-b924-da5f8018eca0'
    ]
    assert newdata['album'] in ['Venus Fly', 'Art Angels']


def test_fallback_utterlunancy(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test various artist as only source '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Utter Lunacy', 'title': 'Monster Mash'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == ['4fc584cc-e735-467c-965b-dc2c2e9586e6']
    assert newdata['musicbrainzrecordingid'] == 'c09d592e-13e5-4374-bc67-9d651dac6fc9'
    assert newdata['album'] == 'Leatherface: The Texas Chainsaw Massacre III'


def test_fallback_jackielipson(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test missing entirely '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Jackie Lipson', 'title': 'Someday'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert not newdata.get('musicbrainzartistid')
    assert not newdata.get('musicbrainzrecordingid')
    assert not newdata.get('album')


def test_fallback_acdc_tnt_nodots(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test missing song and remix with wrong name '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'AC/DC', 'title': 'TNT (Freak On Remix)'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == ['66c662b6-6e2f-4930-8610-912e24c63ed1']
    #
    # ideally, we'd just return the artistid bz the rest of the info is wrong
    #
    assert not metadata.get('musicbrainzrecordingid')


def test_fallback_acdc_tnt_dots(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' test missing song but at least this time remix has correct name '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'AC/DC', 'title': 'T.N.T. (Freak On Remix)'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == ['66c662b6-6e2f-4930-8610-912e24c63ed1']
    #
    # ideally, we'd just return the artistid bz the rest of the info is wrong
    #
    assert not metadata.get('musicbrainzrecordingid')


def test_fallback_davidbowie(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' this one failed to get bio once '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'David Bowie', 'title': 'Golden Years (Live on Serious Moonlight Tour)'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata.get('musicbrainzartistid') == ['5441c29d-3602-4898-b1a1-b77fa23b8e50']
    assert not newdata.get('musicbrainzrecordingid')


def test_fallback_complex_and_with_feature(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' a very complex one. get the wrong recording id which is correctly rejected though '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Troye Sivan & Kacey Musgraves feat Mark Ronson', 'title': 'Easy'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata.get('musicbrainzartistid') == [
        'e5712ceb-c37a-4c49-a11c-ccf4e21852d4', 'd1393ecb-431b-4fde-a6ea-d769f2f040cb',
        'c3c82bdc-d9e7-4836-9746-c24ead47ca19'
    ]
    assert not newdata.get('musicbrainzrecordingid')
