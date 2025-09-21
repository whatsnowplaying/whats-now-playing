"""
Generic storage layer for datacache module.

Provides unified storage for different data types:
- JSON/structured data
- Binary data (images, etc.)
- Metadata and cache control information

Built on aiosqlite for async operations and better performance.
Uses URL-based keys following imagecache pattern for randomimage support.
"""

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

import aiosqlite
from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

# Module-level lock for schema operations
_schema_lock = asyncio.Lock()


def _generate_cache_key(identifier: str, data_type: str, provider: str, url: str) -> str:
    """
    Generate a stable cache key for WebSocket interface compatibility.

    Similar to imagecache cache keys but based on URL hash to ensure uniqueness.
    """
    # Create a hash from url to ensure uniqueness while keeping it stable
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
    return f"{identifier}_{data_type}_{provider}_{url_hash}"


class DataStorage:
    """
    Async storage layer for cached data.

    Handles all data types uniformly with proper TTL management
    and automatic expired item cleanup. Uses URL-based primary keys
    following imagecache pattern.
    """

    def __init__(self, database_path: Path | None = None):
        self.database_path = get_datacache_path(database_path)
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the database schema"""
        async with self._lock:
            if not self._initialized:
                # Ensure parent directory exists
                self.database_path.parent.mkdir(parents=True, exist_ok=True)

                # Create schema using temporary connection
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    # Enable WAL mode for better concurrent access
                    await connection.execute("PRAGMA journal_mode=WAL")
                    await connection.execute("PRAGMA synchronous=NORMAL")
                    await connection.execute("PRAGMA cache_size=10000")

                    await self._create_schema()

                self._initialized = True

    async def _create_schema(self) -> None:
        """Create the database schema using sync method with lock"""
        async with _schema_lock:
            # Use the sync schema creation to avoid duplication
            _ensure_datacache_schema(self.database_path)

    async def store(  # pylint: disable=too-many-arguments
        self,
        url: str,
        identifier: str,
        data_type: str,
        provider: str,
        data_value: Any,
        ttl_seconds: int,
        metadata: dict | None = None,
    ) -> bool:
        """
        Store data in the cache.

        Args:
            url: Source URL (primary key, handles deduplication)
            identifier: Artist identifier (for randomimage lookups)
            data_type: Type of data (thumbnail, logo, banner, etc.)
            provider: Provider name (theaudiodb, discogs, etc.)
            data_value: The actual data (will be serialized appropriately)
            ttl_seconds: Time to live in seconds
            metadata: Optional metadata about the cached item

        Returns:
            True if stored successfully, False otherwise
        """
        await self.initialize()

        try:
            # Serialize data based on type
            if (
                isinstance(data_value, dict | list)
                or not isinstance(data_value, str)
                and not isinstance(data_value, bytes)
            ):
                serialized_data = json.dumps(data_value).encode("utf-8")
            elif isinstance(data_value, str):
                serialized_data = data_value.encode("utf-8")
            else:
                serialized_data = data_value
            now = int(time.time())
            expires_at = now + ttl_seconds
            metadata_json = json.dumps(metadata) if metadata else None
            cache_key = _generate_cache_key(identifier, data_type, provider, url)

            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                await connection.execute(
                    """
                    INSERT OR REPLACE INTO cached_data
                    (url, cache_key, identifier, data_type, provider, data_value, metadata,
                     created_at, expires_at, last_accessed, data_size)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        url,
                        cache_key,
                        identifier,
                        data_type,
                        provider,
                        serialized_data,
                        metadata_json,
                        now,
                        expires_at,
                        now,
                        len(serialized_data),
                    ),
                )

                await connection.commit()

            return True

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to store cached data for URL %s: %s", url, error)
            return False

    async def retrieve_by_url(self, url: str) -> tuple[Any, dict] | None:
        """
        Retrieve data from cache by URL.

        Args:
            url: Source URL to retrieve

        Returns:
            Tuple of (data, metadata) if found and not expired, None otherwise
        """
        await self.initialize()

        try:
            now = int(time.time())

            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                cursor = await connection.execute(
                    """
                    SELECT data_value, metadata, expires_at
                    FROM cached_data
                    WHERE url = ? AND expires_at > ?
                    """,
                    (url, now),
                )

                row = await cursor.fetchone()
                if not row:
                    return None

                data_value, metadata_json, _expires_at = row

                # Update access statistics
                await connection.execute(
                    """
                    UPDATE cached_data
                    SET access_count = access_count + 1, last_accessed = ?
                    WHERE url = ?
                    """,
                    (now, url),
                )
                await connection.commit()

            # Deserialize data
            try:
                data = json.loads(data_value.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                data = data_value

            metadata = json.loads(metadata_json) if metadata_json else {}
            return data, metadata

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to retrieve cached data for URL %s: %s", url, error)
            return None

    async def retrieve_by_identifier(  # pylint: disable=too-many-locals
        self, identifier: str, data_type: str, provider: str | None = None, random: bool = False
    ) -> list[tuple[Any, dict, str]] | tuple[Any, dict, str] | None:
        """
        Retrieve data from cache by identifier and data type.

        Used for randomimage functionality and multi-image lookups.

        Args:
            identifier: Artist identifier
            data_type: Type of data (thumbnail, logo, etc.)
            provider: Optional provider filter
            random: If True, return random single result; if False, return all matches

        Returns:
            If random=True: Single tuple of (data, metadata, url) or None
            If random=False: List of tuples [(data, metadata, url), ...] or empty list
        """
        await self.initialize()

        try:
            now = int(time.time())

            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                if provider:
                    query = """
                        SELECT data_value, metadata, url
                        FROM cached_data
                        WHERE identifier = ? AND data_type = ? AND provider = ? AND expires_at > ?
                    """
                    params = (identifier, data_type, provider, now)
                else:
                    query = """
                        SELECT data_value, metadata, url
                        FROM cached_data
                        WHERE identifier = ? AND data_type = ? AND expires_at > ?
                    """
                    params = (identifier, data_type, now)

                if random:
                    query += " ORDER BY RANDOM() LIMIT 1"

                cursor = await connection.execute(query, params)

                if random:
                    row = await cursor.fetchone()
                    if not row:
                        return None
                    rows = [row]
                else:
                    rows = await cursor.fetchall()

                if not rows:
                    return None if random else []

                # Update access statistics for all returned rows
                urls = [row[2] for row in rows]
                for url in urls:
                    await connection.execute(
                        """
                        UPDATE cached_data
                        SET access_count = access_count + 1, last_accessed = ?
                        WHERE url = ?
                        """,
                        (now, url),
                    )
                await connection.commit()

            # Deserialize all results
            results = []
            for data_value, metadata_json, url in rows:
                try:
                    data = json.loads(data_value.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    data = data_value

                metadata = json.loads(metadata_json) if metadata_json else {}
                results.append((data, metadata, url))

            return results[0] if random else results

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error(
                "Failed to retrieve cached data for %s/%s: %s", identifier, data_type, error
            )
            return None if random else []

    async def get_cache_keys_for_identifier(
        self, identifier: str, data_type: str, provider: str | None = None
    ) -> list[str]:
        """
        Get cache keys for an identifier and data type.

        Compatible with imagecache.get_cache_keys_for_identifier() for WebSocket interface.

        Args:
            identifier: Artist identifier
            data_type: Type of data (thumbnail, logo, etc.)
            provider: Optional provider filter

        Returns:
            List of cache key strings
        """
        await self.initialize()

        try:
            now = int(time.time())
            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                if provider:
                    query = """
                        SELECT DISTINCT cache_key
                        FROM cached_data
                        WHERE identifier = ? AND data_type = ? AND provider = ? AND expires_at > ?
                        ORDER BY created_at DESC
                    """
                    params = (identifier, data_type, provider, now)
                else:
                    query = """
                        SELECT DISTINCT cache_key
                        FROM cached_data
                        WHERE identifier = ? AND data_type = ? AND expires_at > ?
                        ORDER BY created_at DESC
                    """
                    params = (identifier, data_type, now)

                cursor = await connection.execute(query, params)
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to get cache keys for %s/%s: %s", identifier, data_type, error)
            return []

    async def queue_request(
        self,
        provider: str,
        request_key: str,
        params: dict[str, Any],
        priority: int = 2,  # 1=immediate, 2=batch
    ) -> bool:
        """
        Add a request to the database-backed queue.

        Args:
            provider: Provider name (theaudiodb, discogs, etc.)
            request_key: Type of request (artist_lookup, image_fetch, etc.)
            params: Request parameters
            priority: Request priority (1=immediate, 2=batch)

        Returns:
            True if queued successfully, False otherwise
        """
        await self.initialize()

        try:
            # Generate unique request ID
            params_str = json.dumps(params, sort_keys=True)
            request_id = f"{provider}:{request_key}:{hash(params_str)}"
            now = int(time.time())

            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                # Check if request already exists
                cursor = await connection.execute(
                    "SELECT request_id FROM pending_requests WHERE request_id = ?", (request_id,)
                )
                if await cursor.fetchone():
                    logging.debug("Request already queued: %s", request_id)
                    return False

                # Insert new request
                await connection.execute(
                    """
                    INSERT INTO pending_requests
                    (request_id, provider, request_key, params, priority, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (request_id, provider, request_key, params_str, priority, now),
                )
                await connection.commit()

                logging.debug("Request queued: %s", request_id)
                return True

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to queue request: %s", error)
            return False

    async def get_next_request(self, provider: str | None = None) -> dict[str, Any] | None:
        """
        Get the next pending request from the database queue.

        Args:
            provider: Optional provider filter

        Returns:
            Request dictionary or None if no requests available
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                if provider:
                    query = """
                        SELECT request_id, provider, request_key, params, priority, created_at
                        FROM pending_requests
                        WHERE status = 'pending' AND provider = ?
                        ORDER BY priority ASC, created_at ASC
                        LIMIT 1
                    """
                    cursor = await connection.execute(query, (provider,))
                else:
                    query = """
                        SELECT request_id, provider, request_key, params, priority, created_at
                        FROM pending_requests
                        WHERE status = 'pending'
                        ORDER BY priority ASC, created_at ASC
                        LIMIT 1
                    """
                    cursor = await connection.execute(query)

                row = await cursor.fetchone()
                if not row:
                    return None

                request_id, provider, request_key, params_str, priority, created_at = row

                # Mark as processing
                await connection.execute(
                    """
                    UPDATE pending_requests
                    SET status = 'processing', attempts = attempts + 1, last_attempt = ?
                    WHERE request_id = ?
                    """,
                    (int(time.time()), request_id),
                )
                await connection.commit()

                return {
                    "request_id": request_id,
                    "provider": provider,
                    "request_key": request_key,
                    "params": json.loads(params_str),
                    "priority": priority,
                    "created_at": created_at,
                }

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to get next request: %s", error)
            return None

    async def complete_request(self, request_id: str, success: bool = True) -> bool:
        """
        Mark a request as completed or failed.

        Args:
            request_id: ID of the request to complete
            success: Whether the request succeeded

        Returns:
            True if updated successfully
        """
        await self.initialize()

        try:
            status = "completed" if success else "failed"

            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                cursor = await connection.execute(
                    "UPDATE pending_requests SET status = ? WHERE request_id = ?",
                    (status, request_id),
                )
                await connection.commit()

                return cursor.rowcount > 0

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to complete request %s: %s", request_id, error)
            return False

    async def cleanup_expired(self) -> int:
        """Remove expired entries. Returns number of items cleaned up."""
        await self.initialize()

        try:
            now = int(time.time())
            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                cursor = await connection.execute(
                    "DELETE FROM cached_data WHERE expires_at <= ?",
                    (now,),
                )

                await connection.commit()
                return cursor.rowcount

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to cleanup expired cache entries: %s", error)
            return 0

    async def maintenance(self) -> dict[str, int]:
        """
        Perform database maintenance operations.

        Should be called at system startup to clean expired entries
        and reclaim database space.

        Returns:
            Dictionary with maintenance statistics
        """
        await self.initialize()

        stats = {"expired_cleaned": 0, "vacuum_performed": False, "errors": 0}

        try:
            # Clean up expired entries
            expired_count = await self.cleanup_expired()
            stats["expired_cleaned"] = expired_count

            if expired_count > 0:
                logging.info("Cleaned up %d expired cache entries", expired_count)

            # Vacuum database to reclaim space
            await self.vacuum()
            stats["vacuum_performed"] = True

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Database maintenance failed: %s", error)
            stats["errors"] += 1

        return stats

    async def vacuum(self) -> None:
        """Vacuum the database to reclaim space"""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                await connection.execute("VACUUM")
                logging.debug("Database vacuum completed")
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Database vacuum failed: %s", error)

    async def close(self) -> None:
        """Close the database connection - no-op with connection-per-operation pattern"""


def get_datacache_path(cache_dir: Path | None = None) -> Path:
    """
    Get the datacache database path using Qt standard cache location.

    Args:
        cache_dir: Optional custom cache directory. If None, uses Qt standard cache location.

    Returns:
        Path to the datacache database file
    """
    if cache_dir:
        base_dir = Path(cache_dir)
    else:
        base_dir = Path(
            QStandardPaths.standardLocations(QStandardPaths.StandardLocation.CacheLocation)[0]
        ).joinpath("datacache")

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "datacache.sqlite"


def run_datacache_maintenance(cache_dir: Path | None = None) -> dict[str, int]:
    """
    Run datacache maintenance at system startup (sync version).

    Args:
        cache_dir: Optional custom cache directory. If None, uses Qt standard cache location.

    Returns:
        Dictionary with maintenance statistics
    """
    database_path = get_datacache_path(cache_dir)

    stats = {"expired_cleaned": 0, "requests_cleaned": 0, "vacuum_performed": False, "errors": 0}

    try:
        # Ensure database exists with proper schema
        _ensure_datacache_schema(database_path)

        # Clean up expired entries and old requests
        with sqlite3.connect(str(database_path), timeout=30.0) as conn:
            now = int(time.time())

            # Clean expired cache data
            cursor = conn.execute("DELETE FROM cached_data WHERE expires_at <= ?", (now,))
            stats["expired_cleaned"] = cursor.rowcount

            # Clean completed/failed requests older than 24 hours
            one_day_ago = now - (24 * 3600)
            cursor = conn.execute(
                "DELETE FROM pending_requests WHERE status IN ('completed', 'failed') "
                "AND created_at <= ?",
                (one_day_ago,),
            )
            stats["requests_cleaned"] = cursor.rowcount

            conn.commit()

            if stats["expired_cleaned"] > 0:
                logging.info("Cleaned up %d expired datacache entries", stats["expired_cleaned"])
            if stats["requests_cleaned"] > 0:
                logging.info("Cleaned up %d old request records", stats["requests_cleaned"])

            # Vacuum database to reclaim space
            conn.execute("VACUUM")
            stats["vacuum_performed"] = True

    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.error("Datacache maintenance failed: %s", error)
        stats["errors"] += 1

    return stats


def _ensure_datacache_schema(database_path: Path) -> None:
    """Ensure the datacache database schema exists (sync version)"""
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(database_path), timeout=30.0) as conn:
        # Enable WAL mode for better concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")

        # Create schema - follows imagecache pattern for randomimage support
        schema_sql = """
        CREATE TABLE IF NOT EXISTS cached_data (
            url TEXT PRIMARY KEY,        -- Natural key, handles URL deduplication
            cache_key TEXT NOT NULL,     -- Stable cache key for WebSocket interface
            identifier TEXT NOT NULL,    -- Artist name (e.g., "daft_punk")
            data_type TEXT NOT NULL,     -- "thumbnail", "logo", "banner", etc.
            provider TEXT NOT NULL,      -- "theaudiodb", "discogs", etc.
            data_value BLOB,            -- The actual data (image bytes, JSON, etc.)
            metadata TEXT,              -- JSON metadata about the cached item
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            access_count INTEGER DEFAULT 1,
            last_accessed INTEGER NOT NULL,
            data_size INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pending_requests (
            request_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            request_key TEXT NOT NULL,
            params TEXT NOT NULL,  -- JSON encoded parameters
            priority INTEGER NOT NULL,  -- 1=immediate, 2=batch
            created_at INTEGER NOT NULL,
            attempts INTEGER DEFAULT 0,
            last_attempt INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending'  -- pending, processing, completed, failed
        );

        CREATE INDEX IF NOT EXISTS idx_identifier_type ON cached_data(identifier, data_type);
        CREATE INDEX IF NOT EXISTS idx_cache_key ON cached_data(cache_key);
        CREATE INDEX IF NOT EXISTS idx_provider ON cached_data(provider);
        CREATE INDEX IF NOT EXISTS idx_expires_at ON cached_data(expires_at);
        CREATE INDEX IF NOT EXISTS idx_last_accessed ON cached_data(last_accessed);

        CREATE INDEX IF NOT EXISTS idx_pending_provider ON pending_requests(provider);
        CREATE INDEX IF NOT EXISTS idx_pending_priority ON pending_requests(priority);
        CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_requests(status);
        CREATE INDEX IF NOT EXISTS idx_pending_created ON pending_requests(created_at);
        """

        conn.executescript(schema_sql)
        conn.commit()
