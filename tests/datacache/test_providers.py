"""
Unit tests for datacache providers layer.

Tests the provider-specific interfaces for MusicBrainz,
images, and API responses.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

import nowplaying.datacache.providers


@pytest_asyncio.fixture
async def temp_providers(bootstrap):
    """Create temporary providers instance"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        providers = nowplaying.datacache.providers.DataCacheProviders(temp_path)
        await providers.initialize()
        yield providers
        await providers.close()


@pytest.mark.asyncio
async def test_providers_initialization(temp_providers):
    """Test providers initialize correctly"""
    assert temp_providers.client._initialized is True
    assert temp_providers.musicbrainz is not None
    assert temp_providers.images is not None
    assert temp_providers.api is not None


@pytest.mark.asyncio
async def test_musicbrainz_search_artists(temp_providers):
    """Test MusicBrainz artist search"""
    # Mock successful search
    with patch.object(temp_providers.client, "get_or_fetch") as mock_fetch:
        mock_fetch.return_value = (
            {"artists": [{"id": "123", "name": "Test Artist"}]},
            {"query": "test", "limit": 10},
        )

        result = await temp_providers.musicbrainz.search_artists(
            query="test", limit=10, immediate=True
        )

        assert result is not None
        data, metadata = result
        assert "artists" in data
        assert data["artists"][0]["name"] == "Test Artist"

        # Verify correct URL construction
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        assert "musicbrainz.org/ws/2/artist" in call_args[1]["url"]
        assert call_args[1]["identifier"] == "search_test"
        assert call_args[1]["data_type"] == "artist_search"
        assert call_args[1]["provider"] == "musicbrainz"


@pytest.mark.asyncio
async def test_musicbrainz_get_artist(temp_providers):
    """Test MusicBrainz get artist by ID"""
    artist_id = "123e4567-e89b-12d3-a456-426614174000"

    with patch.object(temp_providers.client, "get_or_fetch") as mock_fetch:
        mock_fetch.return_value = (
            {"id": artist_id, "name": "Test Artist", "type": "Person"},
            {"artist_id": artist_id},
        )

        result = await temp_providers.musicbrainz.get_artist(
            artist_id=artist_id, includes=["recordings"], immediate=True
        )

        assert result is not None
        data, metadata = result
        assert data["id"] == artist_id
        assert data["name"] == "Test Artist"

        # Verify URL includes parameters
        call_args = mock_fetch.call_args
        assert artist_id in call_args[1]["url"]
        assert "inc=recordings" in call_args[1]["url"]


@pytest.mark.asyncio
async def test_musicbrainz_search_recordings(temp_providers):
    """Test MusicBrainz recording search"""
    with patch.object(temp_providers.client, "get_or_fetch") as mock_fetch:
        mock_fetch.return_value = (
            {"recordings": [{"id": "rec123", "title": "Test Song"}]},
            {"query": "test song", "limit": 5},
        )

        result = await temp_providers.musicbrainz.search_recordings(
            query="test song", limit=5, immediate=True
        )

        assert result is not None
        data, metadata = result
        assert "recordings" in data

        call_args = mock_fetch.call_args
        assert "recording" in call_args[1]["url"]
        assert call_args[1]["identifier"] == "recording_search_test_song"


@pytest.mark.parametrize(
    "image_type,method_name,test_url,expected_data,return_metadata,artist_id,provider,immediate",
    [
        (
            "thumbnail",
            "cache_artist_thumbnail",
            "https://example.com/thumbnail.jpg",
            b"thumbnail_data",
            {"width": 200, "height": 200},
            "test_artist",
            "theaudiodb",
            True,
        ),
        (
            "logo",
            "cache_artist_logo",
            "https://example.com/logo.png",
            b"logo_data",
            {"format": "png"},
            "logo_artist",
            "discogs",
            False,
        ),
        (
            "banner",
            "cache_artist_banner",
            "https://example.com/banner.jpg",
            b"banner_data",
            {"dimensions": "1920x480"},
            "banner_artist",
            "fanarttv",
            True,
        ),
        (
            "fanart",
            "cache_artist_fanart",
            "https://example.com/fanart.jpg",
            b"fanart_data",
            {"quality": "hd"},
            "fanart_artist",
            "fanarttv",
            True,
        ),
    ],
)
@pytest.mark.asyncio
async def test_image_cache_artist_types(
    temp_providers,
    image_type,
    method_name,
    test_url,
    expected_data,
    return_metadata,
    artist_id,
    provider,
    immediate,
):
    """Test caching different artist image types"""
    with patch.object(temp_providers.client, "get_or_fetch") as mock_fetch:
        mock_fetch.return_value = (expected_data, return_metadata)

        # Get the method dynamically
        cache_method = getattr(temp_providers.images, method_name)

        # Call with consistent parameters
        result = await cache_method(
            url=test_url,
            artist_identifier=artist_id,
            provider=provider,
            immediate=immediate,
        )

        assert result is not None
        data, metadata = result
        assert data == expected_data

        # Verify correct parameters were passed to client
        call_args = mock_fetch.call_args
        assert call_args[1]["url"] == test_url
        assert call_args[1]["identifier"] == artist_id
        assert call_args[1]["data_type"] == image_type
        assert call_args[1]["provider"] == provider
        assert call_args[1]["immediate"] == immediate


@pytest.mark.asyncio
async def test_image_get_random_image(temp_providers):
    """Test getting random image"""
    with patch.object(temp_providers.client, "get_random_image") as mock_random:
        mock_random.return_value = (
            b"random_image",
            {"type": "thumbnail"},
            "https://example.com/1.jpg",
        )

        result = await temp_providers.images.get_random_image(
            artist_identifier="random_artist", image_type="thumbnail", provider="test"
        )

        assert result is not None
        data, metadata, url = result
        assert data == b"random_image"

        mock_random.assert_called_once_with(
            identifier="random_artist", data_type="thumbnail", provider="test"
        )


@pytest.mark.asyncio
async def test_image_get_cache_keys_for_identifier(temp_providers):
    """Test getting cache keys for identifier"""
    with patch.object(temp_providers.client, "get_cache_keys_for_identifier") as mock_keys:
        mock_keys.return_value = ["key1", "key2"]

        results = await temp_providers.images.get_cache_keys_for_identifier(
            artist_identifier="all_artist",
            image_type="logo",
        )

        assert isinstance(results, list)
        assert len(results) == 2

        mock_keys.assert_called_once_with(identifier="all_artist", data_type="logo", provider=None)


@pytest.mark.asyncio
async def test_api_cache_api_response(temp_providers):
    """Test caching generic API response"""
    test_url = "https://api.example.com/artist/123"
    test_data = {"name": "Test Artist", "bio": "Artist biography"}

    with patch.object(temp_providers.client, "get_or_fetch") as mock_fetch:
        mock_fetch.return_value = (test_data, {"cached_at": "2023-01-01"})

        result = await temp_providers.api.cache_api_response(
            url=test_url,
            identifier="api_test_artist",
            data_type="biography",
            provider="test_api",
            immediate=True,
            metadata={"language": "en"},
            timeout=15.0,
            ttl_seconds=7200,
        )

        assert result is not None
        data, metadata = result
        assert data == test_data

        call_args = mock_fetch.call_args
        assert call_args[1]["url"] == test_url
        assert call_args[1]["data_type"] == "biography"
        assert call_args[1]["timeout"] == 15.0
        assert call_args[1]["ttl_seconds"] == 7200


@pytest.mark.asyncio
async def test_api_cache_artist_bio(temp_providers):
    """Test caching artist biography"""
    test_url = "https://api.example.com/bio/artist"

    with patch.object(temp_providers.api, "cache_api_response") as mock_cache:
        mock_cache.return_value = ({"biography": "Artist bio text"}, {"lang": "en"})

        result = await temp_providers.api.cache_artist_bio(
            url=test_url,
            artist_identifier="bio_artist",
            provider="test_api",
            language="en",
            immediate=True,
            metadata={"source": "wikipedia"},
        )

        assert result is not None

        # Verify cache_api_response was called with correct parameters
        mock_cache.assert_called_once()
        call_args = mock_cache.call_args
        assert call_args[1]["url"] == test_url
        assert call_args[1]["identifier"] == "bio_artist"
        assert call_args[1]["data_type"] == "bio_en"
        assert call_args[1]["ttl_seconds"] == 7 * 24 * 3600  # 1 week

        # Verify metadata includes language
        bio_metadata = call_args[1]["metadata"]
        assert bio_metadata["language"] == "en"
        assert bio_metadata["source"] == "wikipedia"


@pytest.mark.asyncio
async def test_providers_process_queue(temp_providers):
    """Test queue processing through providers"""
    with patch.object(temp_providers.client, "process_queue") as mock_process:
        mock_process.return_value = {"processed": 5, "succeeded": 4, "failed": 1}

        stats = await temp_providers.process_queue(provider="test")

        assert stats["processed"] == 5
        assert stats["succeeded"] == 4
        assert stats["failed"] == 1

        mock_process.assert_called_once_with("test")


def test_get_providers_singleton():
    """Test providers singleton behavior"""
    # Should return same instance
    providers1 = nowplaying.datacache.providers.get_providers()
    providers2 = nowplaying.datacache.providers.get_providers()

    assert providers1 is providers2


@pytest.mark.asyncio
async def test_musicbrainz_provider_configuration(temp_providers):
    """Test MusicBrainz provider has correct configuration"""
    mb = temp_providers.musicbrainz

    assert mb.base_url == "https://musicbrainz.org/ws/2"
    assert mb.rate_limit == 1.0  # 1 request per second
    assert mb.timeout == 15.0
    assert mb.retries == 3
    assert mb.ttl_seconds == 30 * 24 * 3600  # 1 month


@pytest.mark.asyncio
async def test_image_provider_configuration(temp_providers):
    """Test image provider has correct configuration"""
    img = temp_providers.images

    assert img.timeout == 30.0
    assert img.retries == 3
    assert img.ttl_seconds == 14 * 24 * 3600  # 2 weeks


@pytest.mark.asyncio
async def test_api_provider_configuration(temp_providers):
    """Test API provider has correct configuration"""
    api = temp_providers.api

    assert api.timeout == 30.0
    assert api.retries == 3
    assert api.ttl_seconds == 7 * 24 * 3600  # 1 week


@pytest.mark.asyncio
async def test_providers_share_same_client(temp_providers):
    """Test all providers share the same client instance"""
    # All providers should share the same client
    assert temp_providers.musicbrainz.client is temp_providers.client
    assert temp_providers.images.client is temp_providers.client
    assert temp_providers.api.client is temp_providers.client
