"""
High-level client interface for datacache operations.

Provides simple API for artist extras plugins to cache and retrieve data
without dealing with low-level storage details.
"""

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Any

import ssl

import httpx
import truststore
from httpx import Headers as CacheHeaders

import nowplaying.version  # pylint: disable=no-name-in-module,import-error

from .pending import RequestQueue
from .queue import RateLimiterManager
from .storage import IMAGE_DATA_TYPES, CachedEntry, DataStorage

_PROVIDER_TTL_DEFAULTS: dict[str, int] = {
    "theaudiodb": 7 * 24 * 3600,
    "discogs": 7 * 24 * 3600,
    "fanarttv": 30 * 24 * 3600,
    "wikimedia": 7 * 24 * 3600,
    "musicbrainz": 30 * 24 * 3600,
    "lastfm": 7 * 24 * 3600,
}
_IMAGE_DATA_TYPES = IMAGE_DATA_TYPES  # re-exported from storage for TTL doubling logic
_DEFAULT_TTL = 7 * 24 * 3600


def _backoff(attempt: int) -> float:
    """Exponential backoff with random jitter."""
    return (2**attempt) + random.uniform(0, 1.0)


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
        self.queue = RequestQueue(cache_dir)
        self.rate_limiters = RateLimiterManager()
        self._initialized = False
        self._session: httpx.AsyncClient | None = None
        self._init_lock = asyncio.Lock()
        self._retry_after_until: dict[str, float] = {}

    async def initialize(self) -> None:
        """Initialize the client and underlying storage (concurrency-safe)."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await self.storage.initialize()
            await self.queue.initialize()
            ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            self._session = httpx.AsyncClient(
                http2=True,
                verify=ssl_ctx,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        f"WhatIsNowPlaying/{nowplaying.version.__VERSION__} "  # pylint: disable=no-member
                        "(https://github.com/whatsnowplaying/whats-now-playing)"
                    )
                },
            )
            self._initialized = True

    async def close(self) -> None:
        """Close the client and cleanup resources"""
        self._initialized = False
        if self._session:
            await self._session.aclose()
            self._session = None
        await self.storage.close()

    async def get_or_fetch(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
        headers: CacheHeaders | None = None,
        negative_ttl: int | None = None,
        queue_priority: int = 2,
    ) -> CachedEntry | None:
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
            CachedEntry if found/fetched, None if failed or queued
        """
        await self.initialize()

        # Try to retrieve from cache first
        cached_result = await self.storage.retrieve_by_url(url)
        if cached_result:
            if cached_result.status_code != 200:
                logging.debug(
                    "Cache hit (negative, status=%d) for URL: %s", cached_result.status_code, url
                )
                return None
            logging.debug("Cache hit for URL: %s", url)
            return cached_result

        if not immediate:
            # Queue for background processing
            await self.queue.queue_request(
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
                priority=queue_priority,
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
            headers=headers,
            negative_ttl=negative_ttl,
        )

    async def _cache_negative(  # pylint: disable=too-many-arguments
        self,
        url: str,
        identifier: str,
        data_type: str,
        provider: str,
        ttl: int,
        metadata: dict | None,
    ) -> None:
        """Store b'' with status_code=404 and a short TTL for a definitive 404 response."""
        logging.debug("HTTP 404 for %s — caching negative result", url)
        try:
            await self.storage.store(
                url=url,
                identifier=identifier,
                data_type=data_type,
                provider=provider,
                data_value=b"",
                ttl_seconds=ttl,
                metadata=metadata,
                status_code=404,
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to cache 404 for %s: %s", url, err)

    def _in_cooldown(self, provider: str) -> bool:
        """Return True if provider is still in a server-side 429 back-off window."""
        until = self._retry_after_until.get(provider, 0.0)
        if time.monotonic() < until:
            remaining = int(until - time.monotonic())
            logging.warning("Provider %s in 429 cooldown, %ds remaining", provider, remaining)
            return True
        return False

    async def _fetch_and_store(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches,too-many-statements
        self,
        url: str,
        identifier: str,
        data_type: str,
        provider: str,
        timeout: float,
        retries: int,
        ttl_seconds: int | None,
        metadata: dict | None,
        headers: CacheHeaders | None = None,
        negative_ttl: int | None = None,
    ) -> CachedEntry | None:
        """
        Fetch data from URL and store in cache.

        Handles rate limiting and retries automatically.
        """
        if not self._session:
            raise RuntimeError("DataCacheClient not initialized - call initialize() first")

        # Honour server-side 429 cooldown recorded from a previous call
        if self._in_cooldown(provider):
            return None

        # Apply rate limiting
        rate_limiter = self.rate_limiters.get_limiter(provider)
        if not await rate_limiter.acquire():
            logging.warning(
                "Rate limit acquire timed out for provider %s, dropping request", provider
            )
            return None

        # Default TTL based on provider and data type
        if ttl_seconds is None:
            ttl_seconds = self._get_default_ttl(provider, data_type)

        # Fetch with retries
        for attempt in range(retries + 1):
            try:
                # self._session is guaranteed non-None after the check above
                response = await self._session.get(
                    url, timeout=httpx.Timeout(timeout), headers=headers
                )
                if response.status_code == 200:
                    data = response.content  # callers decode (e.g. orjson.loads) as needed

                    # Store in cache
                    success = await self.storage.store(
                        url=url,
                        identifier=identifier,
                        data_type=data_type,
                        provider=provider,
                        data_value=data,
                        ttl_seconds=ttl_seconds,
                        metadata=metadata,
                        status_code=200,
                    )

                    if success:
                        logging.debug("Cached data from URL: %s", url)
                    else:
                        logging.warning("Failed to cache data from URL: %s", url)
                    return CachedEntry(
                        data=data,
                        metadata=metadata or {},
                        status_code=200,
                        mime_type=None,
                        url=url,
                    )
                if response.status_code == 429:
                    try:
                        retry_after = max(1, int(response.headers.get("Retry-After", "60")))
                    except ValueError:
                        retry_after = 60
                    # Record cooldown so the next get_or_fetch call skips immediately
                    self._retry_after_until[provider] = time.monotonic() + retry_after
                    if attempt < retries:
                        logging.warning(
                            "Rate limited by %s, waiting %d seconds", provider, retry_after
                        )
                        await asyncio.sleep(retry_after)
                        # Re-acquire token after sleeping so local limiter stays in
                        # sync with the server's actual rate-limit window.
                        if not await rate_limiter.acquire():
                            return None
                        continue
                    logging.warning(
                        "Rate limited by %s on final attempt, cooldown %ds", provider, retry_after
                    )
                    break

                if response.status_code == 404 and negative_ttl is not None:
                    await self._cache_negative(
                        url, identifier, data_type, provider, negative_ttl, metadata
                    )
                    return None
                logging.warning("HTTP %d error fetching %s", response.status_code, url)
                if attempt < retries:
                    wait_time = _backoff(attempt)
                    await asyncio.sleep(wait_time)
                    continue
                break

            except httpx.TimeoutException:
                logging.warning(
                    "Timeout fetching URL (attempt %d/%d): %s", attempt + 1, retries + 1, url
                )
                if attempt < retries:
                    wait_time = _backoff(attempt)
                    await asyncio.sleep(wait_time)
                    continue
                break

            except Exception as error:  # pylint: disable=broad-except
                logging.error(
                    "Error fetching URL (attempt %d/%d): %s - %s",
                    attempt + 1,
                    retries + 1,
                    url,
                    error,
                )
                if attempt < retries:
                    wait_time = _backoff(attempt)
                    await asyncio.sleep(wait_time)
                    continue
                break

        return None

    @staticmethod
    def _get_default_ttl(provider: str, data_type: str) -> int:
        """Get default TTL based on provider and data type."""
        base = _PROVIDER_TTL_DEFAULTS.get(provider, _DEFAULT_TTL)
        return base * 2 if data_type in _IMAGE_DATA_TYPES else base

    async def get_random_image(
        self,
        identifier: str,
        data_type: str,
        provider: str | None = None,
    ) -> CachedEntry | None:
        """
        Get a random image for an identifier and type.

        This supports the randomimage() functionality from imagecache.

        Args:
            identifier: Artist identifier (e.g., "daft_punk")
            data_type: Image type ("thumbnail", "logo", "banner", "fanart")
            provider: Optional provider filter

        Returns:
            CachedEntry if found, None otherwise
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

    async def find_by_cachekey(self, cachekey: str) -> CachedEntry | None:
        """
        Retrieve cached data by its opaque UUID cachekey.

        Provides imagecache-compatible lookup for callers that hold a cachekey
        obtained from get_cache_keys_for_identifier.

        Args:
            cachekey: UUID string from get_cache_keys_for_identifier

        Returns:
            CachedEntry if found and not expired, None otherwise
        """
        await self.initialize()
        return await self.storage.retrieve_by_cachekey(cachekey)

    async def queue_url_fetch(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
        return await self.queue.queue_request(
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

    async def process_queue(
        self, provider: str | None = None, max_concurrent: int = 10
    ) -> dict[str, Any]:
        """
        Process pending requests from the queue concurrently.

        Drains the queue first (marking each item as 'processing'), then runs
        all fetches concurrently under a semaphore. Per-provider rate limiters
        in _fetch_and_store handle provider-level throttling automatically.

        Args:
            provider: Optional provider filter
            max_concurrent: Maximum number of simultaneous outbound connections

        Returns:
            Processing statistics
        """
        await self.initialize()

        async def _process_one(request: dict[str, Any]) -> bool:
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
                    success = result is not None
                else:
                    logging.warning("Unknown request key: %s", request["request_key"])
                    success = False

                await self.queue.complete_request(request_id, success=success)
                return success

            except Exception as error:  # pylint: disable=broad-except
                logging.error("Error processing request %s: %s", request_id, error)
                await self.queue.complete_request(request_id, success=False)
                return False

        stats: dict[str, Any] = {"processed": 0, "succeeded": 0, "failed": 0}

        # Pull round-robin batches (one per data_type at the current priority tier,
        # then fill remaining slots) so banners/logos/thumbnails all get one
        # download before any type gets its second.
        while True:
            if provider:
                # Provider-filtered path uses the old single-item query.
                chunk: list[dict[str, Any]] = []
                for _ in range(max_concurrent):
                    request = await self.queue.get_next_request(provider)
                    if not request:
                        break
                    chunk.append(request)
            else:
                chunk = await self.queue.get_next_batch(max_concurrent)

            if not chunk:
                break

            results = await asyncio.gather(*(_process_one(r) for r in chunk))
            stats["processed"] += len(chunk)
            stats["succeeded"] += sum(1 for r in results if r)
            stats["failed"] += sum(1 for r in results if not r)

        return stats


# Global client instance
_client_instance: DataCacheClient | None = None  # pylint: disable=invalid-name


def get_client(cache_dir: Path | None = None) -> DataCacheClient:
    """Get the global datacache client instance"""
    global _client_instance  # pylint: disable=global-statement
    if _client_instance is None:
        _client_instance = DataCacheClient(cache_dir)
    return _client_instance
