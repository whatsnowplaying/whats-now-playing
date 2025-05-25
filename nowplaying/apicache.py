#!/usr/bin/env python3
"""
API Response Caching Layer

Provides fast caching for artist metadata API responses to significantly reduce
lookup times for frequently requested artists during live DJ performances.
"""

import asyncio
import hashlib
import json
import logging
import pathlib
import sqlite3
import time
import typing as t
from contextlib import asynccontextmanager

import aiosqlite
from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module


class APIResponseCache:
    """Fast SQLite-based cache for API responses with TTL support."""

    CACHE_VERSION = 1

    # Cache TTL settings (in seconds)
    DEFAULT_TTL = {
        'discogs': 24 * 60 * 60,  # 24 hours for artist info
        'theaudiodb': 7 * 24 * 60 * 60,  # 7 days for artist bios
        'fanarttv': 7 * 24 * 60 * 60,  # 7 days for fanart URLs
        'wikimedia': 24 * 60 * 60,  # 24 hours for wiki info
        'default': 6 * 60 * 60  # 6 hours default
    }

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS api_responses (
        cache_key TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        artist_name TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        response_data TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        access_count INTEGER DEFAULT 1,
        last_accessed INTEGER NOT NULL
    );
    """

    # Index for performance
    CREATE_INDICES_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_provider_artist ON api_responses(provider, artist_name);",
        "CREATE INDEX IF NOT EXISTS idx_expires_at ON api_responses(expires_at);",
        "CREATE INDEX IF NOT EXISTS idx_last_accessed ON api_responses(last_accessed);"
    ]

    def __init__(self, cache_dir: t.Optional[pathlib.Path] = None):
        """Initialize the API cache.
        
        Args:
            cache_dir: Optional custom cache directory. If None, uses Qt standard cache location.
        """
        if cache_dir:
            self.cache_dir = pathlib.Path(cache_dir)
        else:
            self.cache_dir = pathlib.Path(
                QStandardPaths.standardLocations(
                    QStandardPaths.StandardLocation.CacheLocation)[0]).joinpath('api_cache')

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_file = self.cache_dir / 'api_responses.db'
        self._lock = asyncio.Lock()

        # Initialize database if needed
        asyncio.create_task(self._initialize_db())

    async def _initialize_db(self):
        """Initialize the database schema."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(self.CREATE_TABLE_SQL)
            for index_sql in self.CREATE_INDICES_SQL:
                await db.execute(index_sql)
            await db.commit()
            logging.debug("API cache database initialized at %s", self.db_file)

    def _make_cache_key(self,
                        provider: str,
                        artist_name: str,
                        endpoint: str,
                        params: t.Optional[dict] = None) -> str:
        """Generate a cache key for the request.
        
        Args:
            provider: API provider name (e.g., 'discogs', 'theaudiodb')
            artist_name: Artist name being queried
            endpoint: API endpoint or operation type
            params: Optional additional parameters that affect the response
            
        Returns:
            SHA256 hash to use as cache key
        """
        # Normalize artist name for consistent caching
        normalized_artist = artist_name.lower().strip()

        # Create deterministic string for hashing
        cache_data = {
            'provider': provider.lower(),
            'artist': normalized_artist,
            'endpoint': endpoint,
            'params': params or {}
        }

        cache_string = json.dumps(cache_data, sort_keys=True)
        return hashlib.sha256(cache_string.encode('utf-8')).hexdigest()

    def _serialize_handler(self, obj):
        """Handle non-JSON serializable objects during caching.
        
        Args:
            obj: Object that failed standard JSON serialization
            
        Returns:
            JSON-serializable representation
        """
        if isinstance(obj, bytes):
            # Encode bytes as base64 for proper round-trip serialization
            import base64
            return {
                '__type__': 'bytes',
                '__data__': base64.b64encode(obj).decode('ascii')
            }
        else:
            # For other types, convert to string representation
            return str(obj)

    def _deserialize_handler(self, obj):
        """Restore objects that were specially serialized during caching.
        
        Args:
            obj: Cached object to process
            
        Returns:
            Object with restored types (e.g., base64 -> bytes)
        """
        if isinstance(obj, dict):
            # Check if this is a specially encoded bytes object
            if obj.get('__type__') == 'bytes' and '__data__' in obj:
                import base64
                return base64.b64decode(obj['__data__'])
            else:
                # Recursively process dictionary values
                return {key: self._deserialize_handler(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            # Recursively process list items
            return [self._deserialize_handler(item) for item in obj]
        else:
            # Return as-is for other types
            return obj

    async def get(self,
                  provider: str,
                  artist_name: str,
                  endpoint: str,
                  params: t.Optional[dict] = None) -> t.Optional[dict]:
        """Retrieve cached API response if available and not expired.
        
        Args:
            provider: API provider name
            artist_name: Artist name being queried  
            endpoint: API endpoint or operation type
            params: Optional additional parameters
            
        Returns:
            Cached response data or None if not found/expired
        """
        cache_key = self._make_cache_key(provider, artist_name, endpoint, params)
        current_time = int(time.time())

        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_file) as db:
                    cursor = await db.execute(
                        "SELECT response_data, expires_at, access_count FROM api_responses "
                        "WHERE cache_key = ? AND expires_at > ?", (cache_key, current_time))
                    row = await cursor.fetchone()

                    if row:
                        response_data, expires_at, access_count = row

                        # Update access statistics
                        await db.execute(
                            "UPDATE api_responses SET access_count = ?, last_accessed = ? "
                            "WHERE cache_key = ?", (access_count + 1, current_time, cache_key))
                        await db.commit()

                        try:
                            cached_data = json.loads(response_data)
                            # Restore any bytes data that was base64 encoded
                            restored_data = self._deserialize_handler(cached_data)
                            logging.debug("Cache HIT for %s:%s:%s (expires in %ds)", provider,
                                          artist_name, endpoint, expires_at - current_time)
                            return restored_data
                        except json.JSONDecodeError:
                            logging.warning("Invalid JSON in cache for key %s", cache_key)

            except sqlite3.Error as e:
                logging.error("Database error retrieving cache: %s", e)

        logging.debug("Cache MISS for %s:%s:%s", provider, artist_name, endpoint)
        return None

    async def put(self,
                  provider: str,
                  artist_name: str,
                  endpoint: str,
                  response_data: dict,
                  ttl_seconds: t.Optional[int] = None,
                  params: t.Optional[dict] = None):
        """Store API response in cache.
        
        Args:
            provider: API provider name
            artist_name: Artist name being queried
            endpoint: API endpoint or operation type  
            response_data: Response data to cache
            ttl_seconds: Time to live in seconds. If None, uses provider default.
            params: Optional additional parameters
        """
        if not response_data:
            return

        cache_key = self._make_cache_key(provider, artist_name, endpoint, params)
        current_time = int(time.time())

        if ttl_seconds is None:
            ttl_seconds = self.DEFAULT_TTL.get(provider.lower(), self.DEFAULT_TTL['default'])

        expires_at = current_time + ttl_seconds

        try:
            response_json = json.dumps(response_data, ensure_ascii=False, default=self._serialize_handler)
        except (TypeError, ValueError) as e:
            logging.warning("Cannot serialize response data for caching: %s", e)
            return

        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_file) as db:
                    await db.execute(
                        "INSERT OR REPLACE INTO api_responses "
                        "(cache_key, provider, artist_name, endpoint, response_data, "
                        "created_at, expires_at, last_accessed) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (cache_key, provider.lower(), artist_name.lower().strip(), endpoint,
                         response_json, current_time, expires_at, current_time))
                    await db.commit()
                    logging.debug("Cached %s:%s:%s (TTL: %ds)", provider, artist_name, endpoint,
                                  ttl_seconds)

            except sqlite3.Error as e:
                logging.error("Database error storing cache: %s", e)

    @asynccontextmanager
    async def get_or_fetch(self,
                           provider: str,
                           artist_name: str,
                           endpoint: str,
                           fetch_func: t.Callable[[], t.Awaitable[dict]],
                           ttl_seconds: t.Optional[int] = None,
                           params: t.Optional[dict] = None):
        """Get from cache or fetch and cache the result.
        
        This is a convenience method that handles the common pattern of 
        checking cache first, and if not found, calling the fetch function
        and caching the result.
        
        Args:
            provider: API provider name
            artist_name: Artist name being queried
            endpoint: API endpoint or operation type
            fetch_func: Async function to call if cache miss
            ttl_seconds: Time to live in seconds
            params: Optional additional parameters
            
        Yields:
            The cached or fetched response data
        """
        # Try cache first
        cached_data = await self.get(provider, artist_name, endpoint, params)
        if cached_data is not None:
            yield cached_data
            return

        # Cache miss - fetch fresh data
        try:
            fresh_data = await fetch_func()
            if fresh_data:
                # Cache the result
                await self.put(provider, artist_name, endpoint, fresh_data, ttl_seconds, params)
            yield fresh_data
        except Exception as e:
            logging.error("Error fetching data for %s:%s:%s - %s", provider, artist_name, endpoint,
                          e)
            yield None

    async def cleanup_expired(self) -> int:
        """Remove expired cache entries.
        
        Returns:
            Number of entries removed
        """
        current_time = int(time.time())

        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_file) as db:
                    cursor = await db.execute("DELETE FROM api_responses WHERE expires_at < ?",
                                              (current_time, ))
                    removed_count = cursor.rowcount
                    await db.commit()

                    if removed_count > 0:
                        logging.info("Cleaned up %d expired cache entries", removed_count)

                    return removed_count

            except sqlite3.Error as e:
                logging.error("Database error during cleanup: %s", e)
                return 0

    async def get_cache_stats(self) -> dict:
        """Get cache usage statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        current_time = int(time.time())

        try:
            async with aiosqlite.connect(self.db_file) as db:
                # Total entries
                cursor = await db.execute("SELECT COUNT(*) FROM api_responses")
                result = await cursor.fetchone()
                total_entries = result[0] if result else 0

                # Valid (non-expired) entries
                cursor = await db.execute("SELECT COUNT(*) FROM api_responses WHERE expires_at > ?",
                                          (current_time, ))
                result = await cursor.fetchone()
                valid_entries = result[0] if result else 0

                # Entries by provider
                cursor = await db.execute(
                    "SELECT provider, COUNT(*) FROM api_responses "
                    "WHERE expires_at > ? GROUP BY provider", (current_time, ))
                provider_rows = await cursor.fetchall()
                by_provider = {provider: count for provider, count in provider_rows}

                # Most accessed artists
                cursor = await db.execute(
                    "SELECT artist_name, SUM(access_count) as total_accesses "
                    "FROM api_responses WHERE expires_at > ? "
                    "GROUP BY artist_name ORDER BY total_accesses DESC LIMIT 10", (current_time, ))
                top_artists = list(await cursor.fetchall())

                return {
                    'total_entries': total_entries,
                    'valid_entries': valid_entries,
                    'expired_entries': total_entries - valid_entries,
                    'by_provider': by_provider,
                    'top_artists': top_artists,
                    'cache_hit_potential': f"{(valid_entries / max(total_entries, 1)) * 100:.1f}%"
                }

        except sqlite3.Error as e:
            logging.error("Database error getting stats: %s", e)
            return {}

    async def clear_cache(self, provider: t.Optional[str] = None):
        """Clear cache entries.
        
        Args:
            provider: If specified, only clear entries for this provider.
                     If None, clear all entries.
        """
        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_file) as db:
                    if provider:
                        await db.execute("DELETE FROM api_responses WHERE provider = ?",
                                         (provider.lower(), ))
                        logging.info("Cleared cache for provider: %s", provider)
                    else:
                        await db.execute("DELETE FROM api_responses")
                        logging.info("Cleared entire API response cache")
                    await db.commit()

            except sqlite3.Error as e:
                logging.error("Database error clearing cache: %s", e)


# Global cache instance for use across the application
_global_cache_instance: t.Optional[APIResponseCache] = None


def get_cache() -> APIResponseCache:
    """Get the global cache instance, creating it if needed."""
    global _global_cache_instance
    if _global_cache_instance is None:
        _global_cache_instance = APIResponseCache()
    return _global_cache_instance


def set_cache_instance(cache: APIResponseCache):
    """Set a custom global cache instance (useful for testing)."""
    global _global_cache_instance
    _global_cache_instance = cache
