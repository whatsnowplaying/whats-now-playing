#!/usr/bin/env python3
"""
Rekordbox Database Reader

This module handles reading track data from the encrypted Rekordbox SQLite database.
It provides async access to track history and metadata.
"""

import asyncio
import logging
import pathlib
import re

import sqlcipher3 as sqlite

import nowplaying.utils.sqlite
from .config import ConfigReader
from .types import RekordboxError, RekordboxTrack

_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# Shared column list for all content queries.  Commnt is the Rekordbox
# column name (truncated by AlphaTheta); it is not a typo.
_CONTENT_COLUMNS = """\
        c.Title,
        a.Name as ArtistName,
        al.Name as AlbumName,
        g.Name as GenreName,
        c.BPM,
        c.Length,
        c.TrackNo,
        c.DiscNo,
        c.ReleaseYear,
        c.BitRate,
        c.BitDepth,
        c.SampleRate,
        c.FileNameL,
        c.FolderPath,
        c.ImagePath,
        c.Rating,
        c.DJPlayCount,
        c.Commnt,
        k.ScaleName as KeyName,
        l.Name as LabelName,
        comp.Name as ComposerName,
        c.Lyricist,
        c.ISRC,
        c.FileSize,
        c.FileType"""

_CONTENT_JOINS = """\
        LEFT JOIN djmdArtist a ON c.ArtistID = a.ID
        LEFT JOIN djmdAlbum al ON c.AlbumID = al.ID
        LEFT JOIN djmdGenre g ON c.GenreID = g.ID
        LEFT JOIN djmdKey k ON c.KeyID = k.ID AND c.KeyID != 0
        LEFT JOIN djmdLabel l ON c.LabelID = l.ID
        LEFT JOIN djmdArtist comp ON c.ComposerID = comp.ID"""


class DatabaseReader:
    """Async reader for Rekordbox encrypted database"""

    def __init__(self, config_reader: ConfigReader | None = None):
        self.config_reader = config_reader or ConfigReader()
        self.database_path: pathlib.Path | None = None
        self.encryption_key: str | None = None
        self._current_track_id: str | None = None

    async def initialize(self, custom_key: str = "") -> None:
        """
        Initialize database connection parameters

        Raises:
            RekordboxError: If initialization fails
        """
        no_key_error = RekordboxError(
            "No database key configured. "
            "Enter the Rekordbox 7 key in Settings → Input → Rekordbox. "
            'Search: "what is the rekordbox 7 sqlcipher key for master.db"'
        )
        try:
            auto_detected = not custom_key
            self.encryption_key = custom_key or self.config_reader.get_password()

            if not self.encryption_key:
                raise no_key_error

            # PRAGMA key cannot use parameterized queries (SQLCipher limitation).
            # Validate the key is a 64-character hex string before it reaches any SQL.
            if not _KEY_RE.match(self.encryption_key):
                raise RekordboxError("Database key must be a 64-character hexadecimal string.")

            # Set database path
            self.database_path = self.config_reader.get_database_path()

            if not self.database_path.exists():
                raise RekordboxError(f"Rekordbox database not found: {self.database_path}")

            try:
                await asyncio.to_thread(self._validate_key_sync)
            except RekordboxError as err:
                self.encryption_key = None
                if auto_detected:
                    # Auto-detected key (e.g. a leftover RB6 'dp' field on an
                    # upgraded install) didn't actually open the database -
                    # this install needs a manually supplied key instead.
                    raise no_key_error from err
                raise

            logging.info("Successfully initialized Rekordbox database reader")

        except RekordboxError:
            raise
        except Exception as err:  # pylint: disable=broad-exception-caught
            raise RekordboxError(f"Failed to initialize database reader: {err}") from err

    def _validate_key_sync(self) -> None:
        """Confirm the configured key can actually decrypt the database.

        PRAGMA key never fails on its own; SQLCipher only errors on the
        first real query, so without this check a wrong key would surface
        later as a confusing generic query failure instead of a clear,
        actionable initialization error.
        """

        def _query() -> None:
            with sqlite.connect(str(self.database_path)) as conn:  # pylint: disable=no-member
                self._open_conn(conn)
                conn.execute("SELECT count(*) FROM djmdContent").fetchone()

        try:
            nowplaying.utils.sqlite.retry_sqlite_operation(_query)
        except Exception as err:  # pylint: disable=broad-exception-caught
            raise RekordboxError(
                f"Database key is incorrect or database is unreadable: {err}"
            ) from err

    def _open_conn(self, conn):
        """Apply standard SQLCipher pragmas to an open connection."""
        conn.execute(f'PRAGMA key="{self.encryption_key}"')
        conn.execute("PRAGMA cipher_compatibility = 4")
        conn.execute("PRAGMA read_uncommitted = 1")

    def _build_track(  # pylint: disable=too-many-locals
        self, identifier: str, row: tuple
    ) -> RekordboxTrack:
        """Construct a RekordboxTrack from a content-columns result row."""
        (
            title,
            artist_name,
            album_name,
            genre_name,
            raw_bpm,
            duration,
            track_no,
            disc_no,
            year,
            bitrate,
            bit_depth,
            sample_rate,
            file_name,
            folder_path,
            image_path,
            rating,
            play_count,
            comments,
            key_name,
            label_name,
            composer_name,
            lyricist,
            isrc,
            file_size,
            file_type,
        ) = row

        absolute_image_path = None
        if image_path:
            absolute_image_path = str(self.config_reader.get_image_path(image_path))

        return RekordboxTrack(
            identifier=identifier,
            title=title,
            artist=artist_name,
            album=album_name,
            genre=genre_name,
            bpm=round(raw_bpm / 100, 2) if raw_bpm else None,
            duration=duration,
            track_no=track_no,
            disc_no=disc_no,
            year=year,
            bitrate=bitrate,
            bit_depth=bit_depth,
            sample_rate=sample_rate,
            file_name=file_name,
            folder_path=folder_path,
            image_path=absolute_image_path,
            rating=rating,
            play_count=play_count,
            comments=comments,
            key=key_name,
            label=label_name,
            composer=composer_name,
            lyricist=lyricist if lyricist else None,
            isrc=isrc,
            file_size=file_size,
            file_type=file_type,
        )

    async def get_recent_track(self) -> RekordboxTrack | None:
        """
        Get the most recent track from the database

        Returns:
            RekordboxTrack object with track data, or None if no tracks found

        Raises:
            RekordboxError: If database query fails
        """
        if not self.database_path or not self.encryption_key:
            raise RekordboxError("Database reader not initialized")

        try:
            return await asyncio.to_thread(self.get_recent_track_sync)
        except Exception as err:  # pylint: disable=broad-exception-caught
            raise RekordboxError(f"Database query failed: {err}") from err

    def get_recent_track_sync(self) -> RekordboxTrack | None:
        """Synchronous database query using sqlcipher3"""

        def _query() -> RekordboxTrack | None:
            with sqlite.connect(str(self.database_path)) as conn:  # pylint: disable=no-member
                self._open_conn(conn)

                # Query history only to avoid false positives from tracks
                # loaded on multiple decks without being played.
                query = f"""
                    SELECT
                        h.ID as HistoryID,
{_CONTENT_COLUMNS}
                    FROM djmdSongHistory h
                    JOIN djmdContent c ON h.ContentID = c.ID
{_CONTENT_JOINS}
                    ORDER BY h.created_at DESC
                    LIMIT 1
                """

                cursor = conn.execute(query)
                row = cursor.fetchone()

                if not row:
                    logging.debug("No tracks found in Rekordbox play history")
                    return None

                history_id, *content_row = row
                return self._build_track(str(history_id) if history_id else "", tuple(content_row))

        return nowplaying.utils.sqlite.retry_sqlite_operation(_query)

    def has_track_changed(self, track: RekordboxTrack | None) -> bool:
        """
        Check if the track has changed since last check

        Args:
            track: Current track data

        Returns:
            True if track has changed, False otherwise
        """
        if track is None:
            has_changed = self._current_track_id is not None
        else:
            has_changed = track.identifier != self._current_track_id

        if has_changed and track:
            self._current_track_id = track.identifier
        elif track is None:
            self._current_track_id = None

        return has_changed

    async def get_playlists(self) -> list[tuple[str, str]]:
        """
        Get list of available playlists

        Returns:
            List of (playlist_id, playlist_name) tuples
        """
        if not self.database_path or not self.encryption_key:
            raise RekordboxError("Database reader not initialized")

        try:
            return await asyncio.to_thread(self._get_playlists_sync)
        except Exception as err:  # pylint: disable=broad-exception-caught
            raise RekordboxError(f"Failed to get playlists: {err}") from err

    def _get_playlists_sync(self) -> list[tuple[str, str]]:
        """Synchronous playlist query"""

        def _query() -> list[tuple[str, str]]:
            with sqlite.connect(str(self.database_path)) as conn:  # pylint: disable=no-member
                self._open_conn(conn)

                query = """
                    SELECT ID, Name
                    FROM djmdPlaylist
                    WHERE Name IS NOT NULL AND Name != ''
                    ORDER BY Seq, Name
                """

                cursor = conn.execute(query)
                return [(row[0], row[1]) for row in cursor.fetchall()]

        return nowplaying.utils.sqlite.retry_sqlite_operation(_query)

    async def get_random_track_from_playlist(self, playlist_name: str) -> RekordboxTrack | None:
        """
        Get a random track from the specified playlist

        Args:
            playlist_name: Name of the playlist

        Returns:
            Random track from playlist, or None if playlist not found/empty
        """
        if not self.database_path or not self.encryption_key:
            raise RekordboxError("Database reader not initialized")

        try:
            return await asyncio.to_thread(
                self._get_random_track_from_playlist_sync, playlist_name
            )
        except Exception as err:
            raise RekordboxError(f"Failed to get random track from playlist: {err}") from err

    def _get_random_track_from_playlist_sync(self, playlist_name: str) -> RekordboxTrack | None:
        """Synchronous random track from playlist query"""

        def _query() -> RekordboxTrack | None:
            with sqlite.connect(str(self.database_path)) as conn:  # pylint: disable=no-member
                self._open_conn(conn)

                query = f"""
                    SELECT
                        c.ID,
{_CONTENT_COLUMNS}
                    FROM djmdSongPlaylist sp
                    JOIN djmdPlaylist p ON sp.PlaylistID = p.ID
                    JOIN djmdContent c ON sp.ContentID = c.ID
{_CONTENT_JOINS}
                    WHERE p.Name = ?
                    ORDER BY RANDOM()
                    LIMIT 1
                """

                cursor = conn.execute(query, (playlist_name,))
                row = cursor.fetchone()

                if not row:
                    logging.debug("No tracks found in playlist: %s", playlist_name)
                    return None

                content_id, *content_row = row
                track = self._build_track(str(content_id), tuple(content_row))
                logging.debug(
                    "Retrieved random track from playlist %s: %s - %s",
                    playlist_name,
                    track.artist,
                    track.title,
                )
                return track

        return nowplaying.utils.sqlite.retry_sqlite_operation(_query)

    async def has_artist_in_library(self, artist_name: str) -> bool:
        """
        Check if artist exists in entire library

        Args:
            artist_name: Name of the artist to search for

        Returns:
            True if artist found in library, False otherwise

        Raises:
            RekordboxError: If database query fails
        """
        if not self.database_path or not self.encryption_key:
            raise RekordboxError("Database reader not initialized")

        try:
            return await asyncio.to_thread(self._has_artist_in_library_sync, artist_name)
        except Exception as err:
            raise RekordboxError(f"Failed to check artist in library: {err}") from err

    def _has_artist_in_library_sync(self, artist_name: str) -> bool:
        """Synchronous check if artist exists in entire library"""

        def _query() -> bool:
            with sqlite.connect(str(self.database_path)) as conn:  # pylint: disable=no-member
                self._open_conn(conn)

                query = """
                    SELECT COUNT(*) as count
                    FROM djmdContent c
                    LEFT JOIN djmdArtist a ON c.ArtistID = a.ID
                    WHERE LOWER(COALESCE(a.Name, '')) = LOWER(?)
                """

                cursor = conn.execute(query, (artist_name,))
                row = cursor.fetchone()
                return row[0] > 0 if row else False

        return nowplaying.utils.sqlite.retry_sqlite_operation(_query)

    async def has_artist_in_playlist(self, artist_name: str, playlist_name: str) -> bool:
        """
        Check if artist exists in a specific playlist

        Args:
            artist_name: Name of the artist to search for
            playlist_name: Name of the playlist to search in

        Returns:
            True if artist found in playlist, False otherwise

        Raises:
            RekordboxError: If database query fails
        """
        if not self.database_path or not self.encryption_key:
            raise RekordboxError("Database reader not initialized")

        try:
            return await asyncio.to_thread(
                self._has_artist_in_playlist_sync, artist_name, playlist_name
            )
        except Exception as err:
            raise RekordboxError(f"Failed to check artist in playlist: {err}") from err

    def _has_artist_in_playlist_sync(self, artist_name: str, playlist_name: str) -> bool:
        """Synchronous check if artist exists in a specific playlist"""

        def _query() -> bool:
            with sqlite.connect(str(self.database_path)) as conn:  # pylint: disable=no-member
                self._open_conn(conn)

                query = """
                    SELECT COUNT(*) as count
                    FROM djmdSongPlaylist sp
                    JOIN djmdPlaylist p ON sp.PlaylistID = p.ID
                    JOIN djmdContent c ON sp.ContentID = c.ID
                    LEFT JOIN djmdArtist a ON c.ArtistID = a.ID
                    WHERE p.Name = ? AND LOWER(COALESCE(a.Name, '')) = LOWER(?)
                """

                cursor = conn.execute(query, (playlist_name, artist_name))
                row = cursor.fetchone()
                return row[0] > 0 if row else False

        return nowplaying.utils.sqlite.retry_sqlite_operation(_query)

    async def test_connection(self) -> bool:
        """
        Test database connectivity

        Returns:
            True if connection successful, False otherwise
        """
        try:
            await self.get_recent_track()
            return True
        except RekordboxError:
            return False
