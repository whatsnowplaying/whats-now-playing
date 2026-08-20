#!/usr/bin/env python3
"""tests for nowplaying.datacache.utils"""

import tempfile
import time
from pathlib import Path

import pytest

import nowplaying.datacache.utils
import nowplaying.utils.sqlite


def _insert_image_row(conn, index: int, size: int, access_count: int, now: float) -> None:
    """Insert one image row with a known size and access count."""
    conn.execute(
        """
        INSERT INTO cached_data
        (url, cachekey, identifier, data_type, provider, data_value,
         created_at, expires_at, access_count, last_accessed, data_size)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"https://example.com/{index}.jpg",
            f"key-{index}",
            "wnpmockartist",
            "artistfanart",
            "cdn",
            b"",
            now,
            now + 9999,
            access_count,
            now,
            size,
        ),
    )


@pytest.mark.parametrize(
    "limit_mb,expected_evicted,expected_remaining_mb",
    [
        (3, 2, 3),  # over limit: drop the two least-accessed
        (5, 0, 5),  # exactly at limit: nothing to do
        (99, 0, 5),  # under limit: no-op
    ],
)
def test_evict_lfu_respects_size_limit(limit_mb, expected_evicted, expected_remaining_mb):
    """Eviction drops least-frequently-used images until under the byte limit."""
    megabyte = 1024 * 1024
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        db_path = temp_path / "datacache.sqlite"
        nowplaying.datacache.utils.ensure_datacache_schema(db_path)

        now = time.time()
        with nowplaying.utils.sqlite.sqlite_connection(str(db_path)) as conn:
            for index in range(5):
                _insert_image_row(conn, index, megabyte, index, now)

        evicted = nowplaying.datacache.utils._evict_lfu(  # pylint: disable=protected-access
            db_path, limit_mb * megabyte
        )
        assert evicted == expected_evicted

        with nowplaying.utils.sqlite.sqlite_connection(str(db_path)) as conn:
            total = conn.execute(
                "SELECT SUM(data_size) FROM cached_data WHERE data_type = 'artistfanart'"
            ).fetchone()[0]
            remaining = [
                row[0]
                for row in conn.execute(
                    "SELECT access_count FROM cached_data"
                    " WHERE data_type = 'artistfanart' ORDER BY access_count"
                )
            ]
        assert total == expected_remaining_mb * megabyte
        # whatever survives must be the most-accessed entries
        assert remaining == sorted(remaining)
        if expected_evicted:
            assert min(remaining) == expected_evicted


def test_evict_lfu_leaves_api_responses_alone():
    """Only image data_types are eviction candidates."""
    megabyte = 1024 * 1024
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        db_path = temp_path / "datacache.sqlite"
        nowplaying.datacache.utils.ensure_datacache_schema(db_path)

        now = time.time()
        with nowplaying.utils.sqlite.sqlite_connection(str(db_path)) as conn:
            _insert_image_row(conn, 0, megabyte, 0, now)
            conn.execute(
                """
                INSERT INTO cached_data
                (url, cachekey, identifier, data_type, provider, data_value,
                 created_at, expires_at, access_count, last_accessed, data_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "derived://lastfm/wnpmockartist/artist.getinfo",
                    "key-api",
                    "wnpmockartist",
                    "api_response",
                    "lastfm",
                    b"{}",
                    now,
                    now + 9999,
                    0,
                    now,
                    50 * megabyte,
                ),
            )

        # limit of 0 would evict everything eligible
        nowplaying.datacache.utils._evict_lfu(db_path, 0)  # pylint: disable=protected-access

        with nowplaying.utils.sqlite.sqlite_connection(str(db_path)) as conn:
            kinds = [
                row[0] for row in conn.execute("SELECT data_type FROM cached_data ORDER BY url")
            ]
        assert kinds == ["api_response"], "API responses must survive image eviction"
