"""
Provider-specific caching interfaces for datacache.

This module provides specialized interfaces for different data providers
that artist extras plugins commonly use.
"""

import urllib.parse
from pathlib import Path
from typing import Any

from .client import DataCacheClient


class MusicBrainzProvider:
    """
    Caching interface for MusicBrainz API calls.

    Handles rate limiting (1 req/sec) and provides unified caching
    for artist lookups, recordings, releases, etc.
    """

    def __init__(self, client: DataCacheClient):
        self.client = client
        self.base_url = "https://musicbrainz.org/ws/2"
        self.rate_limit = 1.0  # 1 request per second
        self.timeout = 15.0
        self.retries = 3
        self.ttl_seconds = 30 * 24 * 3600  # 1 month

    async def search_artists(
        self, query: str, limit: int = 10, immediate: bool = True
    ) -> tuple[Any, dict] | None:
        """
        Search for artists by name or query.

        Args:
            query: Search query string
            limit: Maximum number of results
            immediate: Whether to fetch immediately or queue

        Returns:
            Tuple of (search_results, metadata) or None
        """
        # Construct URL
        params = {"query": query, "fmt": "json", "limit": str(limit)}
        query_string = urllib.parse.urlencode(params)
        url = f"{self.base_url}/artist?{query_string}"

        # Use query as identifier for caching
        identifier = f"search_{query}".replace(" ", "_").lower()

        return await self.client.get_or_fetch(
            url=url,
            identifier=identifier,
            data_type="artist_search",
            provider="musicbrainz",
            timeout=self.timeout,
            retries=self.retries,
            ttl_seconds=self.ttl_seconds,
            immediate=immediate,
            metadata={"query": query, "limit": limit},
        )

    async def get_artist(
        self, artist_id: str, includes: list[str] | None = None, immediate: bool = True
    ) -> tuple[Any, dict] | None:
        """
        Get artist details by MusicBrainz ID.

        Args:
            artist_id: MusicBrainz artist ID
            includes: List of related data to include
            immediate: Whether to fetch immediately or queue

        Returns:
            Tuple of (artist_data, metadata) or None
        """
        # Construct URL
        params = {"fmt": "json"}
        if includes:
            params["inc"] = "+".join(includes)

        query_string = urllib.parse.urlencode(params)
        url = f"{self.base_url}/artist/{artist_id}?{query_string}"

        return await self.client.get_or_fetch(
            url=url,
            identifier=artist_id,
            data_type="artist_details",
            provider="musicbrainz",
            timeout=self.timeout,
            retries=self.retries,
            ttl_seconds=self.ttl_seconds,
            immediate=immediate,
            metadata={"artist_id": artist_id, "includes": includes},
        )

    async def search_recordings(
        self, query: str, limit: int = 10, immediate: bool = True
    ) -> tuple[Any, dict] | None:
        """
        Search for recordings by query.

        Args:
            query: Search query string
            limit: Maximum number of results
            immediate: Whether to fetch immediately or queue

        Returns:
            Tuple of (search_results, metadata) or None
        """
        # Construct URL
        params = {"query": query, "fmt": "json", "limit": str(limit)}
        query_string = urllib.parse.urlencode(params)
        url = f"{self.base_url}/recording?{query_string}"

        # Use query as identifier for caching
        identifier = f"recording_search_{query}".replace(" ", "_").lower()

        return await self.client.get_or_fetch(
            url=url,
            identifier=identifier,
            data_type="recording_search",
            provider="musicbrainz",
            timeout=self.timeout,
            retries=self.retries,
            ttl_seconds=self.ttl_seconds,
            immediate=immediate,
            metadata={"query": query, "limit": limit},
        )


class ImageProvider:
    """
    Unified caching interface for image data from various providers.

    Supports TheAudioDB, FanartTV, Discogs images, and other image sources
    with automatic classification (thumbnail, logo, banner, fanart).
    """

    def __init__(self, client: DataCacheClient):
        self.client = client
        self.timeout = 30.0
        self.retries = 3
        self.ttl_seconds = 14 * 24 * 3600  # 2 weeks for images

    async def cache_artist_thumbnail(  # pylint: disable=too-many-arguments
        self,
        url: str,
        artist_identifier: str,
        provider: str,
        immediate: bool = True,
        metadata: dict | None = None,
    ) -> tuple[Any, dict] | None:
        """
        Cache an artist thumbnail image.

        Args:
            url: Image URL
            artist_identifier: Artist identifier (e.g., "daft_punk")
            provider: Provider name ("theaudiodb", "discogs", etc.)
            immediate: Whether to fetch immediately or queue
            metadata: Optional image metadata

        Returns:
            Tuple of (image_data, metadata) or None
        """
        return await self.client.get_or_fetch(
            url=url,
            identifier=artist_identifier,
            data_type="thumbnail",
            provider=provider,
            timeout=self.timeout,
            retries=self.retries,
            ttl_seconds=self.ttl_seconds,
            immediate=immediate,
            metadata=metadata,
        )

    async def cache_artist_logo(  # pylint: disable=too-many-arguments
        self,
        url: str,
        artist_identifier: str,
        provider: str,
        immediate: bool = True,
        metadata: dict | None = None,
    ) -> tuple[Any, dict] | None:
        """
        Cache an artist logo image.

        Args:
            url: Image URL
            artist_identifier: Artist identifier (e.g., "daft_punk")
            provider: Provider name
            immediate: Whether to fetch immediately or queue
            metadata: Optional image metadata

        Returns:
            Tuple of (image_data, metadata) or None
        """
        return await self.client.get_or_fetch(
            url=url,
            identifier=artist_identifier,
            data_type="logo",
            provider=provider,
            timeout=self.timeout,
            retries=self.retries,
            ttl_seconds=self.ttl_seconds,
            immediate=immediate,
            metadata=metadata,
        )

    async def cache_artist_banner(  # pylint: disable=too-many-arguments
        self,
        url: str,
        artist_identifier: str,
        provider: str,
        immediate: bool = True,
        metadata: dict | None = None,
    ) -> tuple[Any, dict] | None:
        """
        Cache an artist banner image.

        Args:
            url: Image URL
            artist_identifier: Artist identifier (e.g., "daft_punk")
            provider: Provider name
            immediate: Whether to fetch immediately or queue
            metadata: Optional image metadata

        Returns:
            Tuple of (image_data, metadata) or None
        """
        return await self.client.get_or_fetch(
            url=url,
            identifier=artist_identifier,
            data_type="banner",
            provider=provider,
            timeout=self.timeout,
            retries=self.retries,
            ttl_seconds=self.ttl_seconds,
            immediate=immediate,
            metadata=metadata,
        )

    async def cache_artist_fanart(  # pylint: disable=too-many-arguments
        self,
        url: str,
        artist_identifier: str,
        provider: str,
        immediate: bool = True,
        metadata: dict | None = None,
    ) -> tuple[Any, dict] | None:
        """
        Cache an artist fanart image.

        Args:
            url: Image URL
            artist_identifier: Artist identifier (e.g., "daft_punk")
            provider: Provider name
            immediate: Whether to fetch immediately or queue
            metadata: Optional image metadata

        Returns:
            Tuple of (image_data, metadata) or None
        """
        return await self.client.get_or_fetch(
            url=url,
            identifier=artist_identifier,
            data_type="fanart",
            provider=provider,
            timeout=self.timeout,
            retries=self.retries,
            ttl_seconds=self.ttl_seconds,
            immediate=immediate,
            metadata=metadata,
        )

    async def get_random_image(
        self, artist_identifier: str, image_type: str, provider: str | None = None
    ) -> tuple[Any, dict] | None:
        """
        Get a random image for an artist and type.

        This supports the randomimage() functionality.

        Args:
            artist_identifier: Artist identifier
            image_type: Type of image ("thumbnail", "logo", "banner", "fanart")
            provider: Optional provider filter

        Returns:
            Tuple of (image_data, metadata) or None
        """
        return await self.client.get_random_image(
            identifier=artist_identifier, data_type=image_type, provider=provider
        )

    async def get_cache_keys_for_identifier(
        self, artist_identifier: str, image_type: str, provider: str | None = None
    ) -> list[str]:
        """
        Get cache keys for an artist and type.

        Compatible with imagecache.get_cache_keys_for_identifier() for WebSocket interface.

        Args:
            artist_identifier: Artist identifier
            image_type: Type of image ("thumbnail", "logo", "banner", "fanart")
            provider: Optional provider filter

        Returns:
            List of cache key strings
        """
        return await self.client.get_cache_keys_for_identifier(
            identifier=artist_identifier, data_type=image_type, provider=provider
        )


class APIProvider:
    """
    Generic API caching provider for JSON/text responses.

    Suitable for TheAudioDB, Discogs API, FanartTV, and other REST APIs
    that return structured data.
    """

    def __init__(self, client: DataCacheClient):
        self.client = client
        self.timeout = 30.0
        self.retries = 3
        self.ttl_seconds = 7 * 24 * 3600  # 1 week for API data

    async def cache_api_response(  # pylint: disable=too-many-arguments
        self,
        url: str,
        identifier: str,
        data_type: str,
        provider: str,
        immediate: bool = True,
        metadata: dict | None = None,
        timeout: float | None = None,
        ttl_seconds: int | None = None,
    ) -> tuple[Any, dict] | None:
        """
        Cache a generic API response.

        Args:
            url: API endpoint URL
            identifier: Identifier for the data (artist name, etc.)
            data_type: Type of data ("bio", "discography", "metadata", etc.)
            provider: Provider name
            immediate: Whether to fetch immediately or queue
            metadata: Optional response metadata
            timeout: Custom timeout (uses default if None)
            ttl_seconds: Custom TTL (uses default if None)

        Returns:
            Tuple of (api_data, metadata) or None
        """
        return await self.client.get_or_fetch(
            url=url,
            identifier=identifier,
            data_type=data_type,
            provider=provider,
            timeout=timeout or self.timeout,
            retries=self.retries,
            ttl_seconds=ttl_seconds or self.ttl_seconds,
            immediate=immediate,
            metadata=metadata,
        )

    async def cache_artist_bio(  # pylint: disable=too-many-arguments
        self,
        url: str,
        artist_identifier: str,
        provider: str,
        language: str = "en",
        immediate: bool = True,
        metadata: dict | None = None,
    ) -> tuple[Any, dict] | None:
        """
        Cache artist biography data.

        Args:
            url: Bio data URL
            artist_identifier: Artist identifier
            provider: Provider name
            language: Language code for the bio
            immediate: Whether to fetch immediately or queue
            metadata: Optional bio metadata

        Returns:
            Tuple of (bio_data, metadata) or None
        """
        bio_metadata = {"language": language}
        if metadata:
            bio_metadata |= metadata

        return await self.cache_api_response(
            url=url,
            identifier=artist_identifier,
            data_type=f"bio_{language}",
            provider=provider,
            immediate=immediate,
            metadata=bio_metadata,
            ttl_seconds=7 * 24 * 3600,  # 1 week for bio data
        )


class DataCacheProviders:
    """
    Unified provider interface for datacache operations.

    Provides access to all specialized provider interfaces through
    a single entry point.
    """

    def __init__(self, cache_dir: Path | None = None):
        self.client = DataCacheClient(cache_dir)
        self.musicbrainz = MusicBrainzProvider(self.client)
        self.images = ImageProvider(self.client)
        self.api = APIProvider(self.client)

    async def initialize(self) -> None:
        """Initialize the providers and underlying client"""
        await self.client.initialize()

    async def close(self) -> None:
        """Close providers and cleanup resources"""
        await self.client.close()

    async def process_queue(self, provider: str | None = None) -> dict[str, Any]:
        """
        Process pending requests from the queue.

        Args:
            provider: Optional provider filter

        Returns:
            Processing statistics
        """
        return await self.client.process_queue(provider)


# Global providers instance
_providers_instance: DataCacheProviders | None = None


def get_providers(cache_dir: Path | None = None) -> DataCacheProviders:
    """Get the global datacache providers instance"""
    global _providers_instance  # pylint: disable=global-statement
    if _providers_instance is None:
        _providers_instance = DataCacheProviders(cache_dir)
    return _providers_instance


# Example usage for artist extras plugins:
#
# async def download_async(self, metadata, imagecache=None):
#     """Artist extras plugin implementation using datacache"""
#     providers = get_providers()
#     await providers.initialize()
#
#     artist_name = metadata.get("artist")
#     if not artist_name:
#         return None
#
#     # Create normalized identifier
#     identifier = artist_name.lower().replace(" ", "_")
#
#     # Fetch artist bio (immediate)
#     bio_url = f"https://api.provider.com/artist/{artist_name}/bio"
#     bio_result = await providers.api.cache_artist_bio(
#         url=bio_url,
#         artist_identifier=identifier,
#         provider="provider_name",
#         immediate=True
#     )
#
#     if bio_result:
#         bio_data, bio_metadata = bio_result
#         metadata["artistlongbio"] = bio_data.get("biography", "")
#
#     # Queue image fetches (background)
#     if imagecache:
#         image_urls = ["https://api.provider.com/image1.jpg",
#                      "https://api.provider.com/image2.jpg"]
#
#         for url in image_urls:
#             await providers.images.cache_artist_thumbnail(
#                 url=url,
#                 artist_identifier=identifier,
#                 provider="provider_name",
#                 immediate=False  # Queue for background
#             )
#
#     return metadata
