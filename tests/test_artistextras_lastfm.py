#!/usr/bin/env python3
"""test artistextras lastfm plugin"""

import os
import urllib.parse

import httpx
import pytest
import respx
from utils_artistextras import (
    configuresettings,
    datacache_has_pending,
    skip_no_lastfm_key,
)

import nowplaying.artistextras.lastfm
import nowplaying.datacache

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


WNP_MOCK_URL = _artist_url("WNP Mock Artist")
XYZ_URL = _artist_url("XYZ Nonexistent Artist XYZ")
WNP_MOCK_ALBUM_URL = _album_url("WNP Mock Artist", "WNP Mock Album")
COVER_IMAGE_URL = "https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg"

WNP_MOCK_ALBUM_RESPONSE = {
    "album": {
        "name": "WNP Mock Album",
        "artist": "WNP Mock Artist",
        "url": "https://www.last.fm/music/WNP+Mock+Artist/WNP+Mock+Album",
        "image": [
            {"#text": "https://lastfm.freetls.fastly.net/i/u/34s/cover.jpg", "size": "small"},
            {"#text": "https://lastfm.freetls.fastly.net/i/u/64s/cover.jpg", "size": "medium"},
            {"#text": "https://lastfm.freetls.fastly.net/i/u/174s/cover.jpg", "size": "large"},
            {"#text": COVER_IMAGE_URL, "size": "extralarge"},
            {"#text": COVER_IMAGE_URL, "size": "mega"},
        ],
    }
}

WNP_MOCK_RESPONSE = {
    "artist": {
        "name": "WNP Mock Artist",
        "url": "https://www.last.fm/music/WNP+Mock+Artist",
        "bio": {
            "summary": "WNP Mock Artist is a fictional band used for testing.",
            "content": (
                "WNP Mock Artist is a fictional band created for unit testing purposes. "
                "It has no real discography or members. "
                '<a href="https://www.last.fm/music/WNP+Mock+Artist">Read more on Last.fm</a>'
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
    return nowplaying.artistextras.lastfm.Plugin(config=config)


@pytest.mark.asyncio
async def test_lastfm_disabled(bootstrap):
    """disabled plugin returns None"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/enabled", False)
    result = await plugin.download_async(
        {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
    )
    assert result is None


@pytest.mark.asyncio
async def test_lastfm_no_apikey(bootstrap):
    """missing API key returns None"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/apikey", "")
    result = await plugin.download_async(
        {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
    )
    assert result is None


@pytest.mark.asyncio
async def test_lastfm_no_artist(bootstrap):
    """missing artist returns None"""
    plugin = _setup_plugin(bootstrap)
    result = await plugin.download_async({"title": "Hurt"})
    assert result is None


@pytest.mark.asyncio
async def test_lastfm_bio_and_website(bootstrap):
    """successful fetch returns bio and website"""
    plugin = _setup_plugin(bootstrap)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))

        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is not None
    assert result["artistlongbio"]
    assert "Read more on Last.fm" not in result["artistlongbio"]
    assert result["artistwebsites"] == ["https://www.last.fm/music/WNP+Mock+Artist"]


@pytest.mark.asyncio
async def test_lastfm_bio_stripped(bootstrap):
    """Last.fm attribution is stripped from bio"""
    plugin = _setup_plugin(bootstrap)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is not None
    assert "Read more on Last.fm" not in result["artistlongbio"]
    assert "WNP Mock Artist" in result["artistlongbio"]


@pytest.mark.asyncio
async def test_lastfm_bio_disabled(bootstrap):
    """bio disabled returns only website"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/bio", False)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is not None
    assert "artistlongbio" not in result
    assert result["artistwebsites"]


@pytest.mark.asyncio
async def test_lastfm_websites_disabled(bootstrap):
    """websites disabled returns only bio"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/websites", False)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is not None
    assert result["artistlongbio"]
    assert "artistwebsites" not in result


@pytest.mark.asyncio
async def test_lastfm_existing_bio_not_overwritten(bootstrap):
    """does not overwrite existing artistlongbio"""
    plugin = _setup_plugin(bootstrap)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "imagecacheartist": "wnpmockartist",
                "artistlongbio": "already set",
            },
        )

    # Only websites should be returned; bio was already set
    assert result is not None
    assert "artistlongbio" not in result
    assert result["artistwebsites"]


@pytest.mark.asyncio
async def test_lastfm_api_error(bootstrap):
    """Last.fm API error response returns None"""
    plugin = _setup_plugin(bootstrap)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(XYZ_URL).mock(
            return_value=httpx.Response(200, json={"error": 6, "message": "Artist not found"})
        )
        result = await plugin.download_async(
            {"artist": "XYZ Nonexistent Artist XYZ", "imagecacheartist": "xyz"},
        )

    assert result is None


@pytest.mark.asyncio
async def test_lastfm_http_error(bootstrap):
    """HTTP error returns None without raising"""
    plugin = _setup_plugin(bootstrap)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(side_effect=lambda _r: httpx.Response(503))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is None


@pytest.mark.asyncio
async def test_lastfm_429_sets_cooldown(bootstrap, isolated_datacache_client):  # pylint: disable=redefined-outer-name,unused-argument,undefined-variable
    """429 response sets provider cooldown; second call skips network"""
    plugin = _setup_plugin(bootstrap)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(
            side_effect=lambda _r: httpx.Response(429, headers={"Retry-After": "60"})
        )
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is None
    assert isolated_datacache_client._in_cooldown("lastfm")  # pylint: disable=protected-access

    # Second call during cooldown must not touch the network
    with respx.mock(assert_all_called=False) as mock_http2:
        mock_http2.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result2 = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )
    assert result2 is None
    assert not mock_http2.calls  # network was not hit


@pytest.mark.asyncio
async def test_lastfm_429_cooldown_expires_allows_retry(bootstrap, isolated_datacache_client):  # pylint: disable=redefined-outer-name,unused-argument,undefined-variable
    """After cooldown expires the next call hits the network again"""
    plugin = _setup_plugin(bootstrap)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(
            side_effect=lambda _r: httpx.Response(429, headers={"Retry-After": "60"})
        )
        await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert isolated_datacache_client._in_cooldown("lastfm")  # pylint: disable=protected-access

    # Force cooldown to expire
    isolated_datacache_client._retry_after_until["lastfm"] = 0.0  # pylint: disable=protected-access

    # After clearing, cooldown should be gone
    assert not isolated_datacache_client._in_cooldown("lastfm")  # pylint: disable=protected-access

    with respx.mock(assert_all_called=False) as mock_http2:
        mock_http2.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is not None


@pytest.mark.asyncio
async def test_lastfm_both_disabled_returns_none(bootstrap):
    """both bio and websites disabled returns None"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/bio", False)
    bootstrap.cparser.setValue("lastfm/websites", False)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is None


def test_lastfm_providerinfo(bootstrap):
    """providerinfo returns expected fields"""
    plugin = _setup_plugin(bootstrap)
    info = plugin.providerinfo()
    assert "artistlongbio" in info
    assert "artistwebsites" in info


@pytest.mark.asyncio
async def test_lastfm_lang_returned(bootstrap):
    """non-English lang is requested and bio uses that language"""
    plugin = _setup_plugin(bootstrap, lang="de")
    de_url = _artist_url("WNP Mock Artist", lang="de")

    de_response = {
        "artist": {
            "name": "WNP Mock Artist",
            "url": "https://www.last.fm/music/WNP+Mock+Artist",
            "bio": {
                "content": "WNP Mock Artist"
                " ist eine fiktive Industrialrock-Band."  # codespell:ignore
            },
        }
    }

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(de_url).mock(return_value=httpx.Response(200, json=de_response))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is not None
    assert "Industrialrock" in result["artistlongbio"]


@pytest.mark.asyncio
async def test_lastfm_lang_fallback_to_en(bootstrap):
    """empty bio in requested lang falls back to English when enabled"""
    plugin = _setup_plugin(bootstrap, lang="ko", en_fallback=True)
    ko_url = _artist_url("WNP Mock Artist", lang="ko")
    en_url = _artist_url("WNP Mock Artist", lang="en")

    ko_response = {
        "artist": {
            "name": "WNP Mock Artist",
            "url": "https://www.last.fm/music/WNP+Mock+Artist",
            "bio": {"content": ""},  # no Korean bio
        }
    }

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(ko_url).mock(return_value=httpx.Response(200, json=ko_response))
        mock_http.get(en_url).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is not None
    assert result["artistlongbio"]
    assert "WNP Mock Artist" in result["artistlongbio"]


@pytest.mark.asyncio
async def test_lastfm_lang_no_fallback(bootstrap):
    """empty bio in requested lang returns no bio when fallback is disabled"""
    plugin = _setup_plugin(bootstrap, lang="ko", en_fallback=False)
    ko_url = _artist_url("WNP Mock Artist", lang="ko")

    ko_response = {
        "artist": {
            "name": "WNP Mock Artist",
            "url": "https://www.last.fm/music/WNP+Mock+Artist",
            "bio": {"content": ""},
        }
    }

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(ko_url).mock(return_value=httpx.Response(200, json=ko_response))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    # website should still be returned even with no bio
    assert result is not None
    assert "artistlongbio" not in result
    assert result["artistwebsites"]


def _setup_live_plugin(bootstrap, lang: str = "en", en_fallback: bool = True):
    """Set up plugin with real API key from environment"""
    config = bootstrap
    configuresettings("lastfm", config.cparser)
    config.cparser.setValue("lastfm/apikey", os.environ["LASTFM_API_KEY"])
    config.cparser.setValue("lastfm/bio_lang", lang)
    config.cparser.setValue("lastfm/bio_lang_en_fallback", en_fallback)
    return nowplaying.artistextras.lastfm.Plugin(config=config)


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_bio_and_website(bootstrap):
    """live: successful fetch returns bio and website for Nine Inch Nails"""
    plugin = _setup_live_plugin(bootstrap)

    result = await plugin.download_async(
        {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
    )

    assert result is not None
    assert result.get("artistlongbio")
    assert "Read more on Last.fm" not in result["artistlongbio"]
    assert result.get("artistwebsites")
    assert any("last.fm" in url for url in result["artistwebsites"])


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_cache_consistency(bootstrap):
    """live: two calls return identical data (cache hit on second)"""
    plugin = _setup_live_plugin(bootstrap)
    metadata = {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"}

    result1 = await plugin.download_async(metadata.copy())
    result2 = await plugin.download_async(metadata.copy())

    assert result1 == result2


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_unknown_artist(bootstrap):
    """live: unknown artist returns None gracefully"""
    plugin = _setup_live_plugin(bootstrap)

    try:
        result = await plugin.download_async(
            {"artist": "XYZ Nonexistent Artist XYZ 99999", "imagecacheartist": "xyz"},
        )
        assert result is None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        pytest.fail(f"Plugin raised exception for unknown artist: {exc}")


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_lang_fallback(bootstrap):
    """live: Korean lang with EN fallback returns English bio for NIN (no Korean bio exists)"""
    plugin = _setup_live_plugin(bootstrap, lang="ko", en_fallback=True)
    result = await plugin.download_async(
        {"artist": "Nine Inch Nails", "imagecacheartist": "nineinchnails"},
    )

    assert result is not None
    assert result.get("artistlongbio"), "Expected English fallback bio"


@pytest.mark.asyncio
async def test_lastfm_coverart_queued(bootstrap):  # pylint: disable=redefined-outer-name
    """album cover art URL is queued in datacache when album is present"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        mock_http.get(WNP_MOCK_ALBUM_URL).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ALBUM_RESPONSE)
        )
        mock_http.get(COVER_IMAGE_URL).mock(return_value=httpx.Response(200, content=b"fake_jpg"))
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
            },
        )
        await nowplaying.datacache.get_client().process_queue()

    assert result is not None
    keys = await nowplaying.datacache.get_client().storage.get_cache_keys_for_identifier(
        "wnpmockartist_wnpmockalbum", "front_cover"
    )
    assert keys, "Cover art should be stored after queue processing"


@pytest.mark.asyncio
async def test_lastfm_coverart_disabled(bootstrap):  # pylint: disable=redefined-outer-name
    """album cover art is not fetched when coverart setting is disabled"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", False)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
            },
        )

    assert result is not None
    assert not await datacache_has_pending(
        nowplaying.datacache.get_client(), "wnpmockartist_wnpmockalbum", "front_cover"
    )


@pytest.mark.asyncio
async def test_lastfm_coverart_skipped_when_coverimageraw_present(
    bootstrap,
):  # pylint: disable=redefined-outer-name
    """album cover art fetch is skipped when coverimageraw already in metadata"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
                "coverimageraw": b"\xff\xd8\xff",
            },
        )

    assert result is not None
    assert not await datacache_has_pending(
        nowplaying.datacache.get_client(), "wnpmockartist_wnpmockalbum", "front_cover"
    )


@pytest.mark.asyncio
async def test_lastfm_coverart_no_album(bootstrap):  # pylint: disable=redefined-outer-name
    """album cover art fetch is skipped when no album in metadata"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is not None
    assert not await datacache_has_pending(
        nowplaying.datacache.get_client(), "wnpmockartist", "front_cover"
    )


@pytest.mark.asyncio
async def test_lastfm_coverart_album_api_error(bootstrap):  # pylint: disable=redefined-outer-name
    """album API error does not prevent artist data from being returned"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        mock_http.get(WNP_MOCK_ALBUM_URL).mock(
            return_value=httpx.Response(200, json={"error": 6, "message": "Album not found"})
        )
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
            },
        )

    assert result is not None
    assert result.get("artistlongbio") or result.get("artistwebsites")
    assert not await datacache_has_pending(
        nowplaying.datacache.get_client(), "wnpmockartist_wnpmockalbum", "front_cover"
    )


@pytest.mark.asyncio
async def test_lastfm_coverart_with_album_mbid(bootstrap):  # pylint: disable=redefined-outer-name
    """album cover art uses MBID-based URL when musicbrainzalbumid is present"""
    plugin = _setup_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)
    album_mbid = "00000000-0000-0000-0000-000000000002"
    mbid_url = _album_mbid_url(album_mbid)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_URL).mock(return_value=httpx.Response(200, json=WNP_MOCK_RESPONSE))
        mock_http.get(mbid_url).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ALBUM_RESPONSE)
        )
        mock_http.get(COVER_IMAGE_URL).mock(return_value=httpx.Response(200, content=b"fake_jpg"))
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
                "musicbrainzalbumid": album_mbid,
            },
        )
        await nowplaying.datacache.get_client().process_queue()

    assert result is not None
    keys = await nowplaying.datacache.get_client().storage.get_cache_keys_for_identifier(
        "wnpmockartist_wnpmockalbum", "front_cover"
    )
    assert keys, "Cover art should be stored after queue processing"


@pytest.mark.asyncio
@skip_no_lastfm_key
async def test_lastfm_live_coverart(bootstrap):  # pylint: disable=redefined-outer-name
    """live: album cover art is downloaded for Nine Inch Nails - The Downward Spiral"""
    plugin = _setup_live_plugin(bootstrap)
    bootstrap.cparser.setValue("lastfm/coverart", True)
    result = await plugin.download_async(
        {
            "artist": "Nine Inch Nails",
            "album": "The Downward Spiral",
            "imagecacheartist": "nineinchnails",
        },
    )
    await nowplaying.datacache.get_client().process_queue()

    assert result is not None
    keys = await nowplaying.datacache.get_client().storage.get_cache_keys_for_identifier(
        "nineinchnails_thedownwardspiral", "front_cover"
    )
    assert keys, "Cover art should be downloaded and stored"
