"""Generic async storage layer for datacache: JSON, binary blobs, and metadata with TTL."""

import asyncio
import contextlib
import dataclasses
import hashlib
import io
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Literal, overload

import orjson
import PIL.Image
import puremagic

import aiofiles
import aiosqlite

import nowplaying.exceptions
import nowplaying.utils.sqlite
from .colors import COLOR_EXTRACT_TYPES, extract_palettes

from .utils import (  # noqa: F401  IMAGE_DATA_TYPES re-exported: tests import it from here
    IMAGE_DATA_TYPES,
    _effective_ttl,
    ensure_datacache_schema,
    get_datacache_path,
    redact_url,
)


@dataclasses.dataclass
class CachedEntry:  # pylint: disable=too-many-instance-attributes
    """Result returned by all DataStorage retrieve methods."""

    data: bytes
    metadata: dict
    status_code: int
    mime_type: str | None
    url: str | None = None  # populated by retrieve_by_cachekey and retrieve_by_identifier
    # Opaque handle for addressing this entry over HTTP; see the cover route in
    # webserver/static_handlers.py.  Assigned at first insert and preserved across
    # re-stores, so clients holding a key list from get_cache_keys_for_identifier stay
    # valid -- which also means a key can come to hold different bytes, so do not
    # serve it with long-lived cache headers.
    cachekey: str | None = None
    checksum: str | None = None  # SHA-256 hex digest of data, set on store
    color_palette: dict | None = None  # cover_palette/lighting/type extracted by colors.py


# Module-level lock for schema operations
_schema_lock = asyncio.Lock()

# Content ≤ this threshold is stored inline in the DB; larger content goes to a blob file.
# Production data shows API responses are consistently < 30 KB, images consistently > 16 KB.
_INLINE_THRESHOLD = 16 * 1024


def is_image_mime(mime_type: str | None) -> bool:
    """True when mime_type is a bare image/<subtype>.

    Parameters are refused as well as non-image types: a value carrying a charset
    makes aiohttp's Response(content_type=...) raise, so it is unusable as a
    Content-Type even when the bytes themselves are fine.  The separator and CRLF
    check guards a value that reaches a response header having come out of a
    cached_data row, which is why it is not left to Pillow's mimetype table.
    """
    if not mime_type:
        return False
    candidate = mime_type.strip().lower()
    if not candidate.startswith("image/") or candidate == "image/":
        return False
    return not any(char in candidate for char in ';,\r\n "\\')


def detect_image_mime(image: bytes | None) -> str | None:
    """The image's MIME type, or None when Pillow cannot parse these bytes.

    Pillow answers both questions at once -- is this a parseable image, and what kind
    -- so callers make one call.  Magic bytes alone would not do: a PNG signature
    followed by garbage satisfies them and still raises here, and that shape (a
    truncated download, a half-written file) is likelier than bytes with no magic.
    Image.open() parses the header only, so this stays cheap on the live path.

    Always derived, never taken from a declaration: an audio file's tag and a remote
    submission are both content we did not create, and callers put the result in a
    response Content-Type.  None therefore means "do not keep or serve these bytes" --
    there is deliberately no default, since labelling unparsable bytes image/png only
    moves the failure to a consumer that cannot detect it.
    """
    if not image:
        return None
    try:
        logging.getLogger("PIL.TiffImagePlugin").setLevel(logging.CRITICAL + 1)
        logging.getLogger("PIL.PngImagePlugin").setLevel(logging.CRITICAL + 1)
        with PIL.Image.open(io.BytesIO(image)) as img:
            detected = img.get_format_mimetype()
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        # Deliberately broad: this takes arbitrary bytes, and Pillow raises
        # UnidentifiedImageError, OSError and assorted plugin-specific errors.
        logging.debug("Not a parseable image", exc_info=True)
        return None
    # get_format_mimetype() is str | None -- a plugin need not declare one
    if not detected or not is_image_mime(detected):
        return None
    return detected.strip().lower()


def _mime_for_storage(url: str, data_value: bytes, data_type: str, status_code: int) -> str | None:
    """The mime_type to record, refusing an image type that is not a parseable image.

    Images are detected by detect_image_mime and nothing else, so the detector that
    decides these bytes are usable is the one whose answer gets recorded -- detecting
    with one library and validating with another hands callers a type from a check that
    never ran.

    Only real content is inspected: a negative cache entry is b"" with status_code=404,
    and rejecting those would leave the status_code != 200 retrieval guard with no row
    to suppress retries with, so every track would re-ask the provider.
    """
    if status_code == 200 and data_type in IMAGE_DATA_TYPES:
        if mime_type := detect_image_mime(data_value):
            return mime_type
        # Served as a Content-Type and rendered by templates, and coverurl on a remote
        # submission names a URL we fetch, which makes the body attacker-chosen.  Refuse
        # rather than store, and let the caller decide how loudly to complain.
        raise nowplaying.exceptions.ToxicContentError(f"{redact_url(url)} is not an image")
    try:
        return puremagic.from_string(data_value, mime=True)
    except Exception:  # pylint: disable=broad-exception-caught
        return None


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
            await asyncio.to_thread(ensure_datacache_schema, self.database_path)

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
    ) -> "CachedEntry | None":
        """Store bytes in the cache. Callers are responsible for encoding (e.g. orjson.dumps).

        Returns the stored entry on success, None on failure -- so existing truthiness
        checks still read correctly. Returning the entry rather than just a cachekey
        means callers get the cachekey they need to build an HTTP handle *and* the
        mime_type detected here, instead of deriving it a second time from the same
        bytes and having two places agree on what counts as an image.
        """
        await self.initialize()

        blob_path: Path | None = None
        blob_written = False

        try:
            now = time.time()
            expires_at = now + _effective_ttl(ttl_seconds, status_code)
            metadata_json = orjson.dumps(metadata).decode() if metadata else None
            new_cachekey = str(uuid.uuid4())
            data_size = len(data_value)
            content_checksum = (
                checksum if checksum is not None else hashlib.sha256(data_value).hexdigest()
            )

            mime_type = _mime_for_storage(url, data_value, data_type, status_code)

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

            # Deliberately not seeded with new_cachekey: that is the value this is
            # meant to stop reporting, so a silent fallback would reintroduce the bug.
            stored_cachekey: str | None = None

            async def _do_store() -> None:
                nonlocal stored_cachekey
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
                    # Read the key back rather than assuming new_cachekey landed. On the
                    # insert path it did; on the upsert path the UPDATE deliberately
                    # leaves the original key alone, so reporting the generated one would
                    # hand callers a key that is in no row.
                    #
                    # A SELECT rather than ON CONFLICT ... RETURNING on purpose:
                    # RETURNING needs SQLite >= 3.35 and the Linux build runs on
                    # AlmaLinux 8, whose sqlite-libs is 3.26. Python links libsqlite3
                    # dynamically, so that builds cleanly and then fails at runtime on
                    # the one platform macOS CI cannot see -- and it would fail for every
                    # datacache write at once. RETURNING also makes the fetch
                    # load-bearing for the write itself, which is a trap for anyone later
                    # removing a fetch they do not think they need.
                    cursor = await connection.execute(
                        "SELECT cachekey FROM cached_data WHERE url = ?", (url,)
                    )
                    if row := await cursor.fetchone():
                        stored_cachekey = row[0]
                    await connection.commit()

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_store)

            if not stored_cachekey:
                # The row must exist after a successful upsert, so this means the SQL
                # above stopped doing what it is assumed to do.  Fail rather than
                # invent a key: reporting one that is in no row is the bug this
                # read-back exists to prevent.
                logging.error("Stored %s but could not read its cachekey back", redact_url(url))
                return None

            # Only real content has colours to extract.  A negative entry is b'' with
            # status_code=404, and handing that to Pillow logged a full traceback at
            # ERROR for every provider miss.  COLOR_EXTRACT_TYPES is a subset of
            # IMAGE_DATA_TYPES, so anything reaching here with status 200 has already
            # been confirmed to be an image by the check above.
            if status_code == 200 and data_type in COLOR_EXTRACT_TYPES:
                asyncio.create_task(
                    self._extract_and_store_colors(url, data_value),
                    name=f"colors:{url[:60]}",
                )

            return CachedEntry(
                data=data_value,
                metadata=metadata or {},
                status_code=status_code,
                mime_type=mime_type,
                url=url,
                cachekey=stored_cachekey,
                checksum=content_checksum,
            )

        except nowplaying.exceptions.ToxicContentError:
            # Must outrun the broad handler below: swallowing this would report a
            # plain "could not cache" and leave the caller holding the payload.
            raise
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to store cached data for URL %s: %s", redact_url(url), error)
            if blob_written and blob_path:
                with contextlib.suppress(OSError):
                    blob_path.unlink()
            return None

    async def _extract_and_store_colors(self, url: str, data_value: bytes) -> None:
        """Run color extraction and write result to the dedicated color_palette column."""
        try:
            if not (colors := await extract_palettes(data_value)):
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
                               mime_type, content_checksum, color_palette, cachekey
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
                cachekey,
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
                url=url,
                cachekey=cachekey,
                checksum=content_checksum,
                color_palette=orjson.loads(color_palette_json) if color_palette_json else None,
            )

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to retrieve cached data for URL %s: %s", redact_url(url), error)
            return None

    async def retrieve_by_cachekey(self, cachekey: str) -> "CachedEntry | None":  # pylint: disable=too-many-locals
        """
        Retrieve data by opaque cachekey UUID.

        Provides imagecache-compatible lookup so callers holding a cachekey can
        retrieve the corresponding blob without knowing the original URL.

        The key is assigned at first insert and survives re-stores of the same URL,
        so a client holding one from get_cache_keys_for_identifier keeps working after
        a refetch.  The content behind it can change, so treat the bytes as current
        rather than immutable.

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
                cachekey=cachekey,
                color_palette=orjson.loads(color_palette_json) if color_palette_json else None,
            )

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to retrieve cached data for cachekey %s: %s", cachekey, error)
            return None

    async def _load_random_blob(  # pylint: disable=too-many-locals
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
            cachekey,
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
            cachekey=cachekey,
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
                            " status_code, mime_type, color_palette, cachekey"
                        )
                        order_limit = " ORDER BY RANDOM() LIMIT 1"
                    else:
                        # Only fetch metadata and url — caller uses retrieve_by_url for blobs
                        select_cols = (
                            "metadata, url, status_code, mime_type, color_palette, cachekey"
                        )
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
                    # random row: (data_value, file_path, metadata, url, status_code,
                    #              mime_type, color_palette, cachekey)
                    # non-random row: (metadata, url, status_code, mime_type,
                    #                   color_palette, cachekey)
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
                    cachekey=cachekey,
                    color_palette=orjson.loads(color_palette_json) if color_palette_json else None,
                )
                for (
                    metadata_json,
                    url,
                    status_code,
                    mime_type,
                    color_palette_json,
                    cachekey,
                ) in rows
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
