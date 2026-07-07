#!/usr/bin/env python3
"""Test Rekordbox plugin"""
# pylint: disable=protected-access

import pathlib
import unittest.mock

import pytest
import pytest_asyncio

import nowplaying.rekordbox.config
import nowplaying.rekordbox.database
import nowplaying.rekordbox.plugin
import nowplaying.rekordbox.types


class MockSqlCipher:
    """Mock sqlcipher3 for testing"""

    def __init__(self, mock_data=None):
        self.mock_data = mock_data or {}
        self.executed_queries = []
        self.executed_pragmas = []

    def connect(self, db_path):
        return MockConnection(self)

    class dbapi2:
        class OperationalError(Exception):
            pass


class MockConnection:
    """Mock database connection"""

    def __init__(self, sqlcipher):
        self.sqlcipher = sqlcipher
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
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
    """Rekordbox plugin with mocked DB path"""
    config = rekordbox_bootstrap
    with unittest.mock.patch(
        "nowplaying.rekordbox.config.ConfigReader.get_database_path",
        return_value=mock_database_path,
    ):
        plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=config)
        yield plugin


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


def test_config_data_path_macos():
    config = nowplaying.rekordbox.config.ConfigReader()
    with unittest.mock.patch("os.name", "posix"):
        path = config.get_data_path()
    assert "Library/Pioneer/rekordbox" in str(path)


def test_config_known_password_is_valid_hex():
    config = nowplaying.rekordbox.config.ConfigReader()
    password = config.get_known_password()
    assert len(password) == 64
    assert all(c in "0123456789abcdef" for c in password)


def test_config_get_password_rb7_fallback():
    """get_password() returns valid RB7 key when options.json is missing"""
    config = nowplaying.rekordbox.config.ConfigReader()
    with unittest.mock.patch(
        "nowplaying.rekordbox.config._get_options_path",
        return_value=pathlib.Path("/nonexistent/options.json"),
    ):
        password = config.get_password()
    assert len(password) == 64
    assert all(c in "0123456789abcdef" for c in password)


def test_config_get_password_rb7_from_options(tmp_path):
    """get_password() returns RB7 key when options.json reports app_ver=7.x"""
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
    assert len(password) == 64
    assert all(c in "0123456789abcdef" for c in password)


def test_config_get_database_path_from_options(tmp_path):
    """get_database_path() reads db-path from options.json when available"""
    db_path = tmp_path / "master.db"
    options_file = tmp_path / "options.json"
    options_file.write_text(f'{{"options":[["db-path","{db_path}"],["app_ver","7.1.4"]]}}')
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
    defaults = dict(
        identifier="test123",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        genre="Electronic",
        bpm=128,
        duration=240,
        track_no=1,
        disc_no=1,
        year=2023,
        bitrate=320,
        bit_depth=16,
        sample_rate=44100,
        file_name="test.mp3",
        folder_path="/test/path",
        image_path=None,
        rating=5,
        play_count=10,
        comments="Great track",
        key="Cm",
        label="Test Label",
        composer="Test Composer",
        lyricist="Test Lyricist",
        isrc="ISRC123",
        file_size=5000000,
        file_type=1,
    )
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
    assert metadata["filename"] == "test.mp3"
    assert metadata["bitrate"] == "320"
    assert metadata["comments"] == "Great track"
    assert metadata["isrc"] == ["ISRC123"]


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_initialization(mock_database_path):
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    with unittest.mock.patch.object(
        config_reader, "get_database_path", return_value=mock_database_path
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        await reader.initialize()

    assert reader.database_path == mock_database_path
    assert reader.encryption_key is not None
    assert len(reader.encryption_key) == 64


@pytest.mark.asyncio
async def test_database_get_recent_track_with_history(mock_database_path):
    mock_sq = MockSqlCipher({"history_data": True})
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    with (
        unittest.mock.patch.object(
            config_reader, "get_database_path", return_value=mock_database_path
        ),
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sq),
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        await reader.initialize()
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
    mock_sq = MockSqlCipher()
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    with (
        unittest.mock.patch.object(
            config_reader, "get_database_path", return_value=mock_database_path
        ),
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sq),
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        await reader.initialize()
        track = await reader.get_recent_track()

    assert track is None


@pytest.mark.asyncio
async def test_database_get_playlists(mock_database_path):
    mock_sq = MockSqlCipher({"playlist_data": True})
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    with (
        unittest.mock.patch.object(
            config_reader, "get_database_path", return_value=mock_database_path
        ),
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sq),
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        await reader.initialize()
        playlists = await reader.get_playlists()

    assert len(playlists) == 2
    assert playlists[0] == ("playlist1", "House Music")
    assert playlists[1] == ("playlist2", "Techno Classics")


@pytest.mark.asyncio
async def test_database_get_random_track_from_playlist(mock_database_path):
    mock_sq = MockSqlCipher()
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    with (
        unittest.mock.patch.object(
            config_reader, "get_database_path", return_value=mock_database_path
        ),
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sq),
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        await reader.initialize()
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
        await reader.initialize()
        with pytest.raises(nowplaying.rekordbox.types.RekordboxError):
            await reader.get_recent_track()


@pytest.mark.asyncio
async def test_database_missing_file():
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    missing_path = pathlib.Path("/nonexistent/master.db")
    with unittest.mock.patch.object(config_reader, "get_database_path", return_value=missing_path):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        with pytest.raises(nowplaying.rekordbox.types.RekordboxError, match="database not found"):
            await reader.initialize()


@pytest.mark.asyncio
async def test_database_playlist_not_found(mock_database_path):
    mock_sq = MockSqlCipher()
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    with (
        unittest.mock.patch.object(
            config_reader, "get_database_path", return_value=mock_database_path
        ),
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sq),
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        await reader.initialize()
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
    assert "1+ minutes" in call_args


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


def test_plugin_detect_path_exists(rekordbox_bootstrap):
    plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=rekordbox_bootstrap)
    mock_path = unittest.mock.Mock()
    mock_path.exists.return_value = True
    with unittest.mock.patch.object(plugin.config_reader, "get_data_path", return_value=mock_path):
        assert plugin.detect() is True


def test_plugin_detect_path_missing(rekordbox_bootstrap):
    plugin = nowplaying.rekordbox.plugin.RekordboxPlugin(config=rekordbox_bootstrap)
    mock_path = unittest.mock.Mock()
    mock_path.exists.return_value = False
    with unittest.mock.patch.object(plugin.config_reader, "get_data_path", return_value=mock_path):
        assert plugin.detect() is False


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
    mock_sq = MockSqlCipher({"history_data": True})  # mock returns raw bpm=12800
    config_reader = nowplaying.rekordbox.config.ConfigReader()
    with (
        unittest.mock.patch.object(
            config_reader, "get_database_path", return_value=mock_database_path
        ),
        unittest.mock.patch("nowplaying.rekordbox.database.sqlite", mock_sq),
    ):
        reader = nowplaying.rekordbox.database.DatabaseReader(config_reader)
        await reader.initialize()
        track = await reader.get_recent_track()

    assert track is not None
    assert track.bpm == 128.0
    assert track.to_metadata()["bpm"] == "128"
