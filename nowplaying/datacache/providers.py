"""
Provider-specific caching interfaces for datacache.

This module provides specialized interfaces for different data providers
that artist extras plugins commonly use.
"""

from pathlib import Path
from typing import Any

from .client import DataCacheClient


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

    async def cache_artist_thumbnail(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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

    async def cache_artist_logo(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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

    async def cache_artist_banner(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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

    async def cache_artist_fanart(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
    ) -> tuple[Any, dict, str] | None:
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

    async def fill_queue(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        identifier: str,
        imagetype: str,
        srclocationlist: list[str],
        provider: str,
        maxcount: int | None = None,
    ) -> int:
        """
        Queue multiple image URLs for background fetching.

        Replaces imagecache.fill_queue() for the same purpose: given a list of
        image URLs from an artist-extras plugin, queue them all for background
        download without blocking the track-polling loop.

        Args:
            identifier: Artist identifier (e.g., "daft_punk")
            imagetype: Image type ("thumbnail", "logo", "banner", "fanart")
            srclocationlist: List of image URLs to queue
            provider: Provider name ("theaudiodb", "discogs", etc.)
            maxcount: Maximum number of URLs to queue (None = all)

        Returns:
            Number of URLs successfully queued (already-cached URLs count as 0
            new queues but are not errors)
        """
        if not srclocationlist:
            return 0

        urls = srclocationlist[:maxcount] if maxcount is not None else srclocationlist
        queued = 0
        for url in urls:
            success = await self.client.queue_url_fetch(
                url=url,
                identifier=identifier,
                data_type=imagetype,
                provider=provider,
                timeout=self.timeout,
                retries=self.retries,
                ttl_seconds=self.ttl_seconds,
                priority=2,  # batch — background
            )
            if success:
                queued += 1
        return queued

    async def random_image_bytes(
        self, artist_identifier: str, image_type: str, provider: str | None = None
    ) -> bytes | None:
        """
        Return random image bytes for an artist and type.

        Simplified interface (no metadata) as a direct replacement for
        imagecache.random_image_fetch() callers that only need the raw bytes.

        Args:
            artist_identifier: Artist identifier
            image_type: Image type ("thumbnail", "logo", "banner", "fanart")
            provider: Optional provider filter

        Returns:
            Raw image bytes, or None if no images are cached
        """
        result = await self.get_random_image(artist_identifier, image_type, provider)
        if result:
            image_data, _metadata, _url = result
            if isinstance(image_data, bytes):
                return image_data
        return None

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

    async def cache_api_response(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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

    async def cache_artist_bio(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
_providers_instance: DataCacheProviders | None = None  # pylint: disable=invalid-name


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
