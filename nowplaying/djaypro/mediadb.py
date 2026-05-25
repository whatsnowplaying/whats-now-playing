#!/usr/bin/env python3
"""djay Pro MediaLibrary.db query helpers."""

import dataclasses
import pathlib
import sqlite3

import nowplaying.djaypro.tsaf
import nowplaying.utils.sqlite


@dataclasses.dataclass
class HistoryExtras:
    """Extra track metadata extracted from historySessionItems blobs."""

    isrc: str | None = None
    source: str | None = None
    deck: str | None = None
    starttime: float | None = None
    title_id: str | None = None


@dataclasses.dataclass
class DeckTrack:  # pylint: disable=too-many-instance-attributes
    """Full track state for one deck, used by mix mode selection."""

    artist: str | None = None
    title: str | None = None
    album: str | None = None
    duration: int | None = None
    filename: str | None = None
    bpm: str | None = None
    key: str | None = None
    isrc: str | None = None
    source: str | None = None
    deck: str | None = None


def query_recent_history(dbfile: pathlib.Path, limit: int = 20) -> list[dict]:
    """Return parsed metadata dicts for the most recent historySessionItems.

    Results are ordered newest-first.  Blobs that fail to parse are
    silently skipped so callers always get a clean list of dicts.
    """

    def query_db():
        records = []
        with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=1) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT data FROM database2 "
                "WHERE collection='historySessionItems' "
                "ORDER BY rowid DESC LIMIT ?",
                (limit,),
            )
            for (blob,) in cursor:
                parsed = nowplaying.djaypro.tsaf.parse_blob(blob)
                if parsed.get("title"):
                    records.append(parsed)
        return records

    try:
        return nowplaying.utils.sqlite.retry_sqlite_operation(query_db)
    except (sqlite3.OperationalError, FileNotFoundError):
        return []


def get_analyzed_data_by_uuid(dbfile: pathlib.Path | None, track_uuid: str) -> dict:
    """Look up bpm, deck, and key from mediaItemAnalyzedData by track UUID.

    Uses the database key column for an O(1) lookup rather than scanning
    all blobs.  The track UUID is the shared key between
    localMediaItemLocations and mediaItemAnalyzedData.
    """
    if not dbfile or not track_uuid:
        return {}

    def query_db() -> dict:
        with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=1) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT data FROM database2 WHERE collection='mediaItemAnalyzedData' AND key=?",
                (track_uuid,),
            )
            row = cursor.fetchone()
            if not row:
                return {}
            parsed = nowplaying.djaypro.tsaf.parse_blob(row[0])
            result = {}
            if parsed.get("bpm"):
                result["bpm"] = parsed["bpm"]
            if parsed.get("deck"):
                result["deck"] = parsed["deck"]
            if parsed.get("key"):
                result["key"] = parsed["key"]
            return result

    try:
        return nowplaying.utils.sqlite.retry_sqlite_operation(query_db)
    except (sqlite3.OperationalError, FileNotFoundError):
        return {}


def get_history_extras_from_db(
    dbfile: pathlib.Path | None, artist: str, title: str
) -> HistoryExtras:
    """Return isrc, source, and deck for a track by scanning recent historySessionItems.

    The most recently added history entry is almost always the currently
    playing track, so we scan from the end and stop as soon as we find a
    matching artist/title pair.  Scanning is bounded to 20 rows to keep it
    fast even for large history tables.
    """
    if not dbfile:
        return HistoryExtras()

    artist_lower = artist.strip().lower()
    title_lower = title.strip().lower()

    for parsed in query_recent_history(dbfile, limit=20):
        p_artist = parsed.get("artist")
        p_title = parsed.get("title")
        if (
            isinstance(p_artist, str)
            and isinstance(p_title, str)
            and p_artist.strip().lower() == artist_lower
            and p_title.strip().lower() == title_lower
        ):
            isrc = parsed.get("isrc")
            source = parsed.get("source")
            deck = parsed.get("deck")
            starttime = parsed.get("starttime")
            title_id = parsed.get("title_id")
            return HistoryExtras(
                isrc=isrc if isinstance(isrc, str) else None,
                source=source if isinstance(source, str) else None,
                deck=deck if isinstance(deck, str) else None,
                starttime=starttime if isinstance(starttime, float) else None,
                title_id=title_id if isinstance(title_id, str) else None,
            )
    return HistoryExtras()


def has_tracks_in_entire_library(dbfile: pathlib.Path | None, artist_name: str) -> bool:
    """Scan mediaItemTitleIDs TSAF blobs for a case-insensitive artist match."""
    artist_lower = artist_name.strip().lower()
    if not dbfile or not artist_lower:
        return False

    with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=5) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM database2 WHERE collection='mediaItemTitleIDs'")
        for (blob,) in cursor:
            parsed = nowplaying.djaypro.tsaf.parse_blob(blob)
            raw_artist = parsed.get("artist")
            if isinstance(raw_artist, str) and raw_artist.strip().lower() == artist_lower:
                return True
    return False


def has_tracks_in_playlists(
    dbfile: pathlib.Path | None, artist_name: str, playlist_names: list[str]
) -> bool:
    """Scan mediaItemTitleIDs blobs for tracks in selected playlists.

    Uses view_mediaItemPlaylistView_map and view_mediaItemPlaylistView_page
    to restrict the search to tracks belonging to the given playlists.
    Falls back to False (rather than the entire library) when the view
    tables are absent, which happens when no playlists are configured.
    """
    if not dbfile:
        return False
    artist_lower = artist_name.strip().lower()
    if not artist_lower or not playlist_names:
        return False

    # Use a single-playlist parameterised query (no dynamic SQL) to satisfy
    # the SQL injection scanner.  The IN clause cannot be expressed with a
    # fixed number of placeholders, so we issue one query per playlist name
    # instead — playlist counts are always small in practice.
    static_sql = (
        "SELECT d.data"
        " FROM database2 d"
        " JOIN view_mediaItemPlaylistView_map m"
        "   ON CAST(m.rowid AS INTEGER) = d.rowid"
        " JOIN view_mediaItemPlaylistView_page p"
        "   ON p.pageKey = m.pageKey"
        ' WHERE p."group" = ?'
        "   AND d.collection = 'mediaItemTitleIDs'"
    )
    with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=5) as conn:
        cursor = conn.cursor()
        for playlist_name in playlist_names:
            try:
                cursor.execute(static_sql, (playlist_name,))
            except sqlite3.OperationalError:
                # Catches both "view tables absent" (no playlists configured)
                # and transient lock errors that survive the 5-second timeout.
                # Either way there is nothing useful to return for this playlist.
                return False
            for (blob,) in cursor:
                parsed = nowplaying.djaypro.tsaf.parse_blob(blob)
                raw_artist = parsed.get("artist")
                if isinstance(raw_artist, str) and raw_artist.strip().lower() == artist_lower:
                    return True
    return False


def get_available_playlists_sync(dbfile: pathlib.Path | None) -> list[str]:
    """Return sorted list of playlist names from view_mediaItemPlaylistView_page."""
    if not dbfile:
        return []
    with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=5) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                'SELECT DISTINCT "group" FROM view_mediaItemPlaylistView_page'
                ' WHERE "group" IS NOT NULL AND "group" != \'\''
                ' ORDER BY "group"'
            )
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            # View table absent (no playlists configured)
            return []
