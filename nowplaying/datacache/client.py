"""
High-level client interface for datacache operations.

Provides simple API for artist extras plugins to cache and retrieve data
without dealing with low-level storage details.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import aiohttp
import aiohttp_client_cache

from .queue import RateLimiterManager
from .storage import DataStorage


class DataCacheClient:
    """
    High-level client for datacache operations.

    Simplifies caching for artist extras plugins by handling:
    - URL-based storage and retrieval
    - Automatic rate limiting per provider
    - TTL management
    - Priority handling (immediate vs batch)
    """

    def __init__(self, cache_dir: Path | None = None):
        self.storage = DataStorage(cache_dir)
        self.rate_limiters = RateLimiterManager()
        self._initialized = False
        self._session: aiohttp_client_cache.CachedSession | None = None

    async def initialize(self) -> None:
        """Initialize the client and underlying storage"""
        if not self._initialized:
            await self.storage.initialize()

            # Create HTTP cache in same directory as datacache for PyInstaller compatibility
            http_cache_path = self.storage.database_path.parent / "datacache_http.sqlite"

            # Create cached session for HTTP requests
            self._session = aiohttp_client_cache.CachedSession(
                cache=aiohttp_client_cache.SQLiteBackend(
                    cache_name=str(http_cache_path.with_suffix("")),  # Remove .sqlite extension
                    expire_after=3600,  # 1 hour default
                )
            )
            self._initialized = True

    async def close(self) -> None:
        """Close the client and cleanup resources"""
        if self._session:
            await self._session.close()
            self._session = None
        await self.storage.close()

    async def get_or_fetch(  # pylint: disable=too-many-arguments
        self,
        url: str,
        identifier: str,
        data_type: str,
        provider: str,
        timeout: float = 30.0,
        retries: int = 3,
        ttl_seconds: int | None = None,
        immediate: bool = True,
        metadata: dict | None = None,
    ) -> tuple[Any, dict] | None:
        """
        Get data from cache, or fetch from URL if not cached.

        Args:
            url: The URL to fetch data from
            identifier: Artist identifier (e.g., "daft_punk")
            data_type: Type of data ("thumbnail", "logo", "bio", etc.)
            provider: Provider name ("theaudiodb", "discogs", etc.)
            timeout: Request timeout in seconds
            retries: Number of retry attempts
            ttl_seconds: Cache TTL in seconds (None for provider default)
            immediate: If True, fetch immediately; if False, queue for later
            metadata: Optional metadata to store with cached item

        Returns:
            Tuple of (data, metadata) if found/fetched, None if failed
        """
        await self.initialize()

        # Try to retrieve from cache first
        cached_result = await self.storage.retrieve_by_url(url)
        if cached_result:
            logging.debug("Cache hit for URL: %s", url)
            return cached_result

        if not immediate:
            # Queue for background processing
            await self.storage.queue_request(
                provider=provider,
                request_key="fetch_url",
                params={
                    "url": url,
                    "identifier": identifier,
                    "data_type": data_type,
                    "timeout": timeout,
                    "retries": retries,
                    "ttl_seconds": ttl_seconds,
                    "metadata": metadata,
                },
                priority=2,  # batch priority
            )
            logging.debug("Queued background fetch for URL: %s", url)
            return None

        # Immediate fetch
        return await self._fetch_and_store(
            url=url,
            identifier=identifier,
            data_type=data_type,
            provider=provider,
            timeout=timeout,
            retries=retries,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
        )

    async def _fetch_and_store(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches
        self,
        url: str,
        identifier: str,
        data_type: str,
        provider: str,
        timeout: float,
        retries: int,
        ttl_seconds: int | None,
        metadata: dict | None,
    ) -> tuple[Any, dict] | None:
        """
        Fetch data from URL and store in cache.

        Handles rate limiting and retries automatically.
        """
        # Apply rate limiting
        rate_limiter = self.rate_limiters.get_limiter(provider)
        await rate_limiter.acquire()

        if not self._session:
            raise RuntimeError("DataCacheClient not initialized - call initialize() first")

        # Default TTL based on provider and data type
        if ttl_seconds is None:
            ttl_seconds = self._get_default_ttl(provider, data_type)

        # Fetch with retries
        for attempt in range(retries + 1):
            try:
                # Type checker: self._session is guaranteed non-None after the check above
                async with self._session.get(  # pylint: disable=not-async-context-manager
                    url, timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status == 200:
                        # Determine data format based on content type
                        content_type = response.headers.get("content-type", "").lower()

                        if content_type.startswith("application/json"):
                            data = await response.json()
                        elif content_type.startswith(("image/", "audio/", "video/")):
                            data = await response.read()  # Binary data
                        else:
                            data = await response.text()  # Text data

                        # Store in cache
                        success = await self.storage.store(
                            url=url,
                            identifier=identifier,
                            data_type=data_type,
                            provider=provider,
                            data_value=data,
                            ttl_seconds=ttl_seconds,
                            metadata=metadata,
                        )

                        if success:
                            logging.debug("Cached data from URL: %s", url)
                        else:
                            logging.warning("Failed to cache data from URL: %s", url)
                        return data, metadata or {}
                    if response.status == 429:
                        # Rate limit - wait and retry
                        retry_after = int(response.headers.get("Retry-After", 60))
                        logging.warning(
                            "Rate limited by %s, waiting %d seconds", provider, retry_after
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    logging.warning("HTTP %d error fetching %s", response.status, url)
                    if attempt < retries:
                        wait_time = (2**attempt) + (
                            time.time() % 1
                        )  # Exponential backoff with jitter
                        await asyncio.sleep(wait_time)
                        continue
                    return None

            except asyncio.TimeoutError:
                logging.warning(
                    "Timeout fetching URL (attempt %d/%d): %s", attempt + 1, retries + 1, url
                )
                if attempt < retries:
                    wait_time = (2**attempt) + (time.time() % 1)
                    await asyncio.sleep(wait_time)
                    continue
                return None

            except Exception as error:  # pylint: disable=broad-except
                logging.error(
                    "Error fetching URL (attempt %d/%d): %s - %s",
                    attempt + 1,
                    retries + 1,
                    url,
                    error,
                )
                if attempt < retries:
                    wait_time = (2**attempt) + (time.time() % 1)
                    await asyncio.sleep(wait_time)
                    continue
                return None

        return None

    def _get_default_ttl(self, provider: str, data_type: str) -> int:  # pylint: disable=no-self-use
        """Get default TTL based on provider and data type"""
        # Provider-specific defaults (in seconds)
        provider_defaults = {
            "theaudiodb": 7 * 24 * 3600,  # 1 week
            "discogs": 7 * 24 * 3600,  # 1 week
            "fanarttv": 30 * 24 * 3600,  # 1 month
            "wikimedia": 7 * 24 * 3600,  # 1 week
            "musicbrainz": 30 * 24 * 3600,  # 1 month
        }

        # Data type modifiers
        if data_type in {"thumbnail", "logo", "banner", "fanart"}:
            # Images change less frequently
            return provider_defaults.get(provider, 7 * 24 * 3600) * 2
        # Text data may update more frequently
        return provider_defaults.get(provider, 7 * 24 * 3600)

    async def get_random_image(
        self,
        identifier: str,
        data_type: str,
        provider: str | None = None,
    ) -> tuple[Any, dict, str] | None:
        """
        Get a random image for an identifier and type.

        This supports the randomimage() functionality from imagecache.

        Args:
            identifier: Artist identifier (e.g., "daft_punk")
            data_type: Image type ("thumbnail", "logo", "banner", "fanart")
            provider: Optional provider filter

        Returns:
            Tuple of (image_data, metadata, url) if found, None otherwise
        """
        await self.initialize()
        return await self.storage.retrieve_by_identifier(
            identifier=identifier, data_type=data_type, provider=provider, random=True
        )

    async def get_cache_keys_for_identifier(
        self,
        identifier: str,
        data_type: str,
        provider: str | None = None,
    ) -> list[str]:
        """
        Get cache keys for an identifier and type.

        Compatible with imagecache.get_cache_keys_for_identifier() for WebSocket interface.
        Returns cache key strings that can be used to reference specific cached items.

        Args:
            identifier: Artist identifier (e.g., "daft_punk")
            data_type: Image type ("thumbnail", "logo", "banner", "fanart")
            provider: Optional provider filter

        Returns:
            List of cache key strings
        """
        await self.initialize()
        return await self.storage.get_cache_keys_for_identifier(
            identifier=identifier, data_type=data_type, provider=provider
        )

    async def queue_url_fetch(  # pylint: disable=too-many-arguments
        self,
        url: str,
        identifier: str,
        data_type: str,
        provider: str,
        timeout: float = 30.0,
        retries: int = 3,
        ttl_seconds: int | None = None,
        priority: int = 2,
        metadata: dict | None = None,
    ) -> bool:
        """
        Queue a URL fetch for background processing.

        Args:
            url: The URL to fetch
            identifier: Artist identifier
            data_type: Type of data
            provider: Provider name
            timeout: Request timeout
            retries: Retry attempts
            ttl_seconds: Cache TTL
            priority: Request priority (1=immediate, 2=batch)
            metadata: Optional metadata

        Returns:
            True if queued successfully
        """
        await self.initialize()
        return await self.storage.queue_request(
            provider=provider,
            request_key="fetch_url",
            params={
                "url": url,
                "identifier": identifier,
                "data_type": data_type,
                "timeout": timeout,
                "retries": retries,
                "ttl_seconds": ttl_seconds,
                "metadata": metadata,
            },
            priority=priority,
        )

    async def process_queue(self, provider: str | None = None) -> dict[str, Any]:
        """
        Process pending requests from the queue.

        Args:
            provider: Optional provider filter

        Returns:
            Processing statistics
        """
        await self.initialize()

        stats = {"processed": 0, "succeeded": 0, "failed": 0}

        while True:
            # Get next request
            request = await self.storage.get_next_request(provider)
            if not request:
                break

            stats["processed"] += 1
            request_id = request["request_id"]

            try:
                if request["request_key"] == "fetch_url":
                    params = request["params"]
                    result = await self._fetch_and_store(
                        url=params["url"],
                        identifier=params["identifier"],
                        data_type=params["data_type"],
                        provider=request["provider"],
                        timeout=params.get("timeout", 30.0),
                        retries=params.get("retries", 3),
                        ttl_seconds=params.get("ttl_seconds"),
                        metadata=params.get("metadata"),
                    )

                    if result:
                        await self.storage.complete_request(request_id, success=True)
                        stats["succeeded"] += 1
                    else:
                        await self.storage.complete_request(request_id, success=False)
                        stats["failed"] += 1
                else:
                    logging.warning("Unknown request key: %s", request["request_key"])
                    await self.storage.complete_request(request_id, success=False)
                    stats["failed"] += 1

            except Exception as error:  # pylint: disable=broad-except
                logging.error("Error processing request %s: %s", request_id, error)
                await self.storage.complete_request(request_id, success=False)
                stats["failed"] += 1

        return stats


# Global client instance
_client_instance: DataCacheClient | None = None


def get_client(cache_dir: Path | None = None) -> DataCacheClient:
    """Get the global datacache client instance"""
    global _client_instance  # pylint: disable=global-statement
    if _client_instance is None:
        _client_instance = DataCacheClient(cache_dir)
    return _client_instance
