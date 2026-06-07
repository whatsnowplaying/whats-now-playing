#!/usr/bin/env python3
"""test artistextras fanarttv plugin"""

import os

import httpx
import pytest
import respx
from utils_artistextras import (
    FakeImageCache,
    configureplugins,
    configuresettings,
    run_cache_consistency_test,
    skip_no_fanarttv_key,
)


def _setup_fanarttv_plugin(bootstrap):
    """Set up FanartTV plugin for testing"""
    config = bootstrap
    configuresettings("fanarttv", config.cparser)
    config.cparser.setValue("fanarttv/apikey", os.environ["FANARTTV_API_KEY"])
    imagecaches, plugins = configureplugins(config)
    return plugins["fanarttv"], imagecaches["fanarttv"]


def _get_test_metadata():
    """Get test metadata for FanartTV (requires MBID)"""
    return {
        "album": "The Downward Spiral",
        "artist": "Nine Inch Nails",
        "imagecacheartist": "nineinchnails",
        "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],  # NIN's MBID
    }


@pytest.mark.asyncio
@skip_no_fanarttv_key
async def test_fanarttv_apicache_usage(bootstrap):
    """test that fanarttv plugin uses apicache for API calls"""
    plugin, imagecache = _setup_fanarttv_plugin(bootstrap)

    await run_cache_consistency_test(
        plugin=plugin,
        test_metadata=_get_test_metadata(),
        imagecache=imagecache,
        success_message="FanartTV API call successful, caching verified",
    )


@pytest.mark.asyncio
@skip_no_fanarttv_key
async def test_fanarttv_apicache_api_call_count(bootstrap, isolated_datacache_client):  # pylint: disable=redefined-outer-name,unused-argument
    """test that fanarttv makes only one HTTP call when the cache is warm"""
    plugin, imagecache = _setup_fanarttv_plugin(bootstrap)
    mbid = "b7ffd2af-418f-4be2-bdd1-22f8b48613da"
    url = f"http://webservice.fanart.tv/v3/music/{mbid}"
    mock_payload = {"name": "Nine Inch Nails"}

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(url).mock(return_value=httpx.Response(200, json=mock_payload))
        await plugin.download_async(_get_test_metadata().copy(), imagecache=imagecache)
        first_count = mock_http.calls.call_count
        assert first_count >= 1

        await plugin.download_async(_get_test_metadata().copy(), imagecache=imagecache)
        assert mock_http.calls.call_count == first_count, "Second call should hit cache"


@pytest.mark.asyncio
@skip_no_fanarttv_key
async def test_fanarttv_apicache_api_failure_behavior(bootstrap, isolated_datacache_client):  # pylint: disable=redefined-outer-name,unused-argument
    """test that fanarttv doesn't cache failed API calls; second call retries"""
    plugin, imagecache = _setup_fanarttv_plugin(bootstrap)
    mbid = "invalid-mbid-that-will-fail"
    url = f"http://webservice.fanart.tv/v3/music/{mbid}"
    metadata = {
        "album": "Test Album",
        "artist": "Test Artist",
        "imagecacheartist": "testartist",
        "musicbrainzartistid": [mbid],
    }

    # First call: 500 (transient server error) → not cached → returns None
    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(url).mock(side_effect=lambda _r: httpx.Response(500))
        result1 = await plugin.download_async(metadata.copy(), imagecache=imagecache)
        assert result1 is None

    # Second call: success → should reach API (transient failure was not cached)
    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(url).mock(return_value=httpx.Response(200, json={"name": "Test Artist"}))
        result2 = await plugin.download_async(metadata.copy(), imagecache=imagecache)
        assert mock_http.calls.call_count >= 1, "Transient failure must not have been cached"
        _ = result2


@pytest.mark.asyncio
@skip_no_fanarttv_key
async def test_fanarttv_coverart(bootstrap):
    """test that fanarttv fetches album cover art for a known album"""
    config = bootstrap
    configuresettings("fanarttv", config.cparser)
    config.cparser.setValue("fanarttv/apikey", os.environ["FANARTTV_API_KEY"])
    config.cparser.setValue("fanarttv/coverart", True)
    for field in ["banners", "logos", "fanart", "thumbnails"]:
        config.cparser.setValue(f"fanarttv/{field}", False)
    imagecaches, plugins = configureplugins(config)

    metadata = {
        "artist": "Nine Inch Nails",
        "album": "Ghosts I-IV",
        "imagecacheartist": "nineinchnails",
        "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],
        "musicbrainzreleasegroupid": "550bf4b9-92ca-30ba-9ea2-8b45f9d081f1",
    }

    await plugins["fanarttv"].download_async(metadata, imagecache=imagecaches["fanarttv"])

    identifier = "Nine Inch Nails_Ghosts I-IV"
    assert "front_cover" in imagecaches["fanarttv"].urls.get(identifier, {})


@pytest.mark.asyncio
async def test_fanarttv_coverart_no_album_mbid(bootstrap):
    """test that cover art is not queued when musicbrainzalbumid is absent"""
    config = bootstrap
    config.cparser.setValue("fanarttv/enabled", True)
    config.cparser.setValue("fanarttv/apikey", "fake-test-key")
    config.cparser.setValue("fanarttv/coverart", True)
    for field in ["banners", "logos", "fanart", "thumbnails"]:
        config.cparser.setValue(f"fanarttv/{field}", False)

    plugin = config.pluginobjs["artistextras"]["nowplaying.artistextras.fanarttv"]
    imagecache = FakeImageCache()

    async def mock_fetch(apikey, artistid):  # pylint: disable=unused-argument
        return {
            "albums": {
                "some-mbid": {
                    "albumcover": [{"url": "https://example.com/cover.jpg", "likes": 10}]
                }
            }
        }

    plugin._fetch_async = mock_fetch  # pylint: disable=protected-access

    metadata = {
        "artist": "Nine Inch Nails",
        "album": "The Downward Spiral",
        "imagecacheartist": "nineinchnails",
        "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],
        # no musicbrainzalbumid
    }

    await plugin.download_async(metadata, imagecache=imagecache)

    identifier = "Nine Inch Nails_The Downward Spiral"
    assert "front_cover" not in imagecache.urls.get(identifier, {})
