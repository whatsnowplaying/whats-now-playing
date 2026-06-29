"""Generic async storage layer for datacache: JSON, binary blobs, and metadata with TTL."""

import asyncio
import contextlib
import dataclasses
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Literal, overload

import orjson
import puremagic

import aiofiles
import aiosqlite

import nowplaying.utils.sqlite
from .colors import COLOR_EXTRACT_TYPES, extract_palettes
from .utils import _ensure_datacache_schema, get_datacache_path, redact_url


@dataclasses.dataclass
class CachedEntry:
    """Result returned by all DataStorage retrieve methods."""

    data: bytes
    metadata: dict
    status_code: int
    mime_type: str | None
    url: str | None = None  # populated by retrieve_by_cachekey and retrieve_by_identifier
    checksum: str | None = None  # SHA-256 hex digest of data, set on store
    color_palette: dict | None = None  # cover_palette/lighting/type extracted by colors.py


# Module-level lock for schema operations
_schema_lock = asyncio.Lock()

# Content ≤ this threshold is stored inline in the DB; larger content goes to a blob file.
# Production data shows API responses are consistently < 30 KB, images consistently > 16 KB.
_INLINE_THRESHOLD = 16 * 1024

# Canonical set of image data_types — shared between evict_lfu(), client._IMAGE_DATA_TYPES,
# and queue priority logic so all three stay in sync as types evolve.
IMAGE_DATA_TYPES: frozenset[str] = frozenset(
    {
        "artistthumbnail",
        "artistlogo",
        "artistbanner",
        "artistfanart",
        "front_cover",
    }
)


def _get_blob_path(cache_dir: Path, url: str) -> Path:
    """
    Get the filesystem path for storing a binary blob.

    Uses a 4-char prefix across two directory levels (65,536 leaf dirs) to keep
    per-directory file counts low on NTFS where Windows Defender and directory
    performance degrade past a few hundred files per directory.
    Content-addressed by URL hash so the same URL always maps to the same file.
    """
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    return cache_dir / "blobs" / url_hash[:2] / url_hash[2:4] / f"{url_hash[4:]}.bin"


class DataStorage:
    """Async storage layer for cached data with TTL management and URL-based primary keys."""

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
                await self._create_schema()
                self._initialized = True

    async def _create_schema(self) -> None:
        """Create the database schema without blocking the event loop."""
        async with _schema_lock:
            await asyncio.to_thread(_ensure_datacache_schema, self.database_path)

    async def store(  # pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments
        self,
        url: str,
        identifier: str,
        data_type: str,
        provider: str,
        data_value: bytes,
        ttl_seconds: int,
        metadata: dict | None = None,
        status_code: int = 200,
        checksum: str | None = None,
    ) -> bool:
        """Store bytes in the cache. Callers are responsible for encoding (e.g. orjson.dumps)."""
        await self.initialize()

        blob_path: Path | None = None
        blob_written = False

        try:
            now = time.time()
            expires_at = now + ttl_seconds
            metadata_json = orjson.dumps(metadata).decode() if metadata else None
            new_cachekey = str(uuid.uuid4())
            data_size = len(data_value)
            content_checksum = (
                checksum if checksum is not None else hashlib.sha256(data_value).hexdigest()
            )

            try:
                mime_type: str | None = puremagic.from_string(data_value, mime=True)
            except Exception:  # pylint: disable=broad-exception-caught
                mime_type = None

            if data_size <= _INLINE_THRESHOLD:
                inline_data: bytes | None = data_value
                file_path_str: str | None = None
            else:
                blob_path = _get_blob_path(self.database_path.parent, url)
                blob_path.parent.mkdir(parents=True, exist_ok=True)
                async with aiofiles.open(blob_path, "wb") as fh:
                    await fh.write(data_value)
                blob_written = True
                inline_data = None
                file_path_str = str(blob_path.relative_to(self.database_path.parent))

            async def _do_store() -> None:
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    await connection.execute(
                        """
                        INSERT INTO cached_data
                        (url, cachekey, identifier, data_type, provider,
                         data_value, file_path, metadata,
                         created_at, expires_at, last_accessed, data_size,
                         status_code, mime_type, content_checksum)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(url) DO UPDATE SET
                          identifier = excluded.identifier,
                          data_type = excluded.data_type,
                          provider = excluded.provider,
                          data_value = excluded.data_value,
                          file_path = excluded.file_path,
                          metadata = excluded.metadata,
                          expires_at = excluded.expires_at,
                          last_accessed = excluded.last_accessed,
                          data_size = excluded.data_size,
                          status_code = excluded.status_code,
                          mime_type = excluded.mime_type,
                          content_checksum = excluded.content_checksum
                        """,
                        (
                            url,
                            new_cachekey,
                            identifier,
                            data_type,
                            provider,
                            inline_data,
                            file_path_str,
                            metadata_json,
                            now,
                            expires_at,
                            now,
                            data_size,
                            status_code,
                            mime_type,
                            content_checksum,
                        ),
                    )
                    await connection.commit()

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_store)

            if data_type in COLOR_EXTRACT_TYPES:
                asyncio.create_task(
                    self._extract_and_store_colors(url, data_value),
                    name=f"colors:{url[:60]}",
                )

            return True

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to store cached data for URL %s: %s", redact_url(url), error)
            if blob_written and blob_path:
                with contextlib.suppress(OSError):
                    blob_path.unlink()
            return False

    async def _extract_and_store_colors(self, url: str, data_value: bytes) -> None:
        """Run color extraction and write result to the dedicated color_palette column."""
        try:
            colors = await extract_palettes(data_value)
            if not any(colors.values()):
                return

            async def _do_update() -> None:
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as conn:
                    await conn.execute(
                        "UPDATE cached_data SET color_palette = ?"
                        " WHERE url = ? AND color_palette IS NULL",
                        (orjson.dumps(colors).decode(), url),
                    )
                    await conn.commit()

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_update)
        except Exception:  # pylint: disable=broad-except
            logging.exception("Color extraction failed for %s", redact_url(url))

    async def retrieve_by_url(self, url: str) -> "CachedEntry | None":  # pylint: disable=too-many-locals
        """
        Retrieve data from cache by URL.

        Args:
            url: Source URL to retrieve

        Returns:
            CachedEntry if found and not expired, None otherwise
        """
        await self.initialize()

        try:
            now = time.time()
            rows: list[tuple] = []

            async def _do_retrieve() -> None:
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    cursor = await connection.execute(
                        """
                        SELECT data_value, file_path, metadata, status_code,
                               mime_type, content_checksum, color_palette
                        FROM cached_data
                        WHERE url = ? AND expires_at > ?
                        """,
                        (url, now),
                    )
                    row = await cursor.fetchone()
                    if not row:
                        return

                    rows.append(tuple(row))

                    # Lazy access_count update: only write if not updated in last 5 min.
                    # Reduces WAL pressure when OBS polls every few seconds.
                    await connection.execute(
                        """
                        UPDATE cached_data
                        SET access_count = access_count + 1, last_accessed = ?
                        WHERE url = ? AND last_accessed < ?
                        """,
                        (now, url, now - 300),
                    )
                    await connection.commit()

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_retrieve)

            if not rows:
                return None

            (
                data_value,
                file_path_str,
                metadata_json,
                status_code,
                mime_type,
                content_checksum,
                color_palette_json,
            ) = rows[0]

            if file_path_str:
                full_path = self.database_path.parent / file_path_str
                try:
                    async with aiofiles.open(full_path, "rb") as fh:
                        data = await fh.read()
                except FileNotFoundError:
                    logging.warning(
                        "Blob file missing for cached URL %s, deleting orphaned row", url
                    )

                    async def _do_delete_url() -> None:
                        async with aiosqlite.connect(
                            str(self.database_path), timeout=30.0
                        ) as connection:
                            await connection.execute(
                                "DELETE FROM cached_data WHERE url = ?", (url,)
                            )
                            await connection.commit()

                    await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_delete_url)
                    return None
            else:
                data = bytes(data_value)

            metadata = orjson.loads(metadata_json) if metadata_json else {}
            return CachedEntry(
                data=data,
                metadata=metadata,
                status_code=status_code,
                mime_type=mime_type,
                checksum=content_checksum,
                color_palette=orjson.loads(color_palette_json) if color_palette_json else None,
            )

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to retrieve cached data for URL %s: %s", redact_url(url), error)
            return None

    async def retrieve_by_cachekey(self, cachekey: str) -> "CachedEntry | None":  # pylint: disable=too-many-locals
        """
        Retrieve data by opaque cachekey UUID.

        Provides imagecache-compatible lookup by the stable UUID assigned at
        first insert.  Callers that stored a cachekey from get_cache_keys_for_identifier
        can retrieve the corresponding blob without knowing the original URL.

        Args:
            cachekey: UUID string returned by get_cache_keys_for_identifier

        Returns:
            CachedEntry if found and not expired, None otherwise (url field populated)
        """
        await self.initialize()

        try:
            now = time.time()
            rows: list[tuple] = []

            async def _do_retrieve_by_key() -> None:
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    cursor = await connection.execute(
                        """
                        SELECT data_value, file_path, metadata, url, status_code, mime_type,
                               color_palette
                        FROM cached_data
                        WHERE cachekey = ? AND expires_at > ?
                        """,
                        (cachekey, now),
                    )
                    row = await cursor.fetchone()
                    if not row:
                        return

                    rows.append(tuple(row))

                    await connection.execute(
                        """
                        UPDATE cached_data
                        SET access_count = access_count + 1, last_accessed = ?
                        WHERE cachekey = ? AND last_accessed < ?
                        """,
                        (now, cachekey, now - 300),
                    )
                    await connection.commit()

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_retrieve_by_key)

            if not rows:
                return None

            (
                data_value,
                file_path_str,
                metadata_json,
                url,
                status_code,
                mime_type,
                color_palette_json,
            ) = rows[0]

            if file_path_str:
                full_path = self.database_path.parent / file_path_str
                try:
                    async with aiofiles.open(full_path, "rb") as fh:
                        data = await fh.read()
                except FileNotFoundError:
                    logging.warning(
                        "Blob file missing for cachekey %s, deleting orphaned row", cachekey
                    )

                    async def _do_delete_cachekey() -> None:
                        async with aiosqlite.connect(
                            str(self.database_path), timeout=30.0
                        ) as connection:
                            await connection.execute(
                                "DELETE FROM cached_data WHERE cachekey = ?", (cachekey,)
                            )
                            await connection.commit()

                    await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_delete_cachekey)
                    return None
            else:
                data = bytes(data_value)

            metadata = orjson.loads(metadata_json) if metadata_json else {}
            return CachedEntry(
                data=data,
                metadata=metadata,
                status_code=status_code,
                mime_type=mime_type,
                url=url,
                color_palette=orjson.loads(color_palette_json) if color_palette_json else None,
            )

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to retrieve cached data for cachekey %s: %s", cachekey, error)
            return None

    async def _load_random_blob(
        self, row: tuple[Any, ...], identifier: str, data_type: str
    ) -> "CachedEntry | None":
        """Load data for a random row, deleting orphaned DB rows on FileNotFoundError."""
        (
            data_value,
            file_path_str,
            metadata_json,
            url,
            status_code,
            mime_type,
            color_palette_json,
        ) = row
        if file_path_str:
            full_path = self.database_path.parent / file_path_str
            try:
                async with aiofiles.open(full_path, "rb") as fh:
                    data = await fh.read()
            except FileNotFoundError:
                logging.warning(
                    "Blob file missing for %s/%s, deleting orphaned row", identifier, data_type
                )

                async def _do_delete_identifier() -> None:
                    async with aiosqlite.connect(
                        str(self.database_path), timeout=30.0
                    ) as connection:
                        await connection.execute("DELETE FROM cached_data WHERE url = ?", (url,))
                        await connection.commit()

                await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_delete_identifier)
                return None
        else:
            data = bytes(data_value)
        return CachedEntry(
            data=data,
            metadata=orjson.loads(metadata_json) if metadata_json else {},
            status_code=status_code,
            mime_type=mime_type,
            url=url,
            color_palette=orjson.loads(color_palette_json) if color_palette_json else None,
        )

    @overload
    async def retrieve_by_identifier(
        self,
        identifier: str,
        data_type: str,
        provider: str | None = ...,
        random: Literal[True] = ...,
    ) -> "CachedEntry | None": ...

    @overload
    async def retrieve_by_identifier(
        self,
        identifier: str,
        data_type: str,
        provider: str | None = ...,
        random: Literal[False] = ...,
    ) -> "list[CachedEntry]": ...

    async def retrieve_by_identifier(  # pylint: disable=too-many-locals
        self, identifier: str, data_type: str, provider: str | None = None, random: bool = False
    ) -> "list[CachedEntry] | CachedEntry | None":
        """
        Retrieve data from cache by identifier and data type.

        Used for randomimage functionality and multi-image lookups.

        Args:
            identifier: Artist identifier
            data_type: Type of data (thumbnail, logo, etc.)
            provider: Optional provider filter
            random: If True, fetch one random item including its blob data;
                    if False, return CachedEntry list without loading blobs
                    (call retrieve_by_url for the specific blob you need)

        Returns:
            If random=True: Single CachedEntry or None
            If random=False: List of CachedEntry (data=b"", blobs not loaded)
        """
        await self.initialize()

        try:
            now = time.time()
            rows: list[Any] = []

            async def _do_retrieve() -> None:
                nonlocal rows
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    if random:
                        select_cols = (
                            "data_value, file_path, metadata, url,"
                            " status_code, mime_type, color_palette"
                        )
                        order_limit = " ORDER BY RANDOM() LIMIT 1"
                    else:
                        # Only fetch metadata and url — caller uses retrieve_by_url for blobs
                        select_cols = "metadata, url, status_code, mime_type, color_palette"
                        order_limit = ""

                    if provider:
                        query = f"""
                            SELECT {select_cols}
                            FROM cached_data
                            WHERE identifier = ? AND data_type = ?
                              AND provider = ? AND expires_at > ?
                              AND status_code = 200
                        """
                        params = (identifier, data_type, provider, now)
                    else:
                        query = f"""
                            SELECT {select_cols}
                            FROM cached_data
                            WHERE identifier = ? AND data_type = ? AND expires_at > ?
                              AND status_code = 200
                        """
                        params = (identifier, data_type, now)

                    query += order_limit
                    cursor = await connection.execute(query, params)

                    if random:
                        row = await cursor.fetchone()
                        rows = [tuple(row)] if row else []
                    else:
                        rows = [tuple(r) for r in await cursor.fetchall()]

                    if not rows:
                        return

                    # Update access statistics for all returned rows
                    # random row: (data_value, file_path, metadata, url, status_code, mime_type)
                    # non-random row: (metadata, url, status_code, mime_type)
                    url_col = 3 if random else 1
                    for row in rows:
                        await connection.execute(
                            """
                            UPDATE cached_data
                            SET access_count = access_count + 1, last_accessed = ?
                            WHERE url = ? AND last_accessed < ?
                            """,
                            (now, row[url_col], now - 300),
                        )
                    await connection.commit()

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_retrieve)

            if not rows:
                return None if random else []

            if random:
                return await self._load_random_blob(rows[0], identifier, data_type)

            return [
                CachedEntry(
                    data=b"",
                    metadata=orjson.loads(metadata_json) if metadata_json else {},
                    status_code=status_code,
                    mime_type=mime_type,
                    url=url,
                    color_palette=orjson.loads(color_palette_json) if color_palette_json else None,
                )
                for metadata_json, url, status_code, mime_type, color_palette_json in rows
            ]

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
            now = time.time()
            cache_keys: list[str] = []

            async def _do_get_keys() -> None:
                nonlocal cache_keys
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    if provider:
                        query = """
                            SELECT cachekey
                            FROM cached_data
                            WHERE identifier = ? AND data_type = ?
                              AND provider = ? AND expires_at > ?
                              AND cachekey IS NOT NULL
                            ORDER BY created_at DESC
                        """
                        params = (identifier, data_type, provider, now)
                    else:
                        query = """
                            SELECT cachekey
                            FROM cached_data
                            WHERE identifier = ? AND data_type = ? AND expires_at > ?
                              AND cachekey IS NOT NULL
                            ORDER BY created_at DESC
                        """
                        params = (identifier, data_type, now)

                    cursor = await connection.execute(query, params)
                    rows = await cursor.fetchall()
                    cache_keys = [row[0] for row in rows]

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_get_keys)
            return cache_keys

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to get cache keys for %s/%s: %s", identifier, data_type, error)
            return []

    async def cleanup_expired(self) -> int:
        """Remove expired entries. Returns number of items cleaned up."""
        await self.initialize()

        try:
            now = time.time()
            expired_rows: list[tuple[str, str | None]] = []

            async def _do_fetch() -> None:
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    cursor = await connection.execute(
                        "SELECT url, file_path FROM cached_data WHERE expires_at <= ?",
                        (now,),
                    )
                    expired_rows.extend((row[0], row[1]) for row in await cursor.fetchall())

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_fetch)

            # Unlink blobs before deleting rows: a failed unlink leaves the row
            # intact so the next maintenance cycle can retry. FileNotFoundError
            # is safe — the file is already gone so the row can be deleted.
            urls_to_delete: list[str] = []
            for url, file_path in expired_rows:
                if file_path:
                    try:
                        (self.database_path.parent / file_path).unlink()
                        urls_to_delete.append(url)
                    except FileNotFoundError:
                        urls_to_delete.append(url)
                    except OSError:
                        logging.warning(
                            "Failed to unlink blob %s; row kept for next cleanup", file_path
                        )
                else:
                    urls_to_delete.append(url)

            if not urls_to_delete:
                return 0

            count = 0
            placeholders = ",".join("?" * len(urls_to_delete))

            async def _do_delete() -> None:
                nonlocal count
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    cursor = await connection.execute(
                        f"DELETE FROM cached_data WHERE url IN ({placeholders})",
                        urls_to_delete,
                    )
                    await connection.commit()
                    count = cursor.rowcount

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_delete)
            return count

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to cleanup expired cache entries: %s", error)
            return 0

    async def evict_lfu(self, size_limit_bytes: int = 2 * 1024 * 1024 * 1024) -> int:  # pylint: disable=too-many-locals
        """Evict image entries by Least Frequently Used until total size is under the limit.

        Only image data_types are considered for eviction; API response entries (tiny,
        infrequently re-fetched) are left alone. Blob files are deleted before their
        DB rows to avoid orphaned files on partial failure.

        Args:
            size_limit_bytes: Maximum total size for image entries (default 2 GB).

        Returns:
            Number of entries evicted.
        """
        await self.initialize()

        image_types = tuple(sorted(IMAGE_DATA_TYPES))
        placeholders = ",".join("?" * len(image_types))

        total_size: int = 0
        evict_candidates: list[tuple[str, str | None, int]] = []  # (url, file_path, data_size)
        evicted = 0

        async def _do_check() -> None:
            nonlocal total_size, evict_candidates
            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                cursor = await connection.execute(
                    f"SELECT SUM(data_size) FROM cached_data WHERE data_type IN ({placeholders})",
                    image_types,
                )
                row = await cursor.fetchone()
                total_size = row[0] if row and row[0] else 0
                if total_size <= size_limit_bytes:
                    return
                cursor = await connection.execute(
                    f"""
                    SELECT url, file_path, data_size FROM cached_data
                    WHERE data_type IN ({placeholders})
                    ORDER BY access_count ASC, last_accessed ASC
                    """,
                    image_types,
                )
                evict_candidates = [(r[0], r[1], r[2] or 0) for r in await cursor.fetchall()]

        await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_check)

        if total_size <= size_limit_bytes:
            return 0

        urls_to_delete: list[str] = []
        remaining = total_size
        for url, file_path, entry_size in evict_candidates:
            if remaining <= size_limit_bytes:
                break
            if file_path:
                try:
                    (self.database_path.parent / file_path).unlink()
                except FileNotFoundError:
                    pass  # blob already gone; still remove the orphaned DB row
                except OSError as err:
                    logging.warning("LFU evict: could not delete blob %s: %s", file_path, err)
                    continue  # keep both blob and row; retry next maintenance cycle
            urls_to_delete.append(url)
            remaining -= entry_size

        if not urls_to_delete:
            return 0

        batch_placeholders = ",".join("?" * len(urls_to_delete))

        async def _do_evict() -> None:
            nonlocal evicted
            async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                cursor = await connection.execute(
                    f"DELETE FROM cached_data WHERE url IN ({batch_placeholders})",
                    urls_to_delete,
                )
                await connection.commit()
                evicted = cursor.rowcount

        await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_evict)
        if evicted:
            logging.info(
                "LFU eviction: removed %d image entries to stay under size limit", evicted
            )
        return evicted

    async def maintenance(self) -> dict[str, int]:
        """
        Perform database maintenance operations.

        Should be called at system startup to clean expired entries
        and reclaim database space.

        Returns:
            Dictionary with maintenance statistics
        """
        await self.initialize()

        stats = {"expired_cleaned": 0, "lfu_evicted": 0, "vacuum_performed": 0, "errors": 0}

        try:
            # Clean up expired entries
            expired_count = await self.cleanup_expired()
            stats["expired_cleaned"] = expired_count

            if expired_count > 0:
                logging.info("Cleaned up %d expired cache entries", expired_count)

            # LFU eviction to stay under size limit
            evicted = await self.evict_lfu()
            stats["lfu_evicted"] = evicted

            # Vacuum database to reclaim space
            await self.vacuum()
            stats["vacuum_performed"] = 1

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Database maintenance failed: %s", error)
            stats["errors"] += 1

        return stats

    async def vacuum(self) -> None:
        """Vacuum the database to reclaim space"""
        await self.initialize()

        try:

            async def _do_vacuum() -> None:
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    await connection.execute("VACUUM")
                    logging.debug("Database vacuum completed")

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_vacuum)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Database vacuum failed: %s", error)

    async def close(self) -> None:
        """Close the database connection - no-op with connection-per-operation pattern"""
