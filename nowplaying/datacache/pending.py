"""Pending request queue for background datacache operations."""

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite
import orjson

import nowplaying.utils.sqlite
from .storage import _ensure_datacache_schema, get_datacache_path


class RequestQueue:
    """Database-backed queue for pending datacache fetch requests."""

    def __init__(self, database_path: Path | None = None):
        self.database_path = get_datacache_path(database_path)
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the database schema without blocking the event loop."""
        async with self._lock:
            if not self._initialized:
                self.database_path.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(_ensure_datacache_schema, self.database_path)
                self._initialized = True

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
            params_str = orjson.dumps(params, option=orjson.OPT_SORT_KEYS).decode()
            request_id = (
                f"{provider}:{request_key}:{hashlib.sha256(params_str.encode()).hexdigest()[:16]}"
            )
            now = time.time()
            queued = False

            async def _do_queue() -> None:
                nonlocal queued
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    # Check if request already exists
                    cursor = await connection.execute(
                        "SELECT request_id FROM pending_requests WHERE request_id = ?",
                        (request_id,),
                    )
                    if await cursor.fetchone():
                        logging.debug("Request already queued: %s", request_id)
                        return

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
                    queued = True
                    logging.debug("Request queued: %s", request_id)

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_queue)
            return queued

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
            result: dict[str, Any] | None = None

            async def _do_get_next() -> None:
                nonlocal result
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
                        return

                    req_id, req_provider, req_key, params_str, req_priority, created_at = row

                    # Mark as processing
                    await connection.execute(
                        """
                        UPDATE pending_requests
                        SET status = 'processing', attempts = attempts + 1, last_attempt = ?
                        WHERE request_id = ?
                        """,
                        (time.time(), req_id),
                    )
                    await connection.commit()

                    result = {
                        "request_id": req_id,
                        "provider": req_provider,
                        "request_key": req_key,
                        "params": orjson.loads(params_str),
                        "priority": req_priority,
                        "created_at": created_at,
                    }

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_get_next)
            return result

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
            updated = False

            async def _do_complete() -> None:
                nonlocal updated
                async with aiosqlite.connect(str(self.database_path), timeout=30.0) as connection:
                    cursor = await connection.execute(
                        "UPDATE pending_requests SET status = ? WHERE request_id = ?",
                        (status, request_id),
                    )
                    await connection.commit()
                    updated = cursor.rowcount > 0

            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_complete)
            return updated

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to complete request %s: %s", request_id, error)
            return False
