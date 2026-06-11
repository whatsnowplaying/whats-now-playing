#!/usr/bin/env python3
"""Side SQLite index for djay Pro location data.

djay Pro stores file paths inside TSAF binary blobs with no queryable text
columns, forcing a full table scan to match by artist/title.  This module
maintains a WNP-owned index so lookups are O(log n) rather than O(n)
blob-decode scans.

The index is append-only: sync() checks MAX(rowid) in djay's location
collections and only processes rows that are newer than the last sync.
In-place updates (e.g. a file move) are not reflected until rebuild() is
called, which is acceptable for a live-set workflow.
"""

import logging
import pathlib
import sqlite3
import time

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.djaypro.tsaf
import nowplaying.utils.sqlite

_LOCATION_COLLECTIONS = ("localMediaItemLocations", "globalMediaItemLocations")
_LOCATION_PLACEHOLDERS = ",".join("?" * len(_LOCATION_COLLECTIONS))

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS locations (
        uuid         TEXT PRIMARY KEY,
        title_lower  TEXT NOT NULL,
        artist_lower TEXT NOT NULL DEFAULT '',
        filename     TEXT,
        isrc         TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_title ON locations (title_lower)",
    """CREATE TABLE IF NOT EXISTS sync_state (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
]


def default_db_path() -> pathlib.Path:
    """Return the default WNP-owned location index path under Qt's cache dir."""
    cache = QStandardPaths.standardLocations(QStandardPaths.StandardLocation.CacheLocation)[0]
    return pathlib.Path(cache).joinpath("djaypro", "djaypro-locations.db")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in _SCHEMA:
        conn.execute(stmt)
    conn.commit()


def _get_stored_max_rowid(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM sync_state WHERE key='max_rowid'").fetchone()
    return int(row[0]) if row else -1


def _set_stored_max_rowid(conn: sqlite3.Connection, rowid: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES ('max_rowid', ?)",
        (str(rowid),),
    )


def _get_last_rebuild_time(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT value FROM sync_state WHERE key='last_rebuild'").fetchone()
    return float(row[0]) if row else 0.0


def _set_last_rebuild_time(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES ('last_rebuild', ?)",
        (str(time.time()),),
    )


def get_last_rebuild_time(side_db: pathlib.Path) -> float:
    """Return the timestamp of the last full rebuild, or 0.0 if never rebuilt."""
    if not side_db.exists():
        return 0.0

    def query() -> float:
        with nowplaying.utils.sqlite.sqlite_connection(str(side_db), timeout=1) as conn:
            return _get_last_rebuild_time(conn)

    try:
        return nowplaying.utils.sqlite.retry_sqlite_operation(query)
    except (sqlite3.OperationalError, FileNotFoundError):
        return 0.0


def _probe_djay_max_rowid(djay_dbfile: pathlib.Path) -> int | None:
    """Return MAX(rowid) for location collections in djay's DB, or None on error."""

    def query() -> int:
        with nowplaying.utils.sqlite.sqlite_connection(str(djay_dbfile), timeout=1) as conn:
            row = conn.execute(
                f"SELECT MAX(rowid) FROM database2 WHERE collection IN ({_LOCATION_PLACEHOLDERS})",
                _LOCATION_COLLECTIONS,
            ).fetchone()
            return row[0] if row and row[0] is not None else -1

    try:
        return nowplaying.utils.sqlite.retry_sqlite_operation(query)
    except (sqlite3.OperationalError, FileNotFoundError) as err:
        logging.debug("djaypro locationdb: could not probe djay DB: %s", err)
        return None


def _fetch_new_rows(
    djay_dbfile: pathlib.Path, after_rowid: int
) -> list[tuple[str, str, str, str | None, str | None]] | None:
    """Return parsed rows with rowid > after_rowid, or None on DB error.

    Returns None (not empty list) when the fetch fails so callers can
    distinguish a DB error from a genuinely empty result and avoid
    advancing the watermark incorrectly.
    """

    def query() -> list[tuple[str, str, str, str | None, str | None]]:
        results: list[tuple[str, str, str, str | None, str | None]] = []
        with nowplaying.utils.sqlite.sqlite_connection(str(djay_dbfile), timeout=1) as conn:
            cursor = conn.execute(
                f"SELECT key, data FROM database2"
                f" WHERE collection IN ({_LOCATION_PLACEHOLDERS}) AND rowid > ?",
                _LOCATION_COLLECTIONS + (after_rowid,),
            )
            for uuid, blob in cursor:
                parsed = nowplaying.djaypro.tsaf.parse_blob(blob)
                title = parsed.get("title")
                if not isinstance(title, str) or not title.strip():
                    continue
                artist = parsed.get("artist")
                isrc = parsed.get("isrc")
                filename = parsed.get("filename")
                results.append(
                    (
                        uuid,
                        title.strip().lower(),
                        artist.strip().lower() if isinstance(artist, str) else "",
                        filename if isinstance(filename, str) else None,
                        isrc if isinstance(isrc, str) else None,
                    )
                )
        return results

    try:
        return nowplaying.utils.sqlite.retry_sqlite_operation(query)
    except (sqlite3.OperationalError, FileNotFoundError) as err:
        logging.debug("djaypro locationdb: could not fetch new rows: %s", err)
        return None


def catchup_index(djay_dbfile: pathlib.Path, side_db: pathlib.Path) -> None:
    """Index any location rows added to djay Pro's DB since the last run.

    Steady-state cost is a single MAX(rowid) probe; only opens djay's DB
    a second time when new rows are actually present.
    """
    djay_max = _probe_djay_max_rowid(djay_dbfile)
    if djay_max is None:
        return

    side_db.parent.mkdir(parents=True, exist_ok=True)

    try:
        with nowplaying.utils.sqlite.sqlite_connection(str(side_db)) as conn:
            _ensure_schema(conn)
            our_max = _get_stored_max_rowid(conn)

            if djay_max <= our_max:
                return

            new_rows = _fetch_new_rows(djay_dbfile, our_max)
            if new_rows is None:
                # DB was locked during fetch — don't advance watermark so
                # these rows are retried on the next sync call.
                return
            if new_rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO locations"
                    " (uuid, title_lower, artist_lower, filename, isrc)"
                    " VALUES (?, ?, ?, ?, ?)",
                    new_rows,
                )
                logging.debug("djaypro locationdb: indexed %d new location rows", len(new_rows))

            _set_stored_max_rowid(conn, djay_max)
            conn.commit()

    except (sqlite3.OperationalError, FileNotFoundError) as err:
        logging.debug("djaypro locationdb: sync failed: %s", err)


def lookup(
    artist: str, title: str, side_db: pathlib.Path
) -> tuple[str | None, str | None, str | None]:
    """Return (filename, uuid, isrc) for a track, or (None, None, None) if not found.

    Matches on title_lower; requires artist match when both sides are non-empty,
    accepts a miss on either side (mirrors the original blob-scan logic).
    """
    if not side_db.exists():
        return None, None, None

    title_lower = title.strip().lower() if title else ""
    artist_lower = artist.strip().lower() if artist else ""
    if not title_lower:
        return None, None, None

    def query() -> tuple[str | None, str | None, str | None]:
        with nowplaying.utils.sqlite.sqlite_connection(str(side_db), timeout=1) as conn:
            row = conn.execute(
                "SELECT filename, uuid, isrc FROM locations"
                " WHERE title_lower = ?"
                "   AND (artist_lower = ? OR artist_lower = '' OR ? = '')"
                " LIMIT 1",
                (title_lower, artist_lower, artist_lower),
            ).fetchone()
            return (row[0], row[1], row[2]) if row else (None, None, None)

    try:
        return nowplaying.utils.sqlite.retry_sqlite_operation(query)
    except (sqlite3.OperationalError, FileNotFoundError):
        return None, None, None


def lookup_direct(djay_dbfile: pathlib.Path, title_id: str) -> tuple[str | None, str | None]:
    """Return (filename, isrc) via O(1) key lookup in djay's DB.

    Uses the ADCMediaItemTitleID UUID as the database2 key — the direct FK
    between historySessionItems and the location collections.  Falls back to
    (None, None) when the track is absent or on error.
    """

    def query() -> tuple[str | None, str | None]:
        with nowplaying.utils.sqlite.sqlite_connection(str(djay_dbfile), timeout=1) as conn:
            row = conn.execute(
                "SELECT data FROM database2"
                f" WHERE collection IN ({_LOCATION_PLACEHOLDERS}) AND key = ?",
                _LOCATION_COLLECTIONS + (title_id,),
            ).fetchone()
            if not row:
                return None, None
            parsed = nowplaying.djaypro.tsaf.parse_blob(row[0])
            filename = parsed.get("filename")
            isrc = parsed.get("isrc")
            return (
                filename if isinstance(filename, str) else None,
                isrc if isinstance(isrc, str) else None,
            )

    try:
        return nowplaying.utils.sqlite.retry_sqlite_operation(query)
    except (sqlite3.OperationalError, FileNotFoundError) as err:
        logging.debug("djaypro locationdb: lookup_direct failed: %s", err)
        return None, None


def rebuild(djay_dbfile: pathlib.Path, side_db: pathlib.Path) -> None:
    """Drop and fully rebuild the location index from djay's DB.

    Writes to a temp file then renames atomically so the index is never
    absent during the rebuild. Use when the index may be stale (e.g.
    files were moved in djay Pro).
    """
    tmp = side_db.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()

    catchup_index(djay_dbfile, tmp)

    if not tmp.exists():
        # sync() bailed early (djay DB unreachable) — leave old index intact
        return

    # Record rebuild timestamp before promoting the file
    try:
        with nowplaying.utils.sqlite.sqlite_connection(str(tmp)) as conn:
            _set_last_rebuild_time(conn)
            conn.commit()
    except (sqlite3.OperationalError, FileNotFoundError) as err:
        logging.debug("djaypro locationdb: could not stamp rebuild time: %s", err)

    tmp.replace(side_db)

    try:
        with nowplaying.utils.sqlite.sqlite_connection(str(side_db), timeout=1) as conn:
            row = conn.execute("SELECT COUNT(*) FROM locations").fetchone()
            count = row[0] if row else 0
        logging.info("djaypro locationdb: rebuild complete, %d tracks indexed", count)
    except (sqlite3.OperationalError, FileNotFoundError) as err:
        logging.info("djaypro locationdb: rebuild complete (count unavailable: %s)", err)
