#!/usr/bin/env python3
"""test artistextras lastfm plugin"""

import os
import urllib.parse

import pytest
from aioresponses import aioresponses
from utils_artistextras import FakeImageCache, configuresettings, skip_no_lastfm_key

import nowplaying.apicache
import nowplaying.artistextras.lastfm

LASTFM_BASE_URL = "https://ws.audioscrobbler.com/2.0/"
TEST_APIKEY = "testapikey123"  # pragma: allowlist secret


def _artist_url(artist: str, lang: str = "en") -> str:
    return (
        f"{LASTFM_BASE_URL}?method=artist.getinfo"
        f"&artist={urllib.parse.quote(artist)}"
        f"&api_key={TEST_APIKEY}"
        f"&format=json&autocorrect=1"
        f"&lang={lang}"
    )


def _album_url(artist: str, album: str) -> str:
    return (
        f"{LASTFM_BASE_URL}?method=album.getinfo"
        f"&artist={urllib.parse.quote(artist)}"
        f"&album={urllib.parse.quote(album)}"
        f"&api_key={TEST_APIKEY}"
        f"&format=json&autocorrect=1"
    )


def _album_mbid_url(mbid: str) -> str:
    return (
        f"{LASTFM_BASE_URL}?method=album.getinfo"
        f"&mbid={urllib.parse.quote(mbid)}"
        f"&api_key={TEST_APIKEY}"
        f"&format=json&autocorrect=1"
    )


NIN_URL = _artist_url("Nine Inch Nails")
XYZ_URL = _artist_url("XYZ Nonexistent Artist XYZ")
NIN_ALBUM_URL = _album_url("Nine Inch Nails", "The Downward Spiral")
COVER_IMAGE_URL = "https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg"

NIN_ALBUM_RESPONSE = {
    "album": {
        "name": "The Downward Spiral",
        "artist": "Nine Inch Nails",
        "url": "https://www.last.fm/music/Nine+Inch+Nails/The+Downward+Spiral",
        "image": [
            {"#text": "https://lastfm.freetls.fastly.net/i/u/34s/cover.jpg", "size": "small"},
            {"#text": "https://lastfm.freetls.fastly.net/i/u/64s/cover.jpg", "size": "medium"},
            {"#text": "https://lastfm.freetls.fastly.net/i/u/174s/cover.jpg", "size": "large"},
            {"#text": COVER_IMAGE_URL, "size": "extralarge"},
            {"#text": COVER_IMAGE_URL, "size": "mega"},
        ],
    }
}

NIN_RESPONSE = {
    "artist": {
        "name": "Nine Inch Nails",
        "url": "https://www.last.fm/music/Nine+Inch+Nails",
        "bio": {
            "summary": "Nine Inch Nails is an American industrial rock band.",
            "content": (
                "Nine Inch Nails (abbreviated as NIN) is an American industrial rock band "
                "formed in Cleveland, Ohio in 1988. Trent Reznor is the primary member. "
                '<a href="https://www.last.fm/music/Nine+Inch+Nails">Read more on Last.fm</a>'
            ),
        },
        "tags": {
            "tag": [
                {"name": "industrial", "url": "https://www.last.fm/tag/industrial"},
                {"name": "rock", "url": "https://www.last.fm/tag/rock"},
                {"name": "electronic", "url": "https://www.last.fm/tag/electronic"},
            ]
        },
        "stats": {"listeners": "1234567", "playcount": "98765432"},
    }
}


def _setup_plugin(bootstrap, lang: str = "en", en_fallback: bool = True):
    config = bootstrap
    configuresettings("lastfm", config.cparser)
    config.cparser.setValue("lastfm/apikey", TEST_APIKEY)
    config.cparser.setValue("lastfm/bio_lang", lang)
    config.cparser.setValue("lastfm/bio_lang_en_fallback", en_fallback)
    plugin = nowplaying.artistextras.lastfm.Plugin(config=config)
    imagecache = FakeImageCache()
    return plugin, imagecache


@pytest.mark.asyncio
async def test_lastfm_disabled(bootstrap):
    """disabled plugin returns None"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/enabled", False)
    result = await plugin.download_async(
        {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
        imagecache=imagecache,
    )
    assert result is None


@pytest.mark.asyncio
async def test_lastfm_no_apikey(bootstrap):
    """missing API key returns None"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/apikey", "")
    result = await plugin.download_async(
        {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
        imagecache=imagecache,
    )
    assert result is None


@pytest.mark.asyncio
async def test_lastfm_no_artist(bootstrap):
    """missing artist returns None"""
    plugin, imagecache = _setup_plugin(bootstrap)
    result = await plugin.download_async({"title": "Hurt"}, imagecache=imagecache)
    assert result is None


@pytest.mark.asyncio
async def test_lastfm_bio_and_website(bootstrap):
    """successful fetch returns bio and website"""
    plugin, imagecache = _setup_plugin(bootstrap)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)

        result = await plugin.download_async(
            {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
            imagecache=imagecache,
        )

    assert result is not None
    assert result["artistlongbio"]
    assert "Read more on Last.fm" not in result["artistlongbio"]
    assert result["artistwebsites"] == ["https://www.last.fm/music/Nine+Inch+Nails"]


@pytest.mark.asyncio
async def test_lastfm_bio_stripped(bootstrap):
    """Last.fm attribution is stripped from bio"""
    plugin, _ = _setup_plugin(bootstrap)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        result = await plugin.download_async(
            {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
        )

    assert result is not None
    assert "Read more on Last.fm" not in result["artistlongbio"]
    assert "Nine Inch Nails" in result["artistlongbio"]


@pytest.mark.asyncio
async def test_lastfm_bio_disabled(bootstrap):
    """bio disabled returns only website"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/bio", False)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        result = await plugin.download_async(
            {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
            imagecache=imagecache,
        )

    assert result is not None
    assert "artistlongbio" not in result
    assert result["artistwebsites"]


@pytest.mark.asyncio
async def test_lastfm_websites_disabled(bootstrap):
    """websites disabled returns only bio"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/websites", False)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        result = await plugin.download_async(
            {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
            imagecache=imagecache,
        )

    assert result is not None
    assert result["artistlongbio"]
    assert "artistwebsites" not in result


@pytest.mark.asyncio
async def test_lastfm_existing_bio_not_overwritten(bootstrap):
    """does not overwrite existing artistlongbio"""
    plugin, imagecache = _setup_plugin(bootstrap)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        result = await plugin.download_async(
            {
                "artist": "Nine Inch Nails",
                "imagecacheartist": "nineinchnails",
                "artistlongbio": "already set",
            },
            imagecache=imagecache,
        )

    # Only websites should be returned; bio was already set
    assert result is not None
    assert "artistlongbio" not in result
    assert result["artistwebsites"]


@pytest.mark.asyncio
async def test_lastfm_api_error(bootstrap):
    """Last.fm API error response returns None"""
    plugin, imagecache = _setup_plugin(bootstrap)

    with aioresponses() as mockr:
        mockr.get(
            XYZ_URL,
            payload={"error": 6, "message": "Artist not found"},
        )
        result = await plugin.download_async(
            {"artist": "XYZ Nonexistent Artist XYZ", "imagecacheartist": "xyz"},
            imagecache=imagecache,
        )

    assert result is None


@pytest.mark.asyncio
async def test_lastfm_http_error(bootstrap, isolated_api_cache):  # pylint: disable=redefined-outer-name
    """HTTP error returns None without raising"""
    plugin, imagecache = _setup_plugin(bootstrap)

    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(isolated_api_cache)

    try:
        with aioresponses() as mockr:
            mockr.get(NIN_URL, status=503)
            result = await plugin.download_async(
                {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
                imagecache=imagecache,
            )

        assert result is None
    finally:
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_lastfm_both_disabled_returns_none(bootstrap):
    """both bio and websites disabled returns None"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/bio", False)
    bootstrap.cparser.setValue("lastfm/websites", False)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        result = await plugin.download_async(
            {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
            imagecache=imagecache,
        )

    assert result is None


def test_lastfm_providerinfo(bootstrap):
    """providerinfo returns expected fields"""
    plugin, _ = _setup_plugin(bootstrap)
    info = plugin.providerinfo()
    assert "artistlongbio" in info
    assert "artistwebsites" in info


@pytest.mark.asyncio
async def test_lastfm_lang_returned(bootstrap, isolated_api_cache):  # pylint: disable=redefined-outer-name
    """non-English lang is requested and bio uses that language"""
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(isolated_api_cache)

    try:
        plugin, imagecache = _setup_plugin(bootstrap, lang="de")
        de_url = _artist_url("Nine Inch Nails", lang="de")

        de_response = {
            "artist": {
                "name": "Nine Inch Nails",
                "url": "https://www.last.fm/music/Nine+Inch+Nails",
                "bio": {
                    "content": "Nine Inch Nails"
                    " ist eine US-amerikanische Industrialrock-Band."  # codespell:ignore
                },
            }
        }

        with aioresponses() as mockr:
            mockr.get(de_url, payload=de_response)
            result = await plugin.download_async(
                {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
                imagecache=imagecache,
            )

        assert result is not None
        assert "Industrialrock" in result["artistlongbio"]
    finally:
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_lastfm_lang_fallback_to_en(bootstrap, isolated_api_cache):  # pylint: disable=redefined-outer-name
    """empty bio in requested lang falls back to English when enabled"""
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(isolated_api_cache)

    try:
        plugin, imagecache = _setup_plugin(bootstrap, lang="ko", en_fallback=True)
        ko_url = _artist_url("Nine Inch Nails", lang="ko")
        en_url = _artist_url("Nine Inch Nails", lang="en")

        ko_response = {
            "artist": {
                "name": "Nine Inch Nails",
                "url": "https://www.last.fm/music/Nine+Inch+Nails",
                "bio": {"content": ""},  # no Korean bio
            }
        }

        with aioresponses() as mockr:
            mockr.get(ko_url, payload=ko_response)
            mockr.get(en_url, payload=NIN_RESPONSE)
            result = await plugin.download_async(
                {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
                imagecache=imagecache,
            )

        assert result is not None
        assert result["artistlongbio"]
        assert "Nine Inch Nails" in result["artistlongbio"]
    finally:
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_lastfm_lang_no_fallback(bootstrap, isolated_api_cache):  # pylint: disable=redefined-outer-name
    """empty bio in requested lang returns no bio when fallback is disabled"""
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(isolated_api_cache)

    try:
        plugin, imagecache = _setup_plugin(bootstrap, lang="ko", en_fallback=False)
        ko_url = _artist_url("Nine Inch Nails", lang="ko")

        ko_response = {
            "artist": {
                "name": "Nine Inch Nails",
                "url": "https://www.last.fm/music/Nine+Inch+Nails",
                "bio": {"content": ""},
            }
        }

        with aioresponses() as mockr:
            mockr.get(ko_url, payload=ko_response)
            result = await plugin.download_async(
                {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
                imagecache=imagecache,
            )

        # website should still be returned even with no bio
        assert result is not None
        assert "artistlongbio" not in result
        assert result["artistwebsites"]
    finally:
        nowplaying.apicache.set_cache_instance(original_cache)


def _setup_live_plugin(bootstrap, lang: str = "en", en_fallback: bool = True):
    """Set up plugin with real API key from environment"""
    config = bootstrap
    configuresettings("lastfm", config.cparser)
    config.cparser.setValue("lastfm/apikey", os.environ["LASTFM_API_KEY"])
    config.cparser.setValue("lastfm/bio_lang", lang)
    config.cparser.setValue("lastfm/bio_lang_en_fallback", en_fallback)
    plugin = nowplaying.artistextras.lastfm.Plugin(config=config)
    imagecache = FakeImageCache()
    return plugin, imagecache


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_bio_and_website(bootstrap):
    """live: successful fetch returns bio and website for Nine Inch Nails"""
    plugin, imagecache = _setup_live_plugin(bootstrap)

    result = await plugin.download_async(
        {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
        imagecache=imagecache,
    )

    assert result is not None
    assert result.get("artistlongbio")
    assert "Read more on Last.fm" not in result["artistlongbio"]
    assert result.get("artistwebsites")
    assert any("last.fm" in url for url in result["artistwebsites"])


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_cache_consistency(bootstrap, isolated_api_cache):  # pylint: disable=redefined-outer-name
    """live: two calls return identical data (cache hit on second)"""
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(isolated_api_cache)

    try:
        plugin, imagecache = _setup_live_plugin(bootstrap)
        metadata = {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"}

        result1 = await plugin.download_async(metadata.copy(), imagecache=imagecache)
        result2 = await plugin.download_async(metadata.copy(), imagecache=imagecache)

        assert result1 == result2
    finally:
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_unknown_artist(bootstrap):
    """live: unknown artist returns None gracefully"""
    plugin, imagecache = _setup_live_plugin(bootstrap)

    try:
        result = await plugin.download_async(
            {"artist": "XYZ Nonexistent Artist XYZ 99999", "imagecacheartist": "xyz"},
            imagecache=imagecache,
        )
        assert result is None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        pytest.fail(f"Plugin raised exception for unknown artist: {exc}")


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_lang_fallback(bootstrap, isolated_api_cache):  # pylint: disable=redefined-outer-name
    """live: Korean lang with EN fallback returns English bio for NIN (no Korean bio exists)"""
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(isolated_api_cache)

    try:
        plugin, imagecache = _setup_live_plugin(bootstrap, lang="ko", en_fallback=True)
        result = await plugin.download_async(
            {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
            imagecache=imagecache,
        )

        assert result is not None
        assert result.get("artistlongbio"), "Expected English fallback bio"
    finally:
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_lastfm_coverart_queued(bootstrap):
    """album cover art URL is queued in imagecache when album is present"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        mockr.get(NIN_ALBUM_URL, payload=NIN_ALBUM_RESPONSE)
        result = await plugin.download_async(
            {
                "artist": "Nine Inch Nails",
                "album": "The Downward Spiral",
                "imagecacheartist": "nineinchnails",
            },
            imagecache=imagecache,
        )

    assert result is not None
    identifier = "Nine Inch Nails_The Downward Spiral"
    assert identifier in imagecache.urls
    assert imagecache.urls[identifier]["front_cover"] == [COVER_IMAGE_URL]


@pytest.mark.asyncio
async def test_lastfm_coverart_disabled(bootstrap):
    """album cover art is not fetched when coverart setting is disabled"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", False)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        result = await plugin.download_async(
            {
                "artist": "Nine Inch Nails",
                "album": "The Downward Spiral",
                "imagecacheartist": "nineinchnails",
            },
            imagecache=imagecache,
        )

    assert result is not None
    assert "Nine Inch Nails_The Downward Spiral" not in imagecache.urls


@pytest.mark.asyncio
async def test_lastfm_coverart_skipped_when_coverimageraw_present(bootstrap):
    """album cover art fetch is skipped when coverimageraw already in metadata"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        result = await plugin.download_async(
            {
                "artist": "Nine Inch Nails",
                "album": "The Downward Spiral",
                "imagecacheartist": "nineinchnails",
                "coverimageraw": b"\xff\xd8\xff",
            },
            imagecache=imagecache,
        )

    assert result is not None
    # No album.getinfo call was made; imagecache should not have front_cover queued
    assert "Nine Inch Nails_The Downward Spiral" not in imagecache.urls


@pytest.mark.asyncio
async def test_lastfm_coverart_no_album(bootstrap):
    """album cover art fetch is skipped when no album in metadata"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        result = await plugin.download_async(
            {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
            imagecache=imagecache,
        )

    assert result is not None
    assert not imagecache.urls


@pytest.mark.asyncio
async def test_lastfm_coverart_album_api_error(bootstrap, isolated_api_cache):  # pylint: disable=redefined-outer-name
    """album API error does not prevent artist data from being returned"""
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(isolated_api_cache)

    try:
        plugin, imagecache = _setup_plugin(bootstrap)
        bootstrap.cparser.setValue("lastfm/coverart", True)

        with aioresponses() as mockr:
            mockr.get(NIN_URL, payload=NIN_RESPONSE)
            mockr.get(NIN_ALBUM_URL, payload={"error": 6, "message": "Album not found"})
            result = await plugin.download_async(
                {
                    "artist": "Nine Inch Nails",
                    "album": "The Downward Spiral",
                    "imagecacheartist": "nineinchnails",
                },
                imagecache=imagecache,
            )

        assert result is not None
        assert result.get("artistlongbio") or result.get("artistwebsites")
        assert "Nine Inch Nails_The Downward Spiral" not in imagecache.urls
    finally:
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_lastfm_coverart_with_album_mbid(bootstrap):
    """album cover art uses MBID-based URL when musicbrainzalbumid is present"""
    plugin, imagecache = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)
    album_mbid = "12345678-1234-1234-1234-123456789abc"
    mbid_url = _album_mbid_url(album_mbid)

    with aioresponses() as mockr:
        mockr.get(NIN_URL, payload=NIN_RESPONSE)
        mockr.get(mbid_url, payload=NIN_ALBUM_RESPONSE)
        result = await plugin.download_async(
            {
                "artist": "Nine Inch Nails",
                "album": "The Downward Spiral",
                "imagecacheartist": "nineinchnails",
                "musicbrainzalbumid": album_mbid,
            },
            imagecache=imagecache,
        )

    assert result is not None
    identifier = "Nine Inch Nails_The Downward Spiral"
    assert identifier in imagecache.urls
    assert imagecache.urls[identifier]["front_cover"] == [COVER_IMAGE_URL]


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_coverart(bootstrap, isolated_api_cache):  # pylint: disable=redefined-outer-name
    """live: album cover art URL is queued for Nine Inch Nails - The Downward Spiral"""
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(isolated_api_cache)

    try:
        plugin, imagecache = _setup_live_plugin(bootstrap)
        bootstrap.cparser.setValue("lastfm/coverart", True)
        result = await plugin.download_async(
            {
                "artist": "Nine Inch Nails",
                "album": "The Downward Spiral",
                "imagecacheartist": "nineinchnails",
            },
            imagecache=imagecache,
        )

        identifier = "Nine Inch Nails_The Downward Spiral"
        assert result is not None
        assert identifier in imagecache.urls, "Expected cover art to be queued"
        assert imagecache.urls[identifier].get("front_cover"), "Expected front_cover URL list"
    finally:
        nowplaying.apicache.set_cache_instance(original_cache)
