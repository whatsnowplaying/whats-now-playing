"""Shared utilities for the datacache package."""

import contextlib
import logging
import re
import sqlite3
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.utils.sqlite


def get_datacache_path(cache_dir: Path | None = None) -> Path:
    """Return the datacache database path, defaulting to Qt standard cache location."""
    if cache_dir:
        base_dir = Path(cache_dir)
    else:
        base_dir = Path(
            QStandardPaths.standardLocations(QStandardPaths.StandardLocation.CacheLocation)[0]
        ).joinpath("datacache")

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "datacache.sqlite"


def redact_url(url: str) -> str:
    """Sanitise a URL for logging by removing embedded credentials.

    Two patterns are redacted:
    - Query-param keys: api_key=, token=, apikey= and variants
    - Path-embedded numeric keys of 4+ digits, e.g. /json/523532/ (TheAudioDB)
    """
    url = re.sub(r"(?i)((?:api_?key|token|apikey)=)[^&\s]+", r"\1<redacted>", url)
    url = re.sub(r"(/(?:json|api)/)\d{4,}/", r"\1<redacted>/", url)
    return url


def _ensure_datacache_schema(database_path: Path) -> None:
    """Ensure the datacache database schema exists (sync version)"""
    database_path.parent.mkdir(parents=True, exist_ok=True)

    def _do_schema() -> None:
        with nowplaying.utils.sqlite.sqlite_connection(str(database_path)) as conn:
            # Enable WAL mode for better concurrent access
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")

            schema_sql = """
            CREATE TABLE IF NOT EXISTS cached_data (
                url TEXT PRIMARY KEY,        -- Natural key, handles URL deduplication
                cachekey TEXT UNIQUE,        -- Opaque UUID for WebSocket/external callers
                identifier TEXT NOT NULL,    -- Artist name (e.g., "daft_punk")
                data_type TEXT NOT NULL,     -- "thumbnail", "logo", "banner", etc.
                provider TEXT NOT NULL,      -- "theaudiodb", "discogs", etc.
                data_value BLOB,            -- Inline storage for content ≤ 16 KB
                file_path TEXT,             -- Blob file path for content > 16 KB
                metadata TEXT,              -- JSON metadata about the cached item
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                access_count INTEGER DEFAULT 1,
                last_accessed REAL NOT NULL,
                data_size INTEGER NOT NULL,
                status_code INTEGER NOT NULL DEFAULT 200,
                mime_type TEXT,             -- MIME type detected by puremagic, NULL for non-binary
                content_checksum TEXT,      -- SHA-256 hex digest of stored content
                color_palette TEXT          -- JSON dict with cover_palette/lighting/type keys
            );

            CREATE TABLE IF NOT EXISTS pending_requests (
                request_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                request_key TEXT NOT NULL,
                data_type TEXT NOT NULL DEFAULT '',
                params TEXT NOT NULL,  -- JSON encoded parameters
                priority INTEGER NOT NULL,  -- 1=immediate, 2=batch
                created_at INTEGER NOT NULL,
                attempts INTEGER DEFAULT 0,
                last_attempt INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending'  -- pending, processing, completed, failed
            );

            CREATE INDEX IF NOT EXISTS idx_identifier_type ON cached_data(identifier, data_type);
            CREATE INDEX IF NOT EXISTS idx_cachekey ON cached_data(cachekey);
            CREATE INDEX IF NOT EXISTS idx_provider ON cached_data(provider);
            CREATE INDEX IF NOT EXISTS idx_expires_at ON cached_data(expires_at);
            CREATE INDEX IF NOT EXISTS idx_last_accessed ON cached_data(last_accessed);
            CREATE INDEX IF NOT EXISTS idx_status_code ON cached_data(status_code);

            CREATE INDEX IF NOT EXISTS idx_pending_provider ON pending_requests(provider);
            CREATE INDEX IF NOT EXISTS idx_pending_priority ON pending_requests(priority);
            CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_requests(status);
            CREATE INDEX IF NOT EXISTS idx_pending_created ON pending_requests(created_at);
            CREATE INDEX IF NOT EXISTS idx_pending_type ON pending_requests(priority, data_type, status);
            """

            conn.executescript(schema_sql)

    nowplaying.utils.sqlite.retry_sqlite_operation(_do_schema)


def run_datacache_maintenance(cache_dir: Path | None = None) -> dict[str, int]:
    """Run datacache maintenance at system startup (sync version)."""
    database_path = get_datacache_path(cache_dir)

    stats = {
        "expired_cleaned": 0,
        "requests_cleaned": 0,
        "requests_recovered": 0,
        "vacuum_performed": 0,
        "errors": 0,
    }

    try:
        # Ensure database exists with proper schema
        _ensure_datacache_schema(database_path)

        now = time.time()
        one_day_ago = now - (24 * 3600)

        def _do_maintenance() -> tuple[int, int, int]:
            with nowplaying.utils.sqlite.sqlite_connection(str(database_path)) as conn:
                rows = conn.execute(
                    "SELECT url, file_path FROM cached_data"
                    " WHERE expires_at <= ? AND file_path IS NOT NULL",
                    (now,),
                ).fetchall()

                # Unlink blobs before deleting rows so a failed unlink leaves the
                # row intact for the next maintenance cycle to retry.
                urls_to_delete: list[str] = []
                for url, fp in rows:
                    try:
                        (database_path.parent / fp).unlink()
                        urls_to_delete.append(url)
                    except FileNotFoundError:
                        urls_to_delete.append(url)
                    except OSError:
                        logging.warning("Failed to unlink blob %s; row kept for next cleanup", fp)

                if urls_to_delete:
                    placeholders = ",".join("?" * len(urls_to_delete))
                    conn.execute(
                        f"DELETE FROM cached_data WHERE url IN ({placeholders})",
                        urls_to_delete,
                    )

                # Also delete rows with no blob that are expired
                cursor = conn.execute(
                    "DELETE FROM cached_data WHERE expires_at <= ? AND file_path IS NULL",
                    (now,),
                )
                expired = len(urls_to_delete) + cursor.rowcount

                cursor = conn.execute(
                    "DELETE FROM pending_requests WHERE status IN ('completed', 'failed') "
                    "AND created_at <= ?",
                    (one_day_ago,),
                )
                requests_cleaned = cursor.rowcount

                # Recover requests stuck in 'processing' from a previous crashed run
                cursor = conn.execute(
                    "UPDATE pending_requests SET status = 'pending', attempts = 0"
                    " WHERE status = 'processing'"
                )
                recovered = cursor.rowcount

                return expired, requests_cleaned, recovered

        def _do_vacuum() -> None:
            # VACUUM must run outside a transaction — use isolation_level=None (autocommit)
            with contextlib.closing(
                sqlite3.connect(str(database_path), isolation_level=None)
            ) as conn:
                conn.execute("VACUUM")

        expired_count, requests_count, recovered_count = (
            nowplaying.utils.sqlite.retry_sqlite_operation(_do_maintenance)
        )
        nowplaying.utils.sqlite.retry_sqlite_operation(_do_vacuum)
        stats["expired_cleaned"] = expired_count
        stats["requests_cleaned"] = requests_count
        stats["requests_recovered"] = recovered_count
        stats["vacuum_performed"] = 1

        if stats["expired_cleaned"] > 0:
            logging.info("Cleaned up %d expired datacache entries", stats["expired_cleaned"])
        if stats["requests_cleaned"] > 0:
            logging.info("Cleaned up %d old request records", stats["requests_cleaned"])
        if stats["requests_recovered"] > 0:
            logging.warning(
                "Recovered %d requests stuck in 'processing' from previous run",
                stats["requests_recovered"],
            )

    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.error("Datacache maintenance failed: %s", error)
        stats["errors"] += 1

    return stats
