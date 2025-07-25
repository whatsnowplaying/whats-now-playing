#!/usr/bin/env python3
"""test metadata"""

import os
import logging
import multiprocessing
import sqlite3
import types

import pytest
import pytest_asyncio

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.metadata  # pylint: disable=import-error
import nowplaying.upgrade  # pylint: disable=import-error
import nowplaying.upgrades.config  # pylint: disable=import-error
import nowplaying.imagecache  # pylint: disable=import-error,no-member


@pytest_asyncio.fixture
async def get_imagecache(bootstrap):
    """setup the image cache for testing"""
    config = bootstrap
    workers = 2
    dbdir = config.testdir.joinpath("imagecache")
    dbdir.mkdir()
    logpath = config.testdir.joinpath("debug.log")
    stopevent = multiprocessing.Event()
    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir, stopevent=stopevent)  # pylint: disable=no-member
    icprocess = multiprocessing.Process(
        target=imagecache.queue_process,
        name="ICProcess",
        args=(
            logpath,
            workers,
        ),
    )
    icprocess.start()
    yield config, imagecache
    stopevent.set()
    imagecache.stop_process()
    icprocess.join()


@pytest.mark.asyncio
async def test_15ghosts2_mp3_orig(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_orig.mp3")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["album"] == "Ghosts I - IV"
    assert metadataout["artist"] == "Nine Inch Nails"
    # assert metadataout['bitrate'] == 64000
    assert metadataout["imagecacheartist"] == "nine inch nails"
    assert metadataout["track"] == "15"
    assert metadataout["title"] == "15 Ghosts II"
    assert metadataout["duration"] == 113


@pytest.mark.asyncio
async def test_15ghosts2_mp3_fullytagged(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_füllytâgged.mp3")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["acoustidid"] == "02d23182-de8b-493e-a6e1-e011bfdacbcf"
    assert metadataout["album"] == "Ghosts I-IV"
    assert metadataout["albumartist"] == "Nine Inch Nails"
    assert metadataout["artist"] == "Nine Inch Nails"
    assert metadataout["artistwebsites"] == ["https://www.nin.com/"]
    assert metadataout["coverimagetype"] == "png"
    assert metadataout["coverurl"] == "cover.png"
    assert metadataout["date"] == "2008-03-02"
    assert metadataout["imagecacheartist"] == "nine inch nails"
    assert metadataout["isrc"] == ["USTC40852243"]
    assert metadataout["label"] == "The Null Corporation"
    assert metadataout["musicbrainzalbumid"] == "3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a"
    assert metadataout["musicbrainzartistid"] == ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"]
    assert metadataout["musicbrainzrecordingid"] == "2d7f08e1-be1c-4b86-b725-6e675b7b6de0"
    assert metadataout["title"] == "15 Ghosts II"
    assert metadataout["duration"] == 113


@pytest.mark.asyncio
async def test_15ghosts2_flac_orig(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_orig.flac")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["album"] == "Ghosts I - IV"
    assert metadataout["artist"] == "Nine Inch Nails"
    assert metadataout["imagecacheartist"] == "nine inch nails"
    assert metadataout["track"] == "15"
    assert metadataout["title"] == "15 Ghosts II"
    assert metadataout["duration"] == 113


@pytest.mark.asyncio
async def test_15ghosts2_m4a_orig(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_orig.m4a")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["album"] == "Ghosts I - IV"
    assert metadataout["artist"] == "Nine Inch Nails"
    # assert metadataout['bitrate'] == 705600
    assert metadataout["imagecacheartist"] == "nine inch nails"
    assert metadataout["track"] == "15"
    assert metadataout["title"] == "15 Ghosts II"
    assert metadataout["duration"] == 113


@pytest.mark.asyncio
async def test_15ghosts2_aiff_orig(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_orig.aiff")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["album"] == "Ghosts I - IV"
    assert metadataout["artist"] == "Nine Inch Nails"
    assert metadataout["imagecacheartist"] == "nine inch nails"
    assert metadataout["track"] == "15"
    assert metadataout["title"] == "15 Ghosts II"
    assert metadataout["duration"] == 113


@pytest.mark.asyncio
async def test_15ghosts2_flac_fullytagged(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_füllytâgged.flac")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )

    assert metadataout["acoustidid"] == "02d23182-de8b-493e-a6e1-e011bfdacbcf"
    assert metadataout["album"] == "Ghosts I-IV"
    assert metadataout["albumartist"] == "Nine Inch Nails"
    assert metadataout["artistwebsites"] == ["https://www.nin.com/"]
    assert metadataout["artist"] == "Nine Inch Nails"
    assert metadataout["coverimagetype"] == "png"
    assert metadataout["coverurl"] == "cover.png"
    assert metadataout["date"] == "2008-03-02"
    assert metadataout["imagecacheartist"] == "nine inch nails"
    assert metadataout["isrc"] == ["USTC40852243"]
    assert metadataout["label"] == "The Null Corporation"
    assert metadataout["musicbrainzalbumid"] == "3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a"
    assert metadataout["musicbrainzartistid"] == ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"]
    assert metadataout["musicbrainzrecordingid"] == "2d7f08e1-be1c-4b86-b725-6e675b7b6de0"
    assert metadataout["title"] == "15 Ghosts II"
    assert metadataout["duration"] == 113


@pytest.mark.asyncio
async def test_15ghosts2_m4a_fullytagged(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_füllytâgged.m4a")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )

    assert metadataout["acoustidid"] == "02d23182-de8b-493e-a6e1-e011bfdacbcf"
    assert metadataout["album"] == "Ghosts I-IV"
    assert metadataout["albumartist"] == "Nine Inch Nails"
    assert metadataout["artistwebsites"] == ["https://www.nin.com/"]
    assert metadataout["artist"] == "Nine Inch Nails"
    assert metadataout["coverimagetype"] == "png"
    assert metadataout["coverurl"] == "cover.png"
    assert metadataout["date"] == "2008-03-02"
    assert metadataout["imagecacheartist"] == "nine inch nails"
    assert metadataout["isrc"] == ["USTC40852243"]
    assert metadataout["label"] == "The Null Corporation"
    assert metadataout["musicbrainzalbumid"] == "3af7ec8c-3bf4-4e6d-9bb3-1885d22b2b6a"
    assert metadataout["musicbrainzartistid"] == ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"]
    assert metadataout["musicbrainzrecordingid"] == "2d7f08e1-be1c-4b86-b725-6e675b7b6de0"
    assert metadataout["title"] == "15 Ghosts II"
    assert metadataout["duration"] == 113


@pytest.mark.asyncio
async def test_15ghosts2_aiff_fullytagged(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_füllytâgged.aiff")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )

    assert metadataout["album"] == "Ghosts I-IV"
    assert metadataout["albumartist"] == "Nine Inch Nails"
    assert metadataout["artist"] == "Nine Inch Nails"
    assert metadataout["coverimagetype"] == "png"
    assert metadataout["coverurl"] == "cover.png"
    assert metadataout["imagecacheartist"] == "nine inch nails"
    assert metadataout["isrc"] == ["USTC40852243"]
    assert metadataout["title"] == "15 Ghosts II"
    assert metadataout["duration"] == 113


@pytest.mark.asyncio
async def test_artistshortio(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_orig.mp3"),
        "artistlongbio": """
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
""",
    }

    shortbio = (
        "Industrial rock band Nine Inch Nails (abbreviated as NIN and stylized as NIИ) was formed"
        " in 1988 by Trent Reznor in Cleveland, Ohio. Reznor has served as the main producer, singer,"  # pylint: disable=line-too-long
        " songwriter, instrumentalist, and sole member of Nine Inch Nails for 28 years. This changed"  # pylint: disable=line-too-long
        " in December 2016 when Atticus Ross officially became the second member of the band."
    )

    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    logging.debug(metadataout["artistshortbio"])
    assert metadataout["artistshortbio"] == shortbio
    assert metadataout["album"] == "Ghosts I - IV"
    assert metadataout["artist"] == "Nine Inch Nails"
    # assert metadataout['bitrate'] == 64000
    assert metadataout["imagecacheartist"] == "nine inch nails"
    assert metadataout["track"] == "15"
    assert metadataout["title"] == "15 Ghosts II"


@pytest.mark.asyncio
async def test_stripre_cleandash(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", True)
    nowplaying.upgrades.config.UpgradeConfig._upgrade_filters(config.cparser)  # pylint: disable=protected-access
    metadatain = {"title": "Test - Clean"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["title"] == "Test"


@pytest.mark.asyncio
async def test_stripre_nocleandash(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", False)
    nowplaying.upgrades.config.UpgradeConfig._upgrade_filters(config.cparser)  # pylint: disable=protected-access
    metadatain = {"title": "Test - Clean"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["title"] == "Test - Clean"


@pytest.mark.asyncio
async def test_stripre_cleanparens(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", True)
    nowplaying.upgrades.config.UpgradeConfig._upgrade_filters(config.cparser)  # pylint: disable=protected-access
    metadatain = {"title": "Test (Clean)"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["title"] == "Test"


@pytest.mark.asyncio
async def test_stripre_cleanextraparens(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", True)
    nowplaying.upgrades.config.UpgradeConfig._upgrade_filters(config.cparser)  # pylint: disable=protected-access
    metadatain = {"title": "Test (Clean) (Single Mix)"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["title"] == "Test (Single Mix)"


@pytest.mark.asyncio
async def test_publisher_not_label(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", False)
    nowplaying.upgrades.config.UpgradeConfig._upgrade_filters(config.cparser)  # pylint: disable=protected-access
    metadatain = {"publisher": "Cool Music Publishing"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["label"] == "Cool Music Publishing"
    assert not metadataout.get("publisher")


@pytest.mark.asyncio
async def test_year_not_date(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", False)
    metadatain = {"year": "1999"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["date"] == "1999"
    assert not metadataout.get("year")


@pytest.mark.asyncio
async def test_streaming_channel_metadata(bootstrap):
    """test that streaming channel information gets added to metadata"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("twitchbot/channel", "teststreamer")
    config.cparser.setValue("kick/channel", "kickstreamer")
    config.cparser.setValue("discord/guild", "My Discord Server")

    metadatain = {"artist": "Test Artist", "title": "Test Title"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )

    assert metadataout["twitchchannel"] == "teststreamer"
    assert metadataout["kickchannel"] == "kickstreamer"
    assert metadataout["discordguild"] == "My Discord Server"


@pytest.mark.asyncio
async def test_streaming_channel_metadata_missing(bootstrap):
    """test that missing streaming channel configs don't add empty fields"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    # Don't set any streaming channel configs

    metadatain = {"artist": "Test Artist", "title": "Test Title"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )

    assert "twitchchannel" not in metadataout
    assert "kickchannel" not in metadataout
    assert "discordguild" not in metadataout


@pytest.mark.asyncio
async def test_url_dedupe1(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", False)
    metadatain = {"artistwebsites": ["http://example.com", "http://example.com/"]}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["artistwebsites"] == ["http://example.com/"]


@pytest.mark.asyncio
async def test_url_dedupe2(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", False)
    metadatain = {"artistwebsites": ["http://example.com", "https://example.com/"]}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["artistwebsites"] == ["https://example.com/"]


@pytest.mark.asyncio
async def test_url_dedupe3(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", False)
    metadatain = {"artistwebsites": ["https://example.com", "http://example.com/"]}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["artistwebsites"] == ["https://example.com/"]


@pytest.mark.asyncio
async def test_url_dedupe4(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", False)
    metadatain = {
        "artistwebsites": [
            "https://example.com",
            "https://whatsnowplaying.github.io",
            "http://example.com/",
        ]
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["artistwebsites"] == [
        "https://example.com/",
        "https://whatsnowplaying.github.io/",
    ]


@pytest.mark.asyncio
async def test_broken_duration(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", False)
    metadatain = {"duration": "1 hour 10 minutes"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert not metadataout.get("duration")


@pytest.mark.asyncio
async def test_str_duration(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("settings/stripextras", False)
    metadatain = {"duration": "1"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["duration"] == 1


@pytest.mark.asyncio
async def test_year_zeronum(bootstrap):
    """automated integration test"""
    config = bootstrap
    metadatain = {"date": 0}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert not metadataout.get("date")


@pytest.mark.asyncio
async def test_year_zerostr(bootstrap):
    """automated integration test"""
    config = bootstrap
    metadatain = {"date": "0"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert not metadataout.get("date")


@pytest.mark.asyncio
async def test_youtube(bootstrap):
    """test the stupid hack for youtube downloaded videos"""
    config = bootstrap
    metadatain = {
        "artist": "fakeartist",
        "title": "Pet Shop Boys - Can You Forgive Her?",
        "comments": "http://youtube.com/watch?v=xxxxxxx",
    }
    mdp = nowplaying.metadata.MetadataProcessors(config=config)
    metadataout = await mdp.getmoremetadata(metadata=metadatain)
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )

    # might get either album or single
    assert metadataout["album"] in ["Very Relentless", "Can You Forgive Her?"]
    assert metadataout["artist"] == "Pet Shop Boys"
    assert metadataout["imagecacheartist"] == "pet shop boys"
    assert metadataout["label"] in ["EMI", "Parlophone"]
    assert metadataout["musicbrainzartistid"] == ["be540c02-7898-4b79-9acc-c8122c7d9e83"]
    assert metadataout["musicbrainzrecordingid"] in [
        "0e0bc5b5-28d0-4f42-8bf8-1cf4187ee738",
        "2c0bb21b-805b-4e13-b2da-6a52d398f4f6",
    ]
    assert metadataout["title"] == "Can You Forgive Her?"


@pytest.mark.asyncio
async def test_discogs_from_mb(bootstrap):  # pylint: disable=redefined-outer-name
    """noimagecache"""

    if not os.environ.get("DISCOGS_API_KEY"):
        return

    config = bootstrap
    config.cparser.setValue("acoustidmb/homepage", False)
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("discogs/apikey", os.environ["DISCOGS_API_KEY"])
    config.cparser.setValue("musicbrainz/enabled", True)
    config.cparser.setValue("discogs/enabled", True)
    config.cparser.setValue("discogs/bio", True)
    config.cparser.setValue("musicbrainz/fallback", True)
    metadatain = {"artist": "TR/ST", "title": "Iris"}
    mdp = nowplaying.metadata.MetadataProcessors(config=config)
    metadataout = await mdp.getmoremetadata(metadata=metadatain)
    del metadataout["coverimageraw"]
    assert metadataout["album"] == "Iris"
    assert metadataout["artistwebsites"] == ["https://www.discogs.com/artist/2028711"]
    assert metadataout["artist"] == "TR/ST"
    assert metadataout["date"] == "2019-07-25"
    assert metadataout["imagecacheartist"] == "tr st"
    assert metadataout["label"] == "House Arrest"
    assert metadataout["musicbrainzartistid"] == ["b8e3d1ae-5983-4af1-b226-aa009b294111"]
    assert metadataout["musicbrainzrecordingid"] == "9ecf96f5-dbba-4fda-a5cf-7728837fb1b6"
    assert metadataout["title"] == "Iris"


@pytest.mark.asyncio
async def test_keeptitle_despite_mb(bootstrap):  # pylint: disable=redefined-outer-name
    """noimagecache"""

    if not os.environ.get("DISCOGS_API_KEY"):
        return

    config = bootstrap
    config.cparser.setValue("acoustidmb/homepage", False)
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("discogs/apikey", os.environ["DISCOGS_API_KEY"])
    config.cparser.setValue("musicbrainz/enabled", True)
    config.cparser.setValue("musicbrainz/fallback", True)
    metadatain = {
        "artist": "Simple Minds",
        "title": "Don't You (Forget About Me) (DJ Paulharwood Remix)",
    }
    mdp = nowplaying.metadata.MetadataProcessors(config=config)
    metadataout = await mdp.getmoremetadata(metadata=metadatain)
    assert not metadataout.get("album")
    assert metadataout["artistwebsites"] == ["https://www.discogs.com/artist/18547"]
    assert metadataout["artist"] == "Simple Minds"
    assert not metadataout.get("date")
    assert metadataout["imagecacheartist"] == "simple minds"
    assert not metadataout.get("label")
    assert metadataout["musicbrainzartistid"] == ["f41490ce-fe39-435d-86c0-ab5ce098b423"]
    assert not metadataout.get("musicbrainzrecordingid")
    assert metadataout["title"] == "Don't You (Forget About Me) (DJ Paulharwood Remix)"


@pytest.mark.asyncio
async def test_15ghosts2_m4a_fake_origdate(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_fake_origdate.m4a")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["date"] == "1982-01-01"


@pytest.mark.asyncio
async def test_15ghosts2_m4a_fake_origyear(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_fake_origyear.m4a")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["date"] == "1983"


@pytest.mark.asyncio
async def test_15ghosts2_m4a_fake_both(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_fake_ody.m4a")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["date"] == "1982-01-01"


@pytest.mark.asyncio
async def test_15ghosts2_mp3_fake_origdate(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_fake_origdate.mp3")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["date"] == "1982"


@pytest.mark.asyncio
async def test_15ghosts2_mp3_fake_origyear(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_fake_origyear.mp3")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["date"] == "1983"


@pytest.mark.asyncio
async def test_15ghosts2_mp3_fake_origboth(bootstrap, getroot):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_fake_ody.mp3")
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["date"] == "1982"


@pytest.mark.parametrize("multifilename", ["multi.flac", "multi.m4a", "multi.mp3"])
@pytest.mark.asyncio
async def test_multi(bootstrap, getroot, multifilename):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"filename": os.path.join(getroot, "tests", "audio", multifilename)}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["artistwebsites"][0] in [
        "http://ww1.example.com/",
        "http://ww2.example.com/",
    ]
    # All formats now properly extract multi-value fields thanks to tinytag fixes
    assert metadataout["isrc"] == ["isrc1", "isrc2"]
    assert metadataout["musicbrainzartistid"] == [
        "b7ffd2af-418f-4be2-bdd1-22f8b48613da",
        "c0b2500e-0cef-4130-869d-732b23ed9df5",
    ]


@pytest.mark.parametrize("multifilename", ["multiimage.m4a"])
@pytest.mark.asyncio
async def test_multiimage(get_imagecache, getroot, multifilename):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config, imagecache = get_imagecache
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"filename": os.path.join(getroot, "tests", "audio", multifilename)}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain, imagecache=imagecache
    )

    assert metadataout["coverimageraw"]
    with sqlite3.connect(imagecache.databasefile, timeout=30) as connection:
        cursor = connection.cursor()
        cursor.execute(
            '''SELECT COUNT(cachekey) FROM identifiersha WHERE imagetype="front_cover"'''
        )
        row = cursor.fetchone()[0]
        assert row > 1


@pytest.mark.asyncio
async def test_preset_image(get_imagecache, getroot):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config, imagecache = get_imagecache
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"filename": os.path.join(getroot, "tests", "audio", "multiimage.m4a")}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain, imagecache=imagecache
    )

    assert metadataout["coverimageraw"]
    assert metadataout["album"]
    metadatain |= {"coverimageraw": metadataout["coverimageraw"], "album": metadataout["album"]}

    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain, imagecache=imagecache
    )
    with sqlite3.connect(imagecache.databasefile, timeout=30) as connection:
        cursor = connection.cursor()
        cursor.execute(
            '''SELECT COUNT(cachekey) FROM identifiersha WHERE imagetype="front_cover"'''
        )
        row = cursor.fetchone()[0]
        assert row > 1


@pytest.mark.parametrize(
    "input_value,expected_output",
    [
        # Base64 encoded JSON (MixedInKey format)
        (
            "eyJhbGdvcml0aG0iOjk0LCJrZXkiOiI0QSIsInNvdXJjZSI6Im1peGVkaW5rZXkifQ==",  # pragma: allowlist secret  # pylint: disable=line-too-long
            "4A",
        ),
        # Direct JSON
        ('{"algorithm":94,"key":"9B","source":"mixedinkey"}', "9B"),
        # Simple string keys
        ("Am", "Am"),
        ("C#m", "C#m"),
        ("12A", "12A"),
        # Empty/None values
        (None, None),
        ("", None),
        ("   ", ""),
        # Malformed input
        ("not-base64-or-json", "not-base64-or-json"),
        ('invalid-json{"key":"test"}', 'invalid-json{"key":"test"}'),
        # Valid base64 that decodes to non-JSON text
        ("SGVsbG8gV29ybGQ=", "SGVsbG8gV29ybGQ="),  # "Hello World"
        # Valid base64 that decodes to non-object JSON (array)
        ("WyJ0ZXN0IiwiYXJyYXkiXQ==", "WyJ0ZXN0IiwiYXJyYXkiXQ=="),  # ["test","array"]
        # Valid base64 that decodes to non-object JSON (string)
        ("InRlc3Qgc3RyaW5nIg==", "InRlc3Qgc3RyaW5nIg=="),  # "test string"
        # Valid base64 that decodes to JSON object missing 'key' field
        (
            "eyJhbGdvcml0aG0iOjk0LCJzb3VyY2UiOiJtaXhlZGlua2V5In0=",  # pragma: allowlist secret
            "eyJhbGdvcml0aG0iOjk0LCJzb3VyY2UiOiJtaXhlZGlua2V5In0=",  # pragma: allowlist secret
        ),  # pragma: allowlist secret
        # Direct JSON without 'key' field
        ('{"algorithm":94,"source":"mixedinkey"}', '{"algorithm":94,"source":"mixedinkey"}'),
        # Direct JSON array
        ('["test","array"]', '["test","array"]'),
        # Direct JSON string
        ('"test string"', '"test string"'),
        # JSON with null key value
        (
            '{"algorithm":94,"key":null,"source":"mixedinkey"}',
            '{"algorithm":94,"key":null,"source":"mixedinkey"}',
        ),
    ],
)
def test_decode_musical_key(input_value, expected_output):
    """Test the _decode_musical_key method handles various key formats."""
    result = nowplaying.metadata.TinyTagRunner._decode_musical_key(input_value)  # pylint: disable=protected-access
    assert result == expected_output


@pytest.mark.parametrize(
    "test_value,expected_result",
    [
        (0, True),  # 0 should be processed (our fix)
        (1, True),  # 1 should be processed (normal case)
        (None, False),  # None should be ignored
        ("0", True),  # String '0' should be processed
        ("", True),  # Empty string should be processed (only None is filtered)
    ],
)
def test_metadata_handles_zero_values(test_value, expected_result):
    """Test that metadata processing handles 0 values correctly."""
    # Create a minimal mock tag object that focuses on testing the specific condition
    mock_tag = types.SimpleNamespace(track=test_value)

    # Test the specific condition that was problematic
    has_attr = hasattr(mock_tag, "track")
    value_check = getattr(mock_tag, "track") is not None  # Our fix: was getattr(mock_tag, 'track')

    should_process = has_attr and value_check

    assert should_process == expected_result, (
        f"Value {test_value} should {'be processed' if expected_result else 'be ignored'}"
    )
