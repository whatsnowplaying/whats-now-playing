#!/usr/bin/env python3
"""test artistextras core functionality"""

import logging
import os

import pytest
from utils_artistextras import (
    configureplugins,
    configuresettings,
    datacache_has_pending,
    datacache_image_available,
)

import nowplaying.datacache

PLUGINS = ["wikimedia"]

if os.environ.get("DISCOGS_API_KEY"):
    PLUGINS.append("discogs")
if os.environ.get("FANARTTV_API_KEY"):
    PLUGINS.append("fanarttv")
if os.environ.get("THEAUDIODB_API_KEY"):
    PLUGINS.append("theaudiodb")


@pytest.fixture
def getconfiguredplugin(bootstrap):
    """automated integration test"""
    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    if "discogs" in PLUGINS:
        configuresettings("discogs", config.cparser)
        config.cparser.setValue("discogs/apikey", os.environ["DISCOGS_API_KEY"])
    if "fanarttv" in PLUGINS:
        configuresettings("fanarttv", config.cparser)
        config.cparser.setValue("fanarttv/apikey", os.environ["FANARTTV_API_KEY"])
    if "theaudiodb" in PLUGINS:
        configuresettings("theaudiodb", config.cparser)
        config.cparser.setValue("theaudiodb/apikey", os.environ["THEAUDIODB_API_KEY"])
    if "theaudiodb" in PLUGINS:
        configuresettings("theaudiodb", config.cparser)
    yield configureplugins(config)


@pytest.mark.asyncio
async def test_disabled(bootstrap):
    """test disabled"""
    plugins = configureplugins(bootstrap)
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)
        data = await plugins[pluginname].download_async()
        assert not data


def test_providerinfo(bootstrap):  # pylint: disable=redefined-outer-name
    """test providerinfo"""
    plugins = configureplugins(bootstrap)
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)
        data = plugins[pluginname].providerinfo()
        assert data


@pytest.mark.asyncio
async def test_noapikey(bootstrap):  # pylint: disable=redefined-outer-name
    """test disabled"""
    config = bootstrap
    plugins = configureplugins(config)
    for pluginname in PLUGINS:
        config.cparser.setValue(f"{pluginname}/enabled", True)
        logging.debug("Testing %s", pluginname)
        data = await plugins[pluginname].download_async()
        assert not data


@pytest.mark.asyncio
async def test_nodata(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """test disabled"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)
        data = await plugins[pluginname].download_async()
        assert not data


@pytest.mark.asyncio
async def test_noimagecache(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """noimagecache"""

    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)
        data = await plugins[pluginname].download_async(
            {
                "album": "The Downward Spiral",
                "artist": "Nine Inch Nails",
                "imagecacheartist": "nineinchnails",
            },
        )
        if pluginname in ["discogs", "theaudiodb"]:
            assert data["artistwebsites"]
            assert data["artistlongbio"]
        else:
            assert not data


@pytest.mark.asyncio
async def test_missingallartistdata(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """missing all artist data"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)

        data = await plugins[pluginname].download_async({"title": "title"})
        assert not data


@pytest.mark.asyncio
async def test_missingmbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """artist"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)

        data = await plugins[pluginname].download_async(
            {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
        )
        if pluginname == "theaudiodb":
            assert data["artistlongbio"]
            assert data["artistwebsites"]
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistfanart"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistbanner"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistlogo"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistthumbnail"
            )
        else:
            assert not data


@pytest.mark.asyncio
async def test_featuring1(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """artist"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)

        data = await plugins[pluginname].download_async(
            {
                "artist": "Grimes feat Janelle Monáe",
                "title": "Venus Fly",
                "album": "Art Angels",
                "imagecacheartist": "grimesfeatjanellemonae",
            },
        )
        if pluginname == "discogs":
            assert data["artistlongbio"]
            assert data["artistwebsites"]
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "grimesfeatjanellemonae", "artistfanart"
            )
        elif pluginname == "theaudiodb":
            assert data["artistlongbio"]
            assert data["artistwebsites"]
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "grimesfeatjanellemonae", "artistfanart"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "grimesfeatjanellemonae", "artistbanner"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "grimesfeatjanellemonae", "artistlogo"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "grimesfeatjanellemonae", "artistthumbnail"
            )


@pytest.mark.asyncio
async def test_featuring2(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """artist"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)

        data = await plugins[pluginname].download_async(
            {
                "artist": "MӨЯIS BLΛK feat. grabyourface",
                "title": "Complicate",
                "album": "Irregular Revisions",
                "imagecacheartist": "morisblakfeatgrabyourface",
            },
        )
        if pluginname == "discogs":
            assert data["artistlongbio"]
            assert data["artistwebsites"]
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "morisblakfeatgrabyourface", "artistfanart"
            )


@pytest.mark.asyncio
async def test_badmbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """badmbid"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)

        data = await plugins[pluginname].download_async(
            {
                "artist": "NonExistentArtistXYZ",
                "imagecacheartist": "nonexistentartistxyz",
                "musicbrainzartistid": ["xyz"],
            },
        )
        assert not data


@pytest.mark.asyncio
async def test_onlymbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """badmbid"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)

        data = await plugins[pluginname].download_async(
            {
                "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],
            },
        )
        assert not data


@pytest.mark.asyncio
async def test_artist_and_mbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """badmbid"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)

        data = await plugins[pluginname].download_async(
            {
                "artist": "Nine Inch Nails",
                "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],
                "imagecacheartist": "nineinchnails",
            },
        )
        if pluginname == "theaudiodb":
            assert data["artistlongbio"]
            assert data["artistwebsites"]
        if pluginname in ["fanarttv", "theaudiodb"]:
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistfanart"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistbanner"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistlogo"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistthumbnail"
            )
        else:
            assert not data


@pytest.mark.asyncio
async def test_all(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """badmbid"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)
        metadata = {
            "artist": "Nine Inch Nails",
            "album": "The Downward Spiral",
            "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],
            "imagecacheartist": "nineinchnails",
        }
        if pluginname == "wikimedia":
            metadata["artistwebsites"] = ["https://www.wikidata.org/wiki/Q11647"]
        data = await plugins[pluginname].download_async(metadata)
        if pluginname in ["discogs", "theaudiodb"]:
            assert data["artistlongbio"]
            assert data["artistwebsites"]
        if pluginname in ["fanarttv", "theaudiodb", "discogs", "wikimedia"]:
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistfanart"
            )
        if pluginname in ["fanarttv", "theaudiodb"]:
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistbanner"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistlogo"
            )


@pytest.mark.xfail(reason="Non-deterministic at the moment")
@pytest.mark.asyncio
async def test_theall(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """badmbid"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)

        metadata = {
            "artist": "The Nine Inch Nails",
            "album": "The Downward Spiral",
            "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],
            "imagecacheartist": "nineinchnails",
        }
        if pluginname == "wikimedia":
            metadata["artistwebsites"] = ["https://www.wikidata.org/wiki/Q11647"]
        data = await plugins[pluginname].download_async(metadata)
        if pluginname in ["discogs", "theaudiodb"]:
            assert data["artistlongbio"]
            assert data["artistwebsites"]
        if pluginname in ["fanarttv", "theaudiodb"]:
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistfanart"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistbanner"
            )
            assert await datacache_image_available(
                nowplaying.datacache.get_client(), "nineinchnails", "artistlogo"
            )
        assert await datacache_has_pending(
            nowplaying.datacache.get_client(), "nineinchnails", "artistthumbnail"
        )


@pytest.mark.asyncio
async def test_notfound(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    """discogs"""
    plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug("Testing %s", pluginname)

        data = await plugins[pluginname].download_async(
            {
                "album": "ZYX fake album XYZ",
                "artist": "The XYZ fake artist XYZ",
                "musicbrainzartistid": ["xyz"],
            },
        )
        assert not data
