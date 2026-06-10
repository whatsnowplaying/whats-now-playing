"""DataCache - unified async caching for API responses and images."""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from httpx import Headers as CacheHeaders  # re-exported so callers don't import httpx directly

import orjson

# Core components
from .client import DataCacheClient, get_client, reset_client
from .utils import redact_url
from .pending import RequestQueue
from .queue import RateLimiter, RateLimiterManager
from .storage import CachedEntry, DataStorage, get_datacache_path, run_datacache_maintenance

# Public API
__all__ = [
    "get_client",  # Get DataCacheClient instance
    "DataCacheClient",  # Core client with get_or_fetch
    "CachedEntry",  # Result dataclass from retrieve methods
    "DataStorage",  # Direct storage layer access
    "RequestQueue",  # Database-backed pending request queue
    "RateLimiter",  # Rate limiting primitives
    "RateLimiterManager",  # Rate limiter management
    "get_datacache_path",  # Get database path
    "run_datacache_maintenance",  # Cleanup function for system startup
    "cached_fetch",  # Drop-in replacement for apicache.cached_fetch
    "set_shared_storage",  # Test isolation helper
    "redact_url",  # Sanitise URLs before logging (remove API keys)
    "reset_client",  # Reset DataCacheClient singleton (test fixtures)
    "reset_shared_storage",  # Reset singleton after DB move/delete
    "get_shared_storage",  # Access the storage singleton directly
    "CacheHeaders",  # httpx.Headers re-export — use for get_or_fetch() headers param
]


def run_maintenance(cache_dir: Path | None = None) -> dict[str, int]:
    """Run datacache maintenance tasks at system startup."""
    return run_datacache_maintenance(cache_dir)


# TTL defaults matching apicache.py provider settings (seconds)
_PROVIDER_TTL: dict[str, int] = {
    "discogs": 7 * 24 * 3600,
    "theaudiodb": 7 * 24 * 3600,
    "fanarttv": 7 * 24 * 3600,
    "lastfm": 7 * 24 * 3600,
    "wikimedia": 24 * 3600,
    "default": 24 * 3600,
}

_BYTES_KEY = "__bytes__"


def _serialize_default(obj: Any) -> Any:
    """orjson default handler: base64-encode raw bytes values inside dicts."""
    if isinstance(obj, bytes):
        return {_BYTES_KEY: base64.b64encode(obj).decode()}
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _deserialize_bytes(data: Any) -> Any:
    """Recursively restore base64-encoded bytes sentinels after orjson.loads."""
    if isinstance(data, dict):
        if len(data) == 1 and _BYTES_KEY in data:
            return base64.b64decode(data[_BYTES_KEY])
        return {k: _deserialize_bytes(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_deserialize_bytes(v) for v in data]
    return data


_shared_storage: DataStorage | None = None  # pylint: disable=invalid-name


def _get_shared_storage() -> DataStorage:
    global _shared_storage  # pylint: disable=global-statement
    if _shared_storage is None:
        _shared_storage = DataStorage()
    return _shared_storage


def set_shared_storage(storage: DataStorage | None) -> None:
    """Replace the module-level storage singleton. Used by tests for isolation."""
    global _shared_storage  # pylint: disable=global-statement
    _shared_storage = storage


def get_shared_storage() -> DataStorage:
    """Return the module-level storage singleton, creating it if needed."""
    return _get_shared_storage()


def reset_shared_storage() -> None:
    """Reset the module-level storage singleton to None.

    Call this after moving or deleting the underlying database file so the next
    access creates a fresh DataStorage pointing at the new location rather than
    trying to use the stale pre-move path.
    """
    global _shared_storage  # pylint: disable=global-statement
    _shared_storage = None


async def cached_fetch(  # pylint: disable=too-many-arguments
    provider: str,
    artist_name: str,
    endpoint: str,
    fetch_func: Callable[[], Awaitable[Any]],
    ttl_seconds: int | None = None,
    negative_ttl: int | None = None,
) -> Any | None:
    """Drop-in replacement for apicache.cached_fetch using datacache storage.

    Checks the local cache first; calls fetch_func() on a miss and stores the
    result. Returns None without caching when fetch_func() returns None so
    transient API failures (429, 5xx, timeout) do not poison the cache.

    negative_ttl: TTL for falsy-but-not-None results (e.g. {} meaning "not found
    in the upstream API").  When set, empty results are cached with this shorter
    TTL rather than the full ttl_seconds.  When None, falsy results are not cached.
    """
    storage = get_client().storage
    normalized = artist_name.lower().strip()
    url = f"apicache://{provider}/{normalized}/{endpoint}"

    cached = await storage.retrieve_by_url(url)
    if cached is not None:
        if cached.status_code != 200:
            logging.debug("Cache HIT (negative) for %s:%s:%s", provider, artist_name, endpoint)
            return None
        try:
            result = _deserialize_bytes(orjson.loads(cached.data))
            logging.debug("Cache HIT for %s:%s:%s", provider, artist_name, endpoint)
            return result
        except orjson.JSONDecodeError:
            logging.warning("corrupt cached entry for %s — treating as miss", url)

    logging.debug("Cache MISS for %s:%s:%s", provider, artist_name, endpoint)
    fresh = await fetch_func()
    if fresh:
        store_ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else _PROVIDER_TTL.get(provider, _PROVIDER_TTL["default"])
        )
    elif fresh is not None and negative_ttl is not None:
        # Falsy-but-not-None result (e.g. {} = not found) — cache with shorter TTL
        store_ttl = negative_ttl
    else:
        return fresh  # None = transient failure, do not cache
    try:
        # Negative results (empty/falsy from API) are stored with status_code=404
        # so the retrieval guard (status_code != 200) correctly suppresses retries.
        effective_status = 200 if fresh else 404
        await storage.store(
            url=url,
            identifier=normalized,
            data_type="api_response",
            provider=provider,
            data_value=orjson.dumps(fresh, default=_serialize_default),
            ttl_seconds=store_ttl,
            status_code=effective_status,
        )
    except Exception as err:  # pylint: disable=broad-exception-caught
        logging.warning("datacache store failed for %s: %s", url, err)
    return fresh
