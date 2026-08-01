#!/usr/bin/env python3
"""Test Rekordbox plugin"""
# pylint: disable=protected-access,missing-function-docstring,redefined-outer-name

import base64
import json
import pathlib
import sys
import unittest.mock
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from Crypto.Cipher import Blowfish

import nowplaying.rekordbox.config
import nowplaying.rekordbox.database
import nowplaying.rekordbox.plugin
import nowplaying.rekordbox.types

_TEST_KEY = "0123456789abcdef" * 4  # valid 64-char hex key for tests


def _make_dp_blob(plaintext: str) -> str:
    """Encrypt plaintext the same way Rekordbox's options.json 'dp' field is
    encrypted, so tests can exercise a real decrypt round-trip."""
    magic = nowplaying.rekordbox.config._decode_secret(
        nowplaying.rekordbox.config._RB6_MAGIC_BLOB
    ).encode()
    cipher = Blowfish.new(magic, Blowfish.MODE_ECB)
    data = plaintext.encode("utf-8")
    pad_len = 8 - (len(data) % 8)
    padded = data + bytes([pad_len]) * pad_len
    return base64.b64encode(cipher.encrypt(padded)).decode()


class MockSqlCipher:  # pylint: disable=too-few-public-methods
    """Mock sqlcipher3 for testing"""

    def __init__(self, mock_data=None):
        self.mock_data = mock_data or {}
        self.executed_queries = []
        self.executed_pragmas = []

    def connect(self, _db_path):
        return MockConnection(self)

    class dbapi2:  # pylint: disable=too-few-public-methods,invalid-name
        """Minimal dbapi2 shim."""

        class OperationalError(Exception):
            """Raised on operational errors."""


class MockConnection:
    """Mock database connection"""

    def __init__(self, sqlcipher):
        self.sqlcipher = sqlcipher
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        return False

    def execute(self, query, params=None):
        if query.startswith("PRAGMA"):
            self.sqlcipher.executed_pragmas.append(query)
            return MockCursor([])

        self.sqlcipher.executed_queries.append((query, params))

        if "djmdSongHistory" in query and "ORDER BY h.created_at DESC" in query:
            if "history_data" in self.sqlcipher.mock_data:
                return MockCursor(
                    [
                        (
                            "hist123",
                            "Test Song",
                            "Test Artist",
                            "Test Album",
                            "Electronic",
                            12800,
                            240,
                            1,
                            1,
                            2023,
                            320,
                            16,
                            44100,
                            "test.mp3",
                            "/path/to/file",
                            "image.jpg",
                            5,
                            3,
                            "Great track",
                            "Cm",
                            "Test Label",
                            "Test Composer",
                            "Test Lyricist",
                            "ISRC123",
                            5000000,
                            1,
                        )
                    ]
                )
        elif "djmdPlaylist" in query and "WHERE Name IS NOT NULL" in query:
            if "playlist_data" in self.sqlcipher.mock_data:
                return MockCursor([("playlist1", "House Music"), ("playlist2", "Techno Classics")])
        elif "djmdSongPlaylist" in query and "ORDER BY RANDOM()" in query:
            if params and params[0] in ["House Music", "Techno Classics"]:
                return MockCursor(
                    [
                        (
                            "content456",
                            "Random Song",
                            "Random Artist",
                            "Random Album",
                            "House",
                            12600,
                            300,
                            2,
                            1,
                            2022,
                            256,
                            16,
                            44100,
                            "random.mp3",
                            "/path/random",
                            "random.jpg",
                            4,
                            1,
                            "Random comment",
                            "Am",
                            "Random Label",
                            "Random Composer",
                            None,
                            "ISRC456",
                            4500000,
                            1,
                        )
                    ]
                )

        return MockCursor([])

    def close(self):
        self.closed = True


class MockCursor:
    """Mock database cursor"""

    def __init__(self, data):
        self.data = data
        self.description = None

    def fetchone(self):
        return self.data[0] if self.data else None

    def fetchall(self):
        return self.data


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _db_reader(mock_database_path, mock_data=None):
    """Yield (mock_sq, reader) with sqlite and db-path patched for the duration."""
    mock_sq = MockSqlCipher(mock_data or {})
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    with (
        unittest.mock.patch.object(
            config_reader, "get_database_path", return_value=mock_database_path
        ),
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sq),
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        await reader.initialize(custom_key=_TEST_KEY)
        yield mock_sq, reader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rekordbox_bootstrap(bootstrap):
    """Bootstrap test with Rekordbox configuration"""
    config = bootstrap
    config.cparser.sync()
    yield config


@pytest.fixture
def mock_sqlcipher():
    """Empty MockSqlCipher instance"""
    return MockSqlCipher()


@pytest.fixture
def mock_database_path(tmp_path):
    """Temporary database file"""
    db_path = tmp_path / "test_master.db"
    db_path.touch()
    return db_path


@pytest_asyncio.fixture
async def rekordbox_plugin(rekordbox_bootstrap, mock_database_path):
    """Rekordbox plugin with mocked DB path and test key"""
    config = rekordbox_bootstrap
    config.cparser.setValue("rekordbox/custom_key", _TEST_KEY)
    with unittest.mock.patch(
        "nowplaying.rekordbox.config.ConfigReader.get_database_path",
        return_value=mock_database_path,
    ):
        plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=config)
        yield plugin


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX path only")
def test_config_data_path_posix():
    config = nowplaying.rekordbox.config.ConfigReader()
    path = config.get_data_path()
    assert path.parts[-3:] == ("Library", "Pioneer", "rekordbox")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path only")
def test_config_data_path_windows_appdata():
    config = nowplaying.rekordbox.config.ConfigReader()
    with unittest.mock.patch.dict("os.environ", {"APPDATA": "C:\\AppData\\Roaming"}):
        path = config.get_data_path()
    assert path.parts[-2:] == ("Pioneer", "rekordbox")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path only")
def test_config_data_path_windows_fallback(monkeypatch):
    config = nowplaying.rekordbox.config.ConfigReader()
    monkeypatch.delenv("APPDATA", raising=False)
    path = config.get_data_path()
    assert path.parts[-4:] == ("AppData", "Roaming", "Pioneer", "rekordbox")


def test_config_get_password_missing_options_file():
    """get_password() returns empty string when options.json doesn't exist"""
    config = nowplaying.rekordbox.config.ConfigReader()
    with unittest.mock.patch(
        "nowplaying.rekordbox.config._get_options_path",
        return_value=pathlib.Path("/nonexistent/options.json"),
    ):
        password = config.get_password()
    assert password == ""


@pytest.mark.parametrize("app_ver", ["6.8.5", "7.1.4"])
def test_config_get_password_decrypts_dp_regardless_of_version(tmp_path, app_ver):
    """get_password() decrypts a valid 'dp' field regardless of app_ver.

    RB6 and RB7 installs upgraded from RB6 both carry this field; only a
    fresh RB7 install may lack it, which callers must handle separately
    by validating the returned key actually opens the database.
    """
    options_file = tmp_path / "options.json"
    options_file.write_text(
        json.dumps({"options": [["dp", _make_dp_blob(_TEST_KEY)], ["app_ver", app_ver]]})
    )
    config = nowplaying.rekordbox.config.ConfigReader()
    with unittest.mock.patch(
        "nowplaying.rekordbox.config._get_options_path",
        return_value=options_file,
    ):
        assert config.get_password() == _TEST_KEY


def test_config_get_password_undecryptable_dp_returns_empty(tmp_path):
    """get_password() gracefully returns empty string when 'dp' can't be decrypted"""
    options_file = tmp_path / "options.json"
    options_file.write_text(
        '{"options":[["db-path","/tmp/master.db"],["dp","ignored"],["app_ver","7.1.4"]]}'
    )
    config = nowplaying.rekordbox.config.ConfigReader()
    with unittest.mock.patch(
        "nowplaying.rekordbox.config._get_options_path",
        return_value=options_file,
    ):
        password = config.get_password()
    assert password == ""


def test_config_get_database_path_from_options(tmp_path):
    """get_database_path() reads db-path from options.json when available"""
    db_path = tmp_path / "master.db"
    options_file = tmp_path / "options.json"
    options_file.write_text(
        json.dumps({"options": [["db-path", str(db_path)], ["app_ver", "7.1.4"]]})
    )
    config = nowplaying.rekordbox.config.ConfigReader()
    with unittest.mock.patch(
        "nowplaying.rekordbox.config._get_options_path",
        return_value=options_file,
    ):
        result = config.get_database_path()
    assert result == db_path


# ---------------------------------------------------------------------------
# Types tests
# ---------------------------------------------------------------------------


def _make_track(**kwargs):
    defaults = {
        "identifier": "test123",
        "title": "Test Song",
        "artist": "Test Artist",
        "album": "Test Album",
        "genre": "Electronic",
        "bpm": 128,
        "duration": 240,
        "track_no": 1,
        "disc_no": 1,
        "year": 2023,
        "bitrate": 320,
        "bit_depth": 16,
        "sample_rate": 44100,
        "file_name": "test.mp3",
        "folder_path": "/test/path",
        "image_path": None,
        "rating": 5,
        "play_count": 10,
        "comments": "Great track",
        "key": "Cm",
        "label": "Test Label",
        "composer": "Test Composer",
        "lyricist": "Test Lyricist",
        "isrc": "ISRC123",
        "file_size": 5000000,
        "file_type": 1,
    }
    defaults.update(kwargs)
    return nowplaying.rekordbox.types.RekordboxTrack(**defaults)


def test_types_track_creation():
    track = _make_track()
    assert track.identifier == "test123"
    assert track.title == "Test Song"
    assert track.artist == "Test Artist"
    assert track.bpm == 128
    assert track.composer == "Test Composer"
    assert track.lyricist == "Test Lyricist"


def test_types_track_to_metadata():
    track = _make_track()
    metadata = track.to_metadata()

    assert metadata["title"] == "Test Song"
    assert metadata["artist"] == "Test Artist"
    assert metadata["album"] == "Test Album"
    assert metadata["genre"] == "Electronic"
    assert metadata["year"] == "2023"
    assert metadata["duration"] == 240
    assert metadata["track"] == "1"
    assert metadata["disc"] == "1"
    assert metadata["bpm"] == "128"
    assert metadata["key"] == "Cm"
    assert metadata["label"] == "Test Label"
    assert metadata["composer"] == "Test Composer"
    assert metadata["lyricist"] == "Test Lyricist"
    assert pathlib.Path(metadata["filename"]) == pathlib.Path("/test/path") / "test.mp3"
    assert metadata["bitrate"] == "320"
    assert metadata["comments"] == "Great track"
    assert metadata["isrc"] == ["ISRC123"]


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_initialization(mock_database_path):
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    mock_sq = MockSqlCipher()
    with (
        unittest.mock.patch.object(
            config_reader, "get_database_path", return_value=mock_database_path
        ),
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sq),
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        await reader.initialize(custom_key=_TEST_KEY)

    assert reader.database_path == mock_database_path
    assert reader.encryption_key == _TEST_KEY


@pytest.mark.asyncio
async def test_database_get_recent_track_with_history(mock_database_path):
    async with _db_reader(mock_database_path, {"history_data": True}) as (mock_sq, reader):
        track = await reader.get_recent_track()

    assert track is not None
    assert track.title == "Test Song"
    assert track.artist == "Test Artist"
    assert track.album == "Test Album"
    assert track.bpm == 128.0
    assert track.composer == "Test Composer"
    assert track.lyricist == "Test Lyricist"

    query_sql = mock_sq.executed_queries[0][0]
    assert "FROM djmdSongHistory h" in query_sql
    assert "JOIN djmdContent c ON h.ContentID = c.ID" in query_sql


@pytest.mark.asyncio
async def test_database_get_recent_track_no_history(mock_database_path):
    async with _db_reader(mock_database_path) as (_, reader):
        track = await reader.get_recent_track()

    assert track is None


@pytest.mark.asyncio
async def test_database_get_playlists(mock_database_path):
    async with _db_reader(mock_database_path, {"playlist_data": True}) as (_, reader):
        playlists = await reader.get_playlists()

    assert len(playlists) == 2
    assert playlists[0] == ("playlist1", "House Music")
    assert playlists[1] == ("playlist2", "Techno Classics")


@pytest.mark.asyncio
async def test_database_get_random_track_from_playlist(mock_database_path):
    async with _db_reader(mock_database_path) as (mock_sq, reader):
        track = await reader.get_random_track_from_playlist("House Music")

    assert track is not None
    assert track.title == "Random Song"
    assert track.artist == "Random Artist"
    assert track.genre == "House"
    assert track.bpm == 126.0

    query_sql, params = mock_sq.executed_queries[0]
    assert "FROM djmdSongPlaylist sp" in query_sql
    assert "ORDER BY RANDOM()" in query_sql
    assert params == ("House Music",)


@pytest.mark.asyncio
async def test_database_connection_failure(mock_database_path):
    """A connection failure during the key-validation query now surfaces from
    initialize() itself rather than later from get_recent_track()."""
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    mock_sqlite = unittest.mock.Mock()
    mock_sqlite.connect.side_effect = Exception("Connection failed")
    with (
        unittest.mock.patch.object(
            config_reader, "get_database_path", return_value=mock_database_path
        ),
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sqlite),
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        with pytest.raises(nowplaying.rekordbox.types.RekordboxError):
            await reader.initialize(custom_key=_TEST_KEY)


@pytest.mark.asyncio
async def test_database_missing_file():
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    missing_path = pathlib.Path("/nonexistent/master.db")
    with unittest.mock.patch.object(config_reader, "get_database_path", return_value=missing_path):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        with pytest.raises(nowplaying.rekordbox.types.RekordboxError, match="database not found"):
            await reader.initialize(custom_key=_TEST_KEY)


@pytest.mark.asyncio
async def test_database_no_key_raises():
    """initialize() raises when no key is supplied and get_password() returns empty"""
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    with unittest.mock.patch.object(config_reader, "get_password", return_value=""):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        with pytest.raises(nowplaying.rekordbox.types.RekordboxError, match="No database key"):
            await reader.initialize()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_key",
    [
        "notahexstring",
        "0" * 16,  # too short (16 chars)
        "0" * 66,  # too long (66 chars)
        "0" * 62 + "ZZ",  # non-hex chars at end
    ],
)
async def test_database_invalid_key_rejected(bad_key):
    """initialize() raises when key is not a valid 64-character hex string"""
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
    with pytest.raises(nowplaying.rekordbox.types.RekordboxError, match="64-character"):
        await reader.initialize(custom_key=bad_key)


@pytest.mark.asyncio
async def test_database_playlist_not_found(mock_database_path):
    async with _db_reader(mock_database_path) as (_, reader):
        track = await reader.get_random_track_from_playlist("Nonexistent Playlist")

    assert track is None


# ---------------------------------------------------------------------------
# Plugin tests
# ---------------------------------------------------------------------------


def test_plugin_creation(rekordbox_bootstrap):
    config = rekordbox_bootstrap
    plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=config)
    assert plugin.displayname == "Rekordbox"
    assert plugin.config_reader is not None
    assert plugin.database_reader is not None
    assert not plugin._running


def test_plugin_defaults(rekordbox_plugin):
    mock_settings = unittest.mock.Mock()
    rekordbox_plugin.defaults(mock_settings)
    mock_settings.setValue.assert_any_call("rekordbox/artist_query_scope", "entire_library")
    mock_settings.setValue.assert_any_call("rekordbox/selected_playlists", "")


def test_plugin_settings_ui_methods(rekordbox_plugin):
    mock_widget = unittest.mock.Mock()
    mock_widget.rekordbox_custom_key_lineedit.text.return_value = ""
    mock_widget.rekordbox_artist_scope_combo.currentText.return_value = "Entire Library"
    mock_widget.rekordbox_selected_playlists_lineedit.text.return_value = ""
    mock_uihelp = unittest.mock.Mock()

    rekordbox_plugin.connect_settingsui(mock_widget, mock_uihelp)
    rekordbox_plugin.load_settingsui(mock_widget)
    rekordbox_plugin.save_settingsui(mock_widget)
    rekordbox_plugin.verify_settingsui(mock_widget)
    rekordbox_plugin.desc_settingsui(mock_widget)

    mock_widget.setText.assert_called_once()
    call_args = mock_widget.setText.call_args[0][0]
    assert "play history" in call_args
    assert "Performance Mode" in call_args


def test_plugin_mix_modes(rekordbox_plugin):
    assert rekordbox_plugin.validmixmodes() == ["newest"]
    assert rekordbox_plugin.getmixmode() == "newest"
    assert rekordbox_plugin.setmixmode("oldest") == "newest"


@pytest.mark.asyncio
async def test_plugin_lifecycle(rekordbox_plugin, mock_sqlcipher):
    with unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sqlcipher):
        await rekordbox_plugin.start(testmode=True)
        assert rekordbox_plugin._running
        assert rekordbox_plugin.observer is not None

        await rekordbox_plugin.stop()
        assert not rekordbox_plugin._running


@pytest.mark.asyncio
async def test_plugin_get_playing_track(rekordbox_plugin, mock_sqlcipher):
    with unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sqlcipher):
        await rekordbox_plugin.start(testmode=True)

        track = await rekordbox_plugin.database_reader.get_recent_track()
        if track and rekordbox_plugin.database_reader.has_track_changed(track):
            rekordbox_plugin._current_track = track.to_metadata()

        metadata = await rekordbox_plugin.getplayingtrack()
        assert isinstance(metadata, dict)
        if metadata:
            assert "title" in metadata
            assert "artist" in metadata

        await rekordbox_plugin.stop()


@pytest.mark.asyncio
async def test_plugin_get_random_track(rekordbox_plugin, mock_sqlcipher):
    with unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sqlcipher):
        await rekordbox_plugin.start(testmode=True)
        random_track = await rekordbox_plugin.getrandomtrack("House Music")
        assert random_track == "Random Artist - Random Song"
        await rekordbox_plugin.stop()


@pytest.mark.asyncio
async def test_plugin_start_fails_when_key_does_not_validate(rekordbox_plugin):
    """start() propagates a RekordboxError when the configured key can't
    actually open the database, instead of silently reporting success."""
    mock_sqlite = unittest.mock.Mock()
    mock_sqlite.connect.side_effect = Exception("file is not a database")
    with (
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sqlite),
        pytest.raises(nowplaying.rekordbox.types.RekordboxError),
    ):
        await rekordbox_plugin.start(testmode=True)
    assert not rekordbox_plugin._running


@pytest.mark.asyncio
async def test_plugin_components_connected(mock_database_path):
    """Plugin wires config_reader into database_reader at construction"""
    mock_config = unittest.mock.Mock()
    mock_config.cparser = unittest.mock.Mock()
    with unittest.mock.patch(
        "nowplaying.rekordbox.config.ConfigReader.get_database_path",
        return_value=mock_database_path,
    ):
        plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=mock_config)

    assert plugin.config_reader is not None
    assert plugin.database_reader is not None
    assert plugin.database_reader.config_reader is plugin.config_reader


# ---------------------------------------------------------------------------
# detect() / install() tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path_exists,expected", [(True, True), (False, False)])
def test_plugin_detect(rekordbox_bootstrap, path_exists, expected):
    plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=rekordbox_bootstrap)
    mock_path = unittest.mock.Mock()
    mock_path.exists.return_value = path_exists
    with unittest.mock.patch.object(plugin.config_reader, "get_data_path", return_value=mock_path):
        assert plugin.detect() is expected


def test_plugin_detect_exception_returns_false(rekordbox_bootstrap):
    plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=rekordbox_bootstrap)
    with unittest.mock.patch.object(
        plugin.config_reader, "get_data_path", side_effect=OSError("no access")
    ):
        assert plugin.detect() is False


def test_plugin_install_writes_config(rekordbox_bootstrap):
    plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=rekordbox_bootstrap)
    with unittest.mock.patch.object(plugin, "detect", return_value=True):
        result = plugin.install()
    assert result is True
    assert rekordbox_bootstrap.cparser.value("settings/input") == "rekordbox"


def test_plugin_install_detect_fails(rekordbox_bootstrap):
    plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=rekordbox_bootstrap)
    with unittest.mock.patch.object(plugin, "detect", return_value=False):
        result = plugin.install()
    assert result is False


# ---------------------------------------------------------------------------
# End-to-end BPM scaling test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_bpm_scaling_end_to_end(mock_database_path):
    """Raw DB BPM (stored ×100) is divided at construction and serialised without trailing zeros"""
    async with _db_reader(mock_database_path, {"history_data": True}) as (_, reader):
        track = await reader.get_recent_track()

    assert track is not None
    assert track.bpm == 128.0
    assert track.to_metadata()["bpm"] == "128"
