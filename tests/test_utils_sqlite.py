#!/usr/bin/env python3
"""Tests for nowplaying.utils.sqlite."""

import pathlib
import sqlite3

import pytest  # pylint: disable=import-error

import nowplaying.utils.sqlite


def _make_db(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE t(a); INSERT INTO t VALUES (1);")
    conn.close()


def test_read_only_dsn_round_trips_an_awkward_path(tmp_path):
    """Spaces and non-ASCII are ordinary in a DJ library folder."""
    db = tmp_path / "djay Pró" / "Media Library.db"
    _make_db(db)

    dsn = nowplaying.utils.sqlite.read_only_dsn(db)
    assert dsn.startswith("file:///"), f"not an absolute file URI: {dsn}"
    assert dsn.endswith("?mode=ro")

    with sqlite3.connect(dsn, uri=True) as conn:
        assert conn.execute("SELECT a FROM t").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES (2)")
    conn.close()


def test_read_only_dsn_accepts_a_relative_path(tmp_path, monkeypatch):
    """as_uri() rejects a relative path, and plugins can be holding one.

    A settings wipe leaves input plugins with paths like History/Sessions, so
    resolve() has to run first or reading the library raises ValueError instead
    of failing to find a file. Not raising mid-set is the right trade, but note
    this pins the resolve-against-CWD behaviour rather than the wipe itself
    being fixed: that path is still wrong, just quietly wrong.
    """
    _make_db(tmp_path / "Library" / "master.db")
    monkeypatch.chdir(tmp_path)

    dsn = nowplaying.utils.sqlite.read_only_dsn("Library/master.db")

    assert dsn.startswith("file:///")
    with sqlite3.connect(dsn, uri=True) as conn:
        assert conn.execute("SELECT a FROM t").fetchone() == (1,)
    conn.close()
