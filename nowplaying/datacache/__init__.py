"""
DataCache - Unified caching system for whats-now-playing application.

This module provides a replacement for both apicache.py and imagecache.py
with improved performance, multiprocess support, and URL-based caching.

Key Features:
- URL-based primary keys for natural deduplication
- Support for randomimage() functionality via identifier+data_type indexing
- Database-backed queues for multiprocess coordination
- Async-first architecture with rate limiting
- Unified interface for images, API responses, and metadata

Example usage:

    # Get providers instance
    from nowplaying.datacache import get_providers

    providers = get_providers()
    await providers.initialize()

    # Cache an artist thumbnail (immediate)
    result = await providers.images.cache_artist_thumbnail(
        url="https://example.com/image.jpg",
        artist_identifier="daft_punk",
        provider="theaudiodb",
        immediate=True
    )

    # Queue background image fetch
    await providers.images.cache_artist_logo(
        url="https://example.com/logo.jpg",
        artist_identifier="daft_punk",
        provider="theaudiodb",
        immediate=False  # Queues for background processing
    )

    # Get random image (replaces imagecache.randomimage)
    random_thumb = await providers.images.get_random_image(
        artist_identifier="daft_punk",
        image_type="thumbnail"
    )

    # Cache API response
    bio_result = await providers.api.cache_artist_bio(
        url="https://api.example.com/artist/bio",
        artist_identifier="daft_punk",
        provider="example_api"
    )
"""

from __future__ import annotations

import logging

# Core components
from .client import DataCacheClient, get_client
from .providers import (
    APIProvider,
    DataCacheProviders,
    ImageProvider,
    MusicBrainzProvider,
    get_providers,
)
from .queue import RateLimiter, RateLimiterManager
from .storage import DataStorage, get_datacache_path, run_datacache_maintenance
from .workers import (
    DataCacheWorker,
    DataCacheWorkerManager,
    run_datacache_worker,
)

# Public API - these are the main interfaces artist extras plugins should use
__all__ = [
    # High-level interfaces (recommended for most use cases)
    "get_providers",  # Get DataCacheProviders instance
    "get_client",  # Get DataCacheClient instance
    # Provider classes (for direct instantiation if needed)
    "DataCacheProviders",  # Unified provider interface
    "MusicBrainzProvider",  # MusicBrainz API caching
    "ImageProvider",  # Image caching with randomimage support
    "APIProvider",  # Generic API response caching
    # Worker classes (for background processing)
    "DataCacheWorkerManager",  # Multi-worker manager
    "DataCacheWorker",  # Single worker
    "run_datacache_worker",  # Standalone worker function
    # Low-level components (for advanced use cases)
    "DataCacheClient",  # Core client with get_or_fetch
    "DataStorage",  # Direct storage layer access
    "RateLimiter",  # Rate limiting primitives
    "RateLimiterManager",  # Rate limiter management
    # Utility functions
    "get_datacache_path",  # Get database path
    "run_datacache_maintenance",  # Cleanup function for system startup
]

# Module-level convenience functions


async def initialize_datacache(cache_dir: str | None = None) -> DataCacheProviders:
    """
    Initialize the datacache system.

    This is a convenience function that initializes the global providers
    instance. Most applications will want to call this at startup.

    Args:
        cache_dir: Optional custom cache directory
    """
    providers = get_providers(cache_dir)
    await providers.initialize()
    return providers


async def shutdown_datacache() -> None:
    """
    Shutdown the datacache system.

    This should be called during application shutdown to cleanup
    resources and close database connections.
    """
    providers = get_providers()
    await providers.close()


def run_maintenance(cache_dir: str | None = None) -> dict[str, int]:
    """
    Run datacache maintenance tasks.

    This function runs cleanup operations and should be called
    at system startup, similar to imagecache maintenance.

    Args:
        cache_dir: Optional custom cache directory

    Returns:
        Dictionary with maintenance statistics
    """
    return run_datacache_maintenance(cache_dir)


# Migration helpers for transitioning from old systems
class LegacyImageCacheShim:
    """
    Compatibility shim for legacy imagecache.py usage.

    Provides a bridge to help migrate from old imagecache patterns
    to the new datacache system.
    """

    def __init__(self) -> None:
        self._providers: DataCacheProviders | None = None

    async def _ensure_providers(self) -> None:
        """Ensure providers are initialized"""
        if self._providers is None:
            self._providers = get_providers()
            await self._providers.initialize()

    async def randomimage(self, artist_identifier: str, image_type: str) -> bytes | None:
        """
        Legacy randomimage() compatibility method.

        Args:
            artist_identifier: Artist identifier
            image_type: Image type ("thumbnail", "logo", etc.)

        Returns:
            Random image data or None
        """
        await self._ensure_providers()
        result = await self._providers.images.get_random_image(
            artist_identifier=artist_identifier, image_type=image_type
        )
        if result:
            image_data, _metadata, _url = result
            return image_data
        return None

    @staticmethod
    def fill_queue(
        config: object, identifier: str, imagetype: str, srclocationlist: list[str] | None
    ) -> None:
        """
        Legacy fill_queue() compatibility method.

        Queues image URLs for background fetching.
        """
        # This would need to be called from an async context
        # For now, log the call - full implementation would require
        # running in an async context or using asyncio.create_task()
        del config  # Unused parameter

        logging.debug(
            "Legacy fill_queue called: identifier=%s, type=%s, urls=%d",
            identifier,
            imagetype,
            len(srclocationlist) if srclocationlist else 0,
        )


# Create legacy shim instance for backward compatibility
legacy_imagecache = LegacyImageCacheShim()


# Example integration patterns for artist extras plugins:
#
# Pattern 1: Simple immediate fetching
# async def download_async(self, metadata, imagecache=None):
#     providers = get_providers()
#     await providers.initialize()
#
#     artist_name = metadata.get("artist", "")
#     identifier = artist_name.lower().replace(" ", "_")
#
#     # Fetch bio immediately
#     bio_result = await providers.api.cache_artist_bio(
#         url=f"https://api.provider.com/{artist_name}/bio",
#         artist_identifier=identifier,
#         provider="provider_name",
#         immediate=True
#     )
#
#     if bio_result:
#         bio_data, _ = bio_result
#         metadata["artistlongbio"] = bio_data.get("text", "")
#
#     return metadata
#
# Pattern 2: Mixed immediate + background queuing
# async def download_async(self, metadata, imagecache=None):
#     providers = get_providers()
#     await providers.initialize()
#
#     artist_name = metadata.get("artist", "")
#     identifier = artist_name.lower().replace(" ", "_")
#
#     # Fetch critical data immediately
#     bio_result = await providers.api.cache_artist_bio(
#         url=f"https://api.provider.com/{artist_name}/bio",
#         artist_identifier=identifier,
#         provider="provider_name",
#         immediate=True
#     )
#
#     # Queue images for background (doesn't block track polling)
#     image_urls = get_image_urls(artist_name)
#     for url in image_urls:
#         await providers.images.cache_artist_thumbnail(
#             url=url,
#             artist_identifier=identifier,
#             provider="provider_name",
#             immediate=False  # Background queue
#         )
#
#     return metadata
#
# Pattern 3: Using randomimage functionality
# def get_artist_image(artist_name, image_type):
#     """Get random artist image (sync wrapper for UI)"""
#     import asyncio
#
#     async def _get_image():
#         providers = get_providers()
#         await providers.initialize()
#
#         identifier = artist_name.lower().replace(" ", "_")
#         result = await providers.images.get_random_image(
#             artist_identifier=identifier,
#             image_type=image_type
#         )
#         return result[0] if result else None
#
#     try:
#         loop = asyncio.get_event_loop()
#         return loop.run_until_complete(_get_image())
#     except RuntimeError:
#         # No event loop running, create new one
#         return asyncio.run(_get_image())
