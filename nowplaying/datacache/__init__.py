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

from pathlib import Path

# Core components
from .client import DataCacheClient, get_client
from .pending import RequestQueue
from .providers import (
    APIProvider,
    DataCacheProviders,
    ImageProvider,
    get_providers,
)
from .queue import RateLimiter, RateLimiterManager
from .storage import DataStorage, get_datacache_path, run_datacache_maintenance

# Public API - these are the main interfaces artist extras plugins should use
__all__ = [
    # High-level interfaces (recommended for most use cases)
    "get_providers",  # Get DataCacheProviders instance
    "get_client",  # Get DataCacheClient instance
    # Provider classes (for direct instantiation if needed)
    "DataCacheProviders",  # Unified provider interface
    "ImageProvider",  # Image caching with randomimage support
    "APIProvider",  # Generic API response caching
    # Low-level components (for advanced use cases)
    "DataCacheClient",  # Core client with get_or_fetch
    "DataStorage",  # Direct storage layer access
    "RequestQueue",  # Database-backed pending request queue
    "RateLimiter",  # Rate limiting primitives
    "RateLimiterManager",  # Rate limiter management
    # Utility functions
    "get_datacache_path",  # Get database path
    "run_datacache_maintenance",  # Cleanup function for system startup
]

# Module-level convenience functions


async def initialize_datacache(cache_dir: Path | None = None) -> DataCacheProviders:
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


def run_maintenance(cache_dir: Path | None = None) -> dict[str, int]:
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
