"""
High-level client interface for datacache operations.

Provides simple API for artist extras plugins to cache and retrieve data
without dealing with low-level storage details.
"""

import asyncio
import dataclasses
import hashlib
import logging
import random
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import ssl

import httpx
import orjson
import truststore
from httpx import Headers as CacheHeaders

import nowplaying.version  # pylint: disable=no-name-in-module,import-error

from .pending import RequestQueue
from .queue import RateLimiterManager
from .storage import IMAGE_DATA_TYPES, CachedEntry, DataStorage
from .utils import redact_url

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


@dataclasses.dataclass
class FetchRequest:  # pylint: disable=too-many-instance-attributes
    """Parameters for a single get_or_fetch call."""

    url: str
    identifier: str
    data_type: str
    provider: str
    timeout: float = 30.0
    retries: int = 3
    ttl_seconds: int | None = None
    immediate: bool = True
    metadata: dict | None = None
    headers: CacheHeaders | None = None
    negative_ttl: int | None = None
    queue_priority: int = 2
    expected_checksum: str | None = None
    on_complete: Callable[[str, "CachedEntry | None"], Coroutine[Any, Any, None]] | None = None


_TERMINAL_HTTP_STATUSES: frozenset[int] = frozenset(range(400, 500)) - {429}


@dataclasses.dataclass
class FetchResult:
    """Result of a single _fetch_with_retry call."""

    data: bytes | None = None
    checksum: str | None = None
    status: int | None = None
    terminal: bool = False

    @property
    def ok(self) -> bool:
        """True only on a successful 200 response with data."""
        return self.status == 200 and self.data is not None


def _backoff(attempt: int) -> float:
    """Exponential backoff with random jitter."""
    return (2**attempt) + random.uniform(0, 1.0)


class DataCacheClient:  # pylint: disable=too-many-instance-attributes
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
        self._callbacks: dict[str, Callable] = {}

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

    async def get_or_fetch(self, request: FetchRequest) -> CachedEntry | None:
        """
        Get data from cache, or fetch from URL if not cached.

        Returns:
            CachedEntry if found/fetched, None if failed or queued
        """
        await self.initialize()

        cached_result = await self.storage.retrieve_by_url(request.url)
        if cached_result:
            if cached_result.status_code != 200:
                logging.debug(
                    "Cache hit (negative, status=%d) for URL: %s",
                    cached_result.status_code,
                    request.url,
                )
                return None
            if (
                request.expected_checksum is None
                or cached_result.checksum == request.expected_checksum
            ):
                logging.debug("Cache hit for URL: %s", self._redact_url(request.url))
                if request.on_complete:
                    asyncio.create_task(request.on_complete(request.url, cached_result))
                return cached_result
            logging.debug(
                "Cache hit checksum mismatch for URL: %s, re-fetching",
                self._redact_url(request.url),
            )

        if not request.immediate:
            params = {
                "url": request.url,
                "identifier": request.identifier,
                "data_type": request.data_type,
                "timeout": request.timeout,
                "retries": request.retries,
                "ttl_seconds": request.ttl_seconds,
                "metadata": request.metadata,
                "expected_checksum": request.expected_checksum,
            }
            params_str = orjson.dumps(params, option=orjson.OPT_SORT_KEYS).decode()
            digest = hashlib.sha256(params_str.encode()).hexdigest()[:16]
            request_id = f"{request.provider}:fetch_url:{digest}"
            if request.on_complete:
                self._callbacks[request_id] = request.on_complete
            await self.queue.queue_request(
                provider=request.provider,
                request_key="fetch_url",
                params=params,
                priority=request.queue_priority,
            )
            logging.debug("Queued background fetch for URL: %s", self._redact_url(request.url))
            return None

        return await self._fetch_and_store(
            url=request.url,
            identifier=request.identifier,
            data_type=request.data_type,
            provider=request.provider,
            timeout=request.timeout,
            retries=request.retries,
            ttl_seconds=request.ttl_seconds,
            metadata=request.metadata,
            headers=request.headers,
            negative_ttl=request.negative_ttl,
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
        logging.debug("HTTP 404 for %s — caching negative result", self._redact_url(url))
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
            logging.warning("Failed to cache 404 for %s: %s", self._redact_url(url), err)

    @staticmethod
    def _redact_url(url: str) -> str:
        return redact_url(url)

    def in_cooldown(self, provider: str) -> bool:
        """Return True if provider is still in a server-side 429 back-off window."""
        until = self._retry_after_until.get(provider, 0.0)
        if time.monotonic() < until:
            remaining = int(until - time.monotonic())
            logging.warning("Provider %s in 429 cooldown, %ds remaining", provider, remaining)
            return True
        return False

    def set_retry_after(self, provider: str, seconds: float) -> None:
        """Record a server-requested retry-after delay for a provider.

        Called by plugins that make their own HTTP requests (e.g. Last.fm)
        when they receive a 429 response, so all callers share the same
        cooldown state.
        """
        self._retry_after_until[provider] = time.monotonic() + seconds

    def clear_retry_after(self, provider: str) -> None:
        """Clear any active cooldown for a provider, allowing immediate retries.

        Useful in tests to reset cooldown state between scenarios.
        """
        self._retry_after_until.pop(provider, None)

    @staticmethod
    async def _stream_body(response: httpx.Response) -> tuple[bytes, str]:
        """Stream response body, returning (data, sha256_hex)."""
        h = hashlib.sha256()
        chunks: list[bytes] = []
        async for chunk in response.aiter_bytes(65536):
            h.update(chunk)
            chunks.append(chunk)
        return b"".join(chunks), h.hexdigest()

    async def _handle_429(  # pylint: disable=too-many-arguments
        self,
        response: httpx.Response,
        provider: str,
        attempt: int,
        retries: int,
        rate_limiter: Any,
    ) -> bool:
        """Record 429 cooldown and sleep if retries remain.

        Returns True to retry, False to give up.
        """
        try:
            retry_after = max(1, int(response.headers.get("Retry-After", "60")))
        except ValueError:
            retry_after = 60
        self._retry_after_until[provider] = time.monotonic() + retry_after
        if attempt < retries:
            logging.warning("Rate limited by %s, waiting %d seconds", provider, retry_after)
            await asyncio.sleep(retry_after)
            return await rate_limiter.acquire()
        logging.warning("Rate limited by %s on final attempt, cooldown %ds", provider, retry_after)
        return False

    async def _fetch_with_retry(  # pylint: disable=too-many-arguments
        self,
        url: str,
        provider: str,
        timeout: float,
        retries: int,
        headers: CacheHeaders | None,
        rate_limiter: Any,
    ) -> FetchResult:
        """Stream-fetch url with retries.

        4xx responses (except 429) are terminal — returned immediately without
        consuming retry budget.  5xx and network errors are retried with
        exponential backoff.
        """
        last_result = FetchResult()
        for attempt in range(retries + 1):
            try:
                async with self._session.stream(  # type: ignore[union-attr]
                    "GET", url, timeout=httpx.Timeout(timeout), headers=headers
                ) as response:
                    if response.status_code == 200:
                        data, checksum = await self._stream_body(response)
                        return FetchResult(data=data, checksum=checksum, status=200)
                    if response.status_code == 429:
                        should_continue = await self._handle_429(
                            response, provider, attempt, retries, rate_limiter
                        )
                        if should_continue:
                            continue
                        return FetchResult(status=429, terminal=False)
                    if response.status_code in _TERMINAL_HTTP_STATUSES:
                        logging.warning(
                            "HTTP %d fetching %s (terminal)",
                            response.status_code,
                            self._redact_url(url),
                        )
                        return FetchResult(status=response.status_code, terminal=True)
                    logging.warning(
                        "HTTP %d fetching %s", response.status_code, self._redact_url(url)
                    )
                    last_result = FetchResult(status=response.status_code, terminal=False)
            except httpx.TimeoutException:
                logging.warning(
                    "Timeout fetching URL (attempt %d/%d): %s",
                    attempt + 1,
                    retries + 1,
                    self._redact_url(url),
                )
            except Exception as error:  # pylint: disable=broad-except
                logging.error(
                    "Error fetching URL (attempt %d/%d): %s - %s",
                    attempt + 1,
                    retries + 1,
                    self._redact_url(url),
                    error,
                )
            if attempt < retries:
                await asyncio.sleep(_backoff(attempt))
        return last_result

    async def _fetch_and_store(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
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
        if not self._session:
            raise RuntimeError("DataCacheClient not initialized - call initialize() first")

        if self.in_cooldown(provider):
            return None

        rate_limiter = self.rate_limiters.get_limiter(provider)
        if not await rate_limiter.acquire():
            logging.warning(
                "Rate limit acquire timed out for provider %s, dropping request", provider
            )
            return None

        if ttl_seconds is None:
            ttl_seconds = self._get_default_ttl(provider, data_type)

        result = await self._fetch_with_retry(
            url, provider, timeout, retries, headers, rate_limiter
        )
        if not result.ok:
            if result.terminal and result.status == 404 and negative_ttl is not None:
                await self._cache_negative(
                    url, identifier, data_type, provider, negative_ttl, metadata
                )
            return None

        data, content_checksum = result.data, result.checksum  # type: ignore[assignment]
        success = await self.storage.store(
            url=url,
            identifier=identifier,
            data_type=data_type,
            provider=provider,
            data_value=data,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
            status_code=200,
            checksum=content_checksum,
        )
        if success:
            logging.debug("Cached data from URL: %s", self._redact_url(url))
        else:
            logging.warning("Failed to cache data from URL: %s", self._redact_url(url))
        return CachedEntry(
            data=data,
            metadata=metadata or {},
            status_code=200,
            mime_type=None,
            url=url,
            checksum=content_checksum,
        )

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

                if request_id in self._callbacks:
                    cb = self._callbacks.pop(request_id)
                    url = request["params"]["url"]
                    entry = await self.storage.retrieve_by_url(url) if success else None
                    asyncio.create_task(cb(url, entry))

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


def reset_client() -> None:
    """Reset the global client singleton.

    Forces the next get_client() call to create a fresh DataCacheClient,
    binding its httpx session to the current event loop.  Call this from
    test fixtures after the event loop or database path may have changed.

    Nulls out the httpx session before dropping the instance so that
    Windows's ProactorEventLoop does not emit ResourceWarning about
    unclosed transports — the connections are abandoned rather than
    cleanly closed, which is acceptable in test fixtures that run
    synchronously.
    """
    global _client_instance  # pylint: disable=global-statement
    if _client_instance is not None:
        _client_instance._session = None  # pylint: disable=protected-access
        _client_instance._initialized = False  # pylint: disable=protected-access
    _client_instance = None
