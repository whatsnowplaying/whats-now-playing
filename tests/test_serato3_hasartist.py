#!/usr/bin/env python3
# pylint: disable=redefined-outer-name,broad-exception-caught,protected-access,line-too-long
"""
Comprehensive tests for Serato3 has_tracks_by_artist with multiple database support.

Tests the complex multiple database logic that was implemented for external storage.
"""

import tempfile
import unittest.mock
from pathlib import Path

import pytest

import nowplaying.inputs.serato3


@pytest.fixture
def mock_config():
    """Create a mock config for Serato testing"""
    config = unittest.mock.MagicMock()
    config.cparser = unittest.mock.MagicMock()
    return config


@pytest.fixture
def temp_serato_dirs():
    """Create temporary Serato directory structure"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create multiple Serato library directories
        primary_lib = temp_path / "primary" / "_Serato_"
        external_lib = temp_path / "external" / "_Serato_"
        backup_lib = temp_path / "backup" / "_Serato_"

        for lib_path in [primary_lib, external_lib, backup_lib]:
            lib_path.mkdir(parents=True)
            # Create database V2 file structure
            (lib_path / "database V2").touch()

        yield {
            "primary": str(primary_lib),
            "external": str(external_lib),
            "backup": str(backup_lib),
        }


@pytest.mark.asyncio
async def test_multiple_database_paths_configuration(mock_config, temp_serato_dirs):
    """Test _get_all_database_paths method"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/libpath": temp_serato_dirs["primary"],
        "serato/additional_libpaths": f"{temp_serato_dirs['external']}\n{temp_serato_dirs['backup']}",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    paths = plugin._get_all_database_paths()

    assert len(paths) == 3
    assert temp_serato_dirs["primary"] in paths
    assert temp_serato_dirs["external"] in paths
    assert temp_serato_dirs["backup"] in paths


@pytest.mark.asyncio
async def test_multiple_database_paths_semicolon_separator(mock_config, temp_serato_dirs):
    """Test alternative semicolon separator for additional paths"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/libpath": temp_serato_dirs["primary"],
        "serato/additional_libpaths": f"{temp_serato_dirs['external']};{temp_serato_dirs['backup']}",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    paths = plugin._get_all_database_paths()

    assert len(paths) == 3
    assert temp_serato_dirs["primary"] in paths
    assert temp_serato_dirs["external"] in paths
    assert temp_serato_dirs["backup"] in paths


@pytest.mark.asyncio
async def test_empty_additional_paths(mock_config, temp_serato_dirs):
    """Test with only primary path configured"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/libpath": temp_serato_dirs["primary"],
        "serato/additional_libpaths": "",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    paths = plugin._get_all_database_paths()

    assert len(paths) == 1
    assert paths[0] == temp_serato_dirs["primary"]


@pytest.mark.asyncio
async def test_whitespace_handling_in_paths(mock_config, temp_serato_dirs):
    """Test whitespace and empty line handling in additional paths"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/libpath": temp_serato_dirs["primary"],
        "serato/additional_libpaths": f"""
        {temp_serato_dirs["external"]}

        {temp_serato_dirs["backup"]}

        """,
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    paths = plugin._get_all_database_paths()

    assert len(paths) == 3
    assert temp_serato_dirs["primary"] in paths
    assert temp_serato_dirs["external"] in paths
    assert temp_serato_dirs["backup"] in paths


@pytest.mark.asyncio
async def test_search_stops_after_finding_artist(mock_config, temp_serato_dirs):
    """Test that search stops after finding artist in any database"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/artist_query_scope": "entire_library",
        "serato/libpath": temp_serato_dirs["primary"],
        "serato/additional_libpaths": f"{temp_serato_dirs['external']}\n{temp_serato_dirs['backup']}",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    # Mock the database search to simulate finding artist in second database
    with unittest.mock.patch.object(plugin, "_has_tracks_in_entire_library") as mock_search:
        mock_search.side_effect = [False, True, False]  # Found in second database

        result = await plugin.has_tracks_by_artist("Test Artist")

        assert result is True
        assert mock_search.call_count == 2  # Should stop after finding in second DB

        # Verify the paths that were searched
        call_args = [call[0] for call in mock_search.call_args_list]
        assert call_args[0] == ("Test Artist", temp_serato_dirs["primary"])
        assert call_args[1] == ("Test Artist", temp_serato_dirs["external"])


@pytest.mark.asyncio
async def test_search_all_databases_when_not_found(mock_config, temp_serato_dirs):
    """Test that all databases are searched when artist not found"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/artist_query_scope": "entire_library",
        "serato/libpath": temp_serato_dirs["primary"],
        "serato/additional_libpaths": f"{temp_serato_dirs['external']}\n{temp_serato_dirs['backup']}",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    # Mock the database search to simulate not finding artist in any database
    with unittest.mock.patch.object(plugin, "_has_tracks_in_entire_library") as mock_search:
        mock_search.return_value = False  # Not found in any database

        result = await plugin.has_tracks_by_artist("Nonexistent Artist")

        assert result is False
        assert mock_search.call_count == 3  # Should search all three databases

        # Verify all paths were searched
        call_args = [call[0] for call in mock_search.call_args_list]
        assert call_args[0] == ("Nonexistent Artist", temp_serato_dirs["primary"])
        assert call_args[1] == ("Nonexistent Artist", temp_serato_dirs["external"])
        assert call_args[2] == ("Nonexistent Artist", temp_serato_dirs["backup"])


@pytest.mark.asyncio
async def test_selected_playlists_scope_multiple_databases(mock_config, temp_serato_dirs):
    """Test selected playlists scope across multiple databases"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/artist_query_scope": "selected_playlists",
        "serato/selected_playlists": "House,Techno",
        "serato/libpath": temp_serato_dirs["primary"],
        "serato/additional_libpaths": f"{temp_serato_dirs['external']}\n{temp_serato_dirs['backup']}",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    # Mock the playlist search across databases
    with unittest.mock.patch.object(plugin, "_has_tracks_in_selected_playlists") as mock_search:
        mock_search.return_value = True  # Found artist in playlists

        result = await plugin.has_tracks_by_artist("Test Artist")

        assert result is True
        assert mock_search.call_count == 1  # Called once, handles all databases internally

        # Verify the method was called with just the artist name
        call_args = mock_search.call_args_list[0][0]
        assert call_args == ("Test Artist",)


@pytest.mark.asyncio
async def test_no_configured_paths_returns_false(mock_config):
    """Test behavior when no library paths are configured"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/artist_query_scope": "entire_library",
        "serato/libpath": None,
        "serato/additional_libpaths": "",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    result = await plugin.has_tracks_by_artist("Any Artist")

    assert result is False


@pytest.mark.asyncio
async def test_database_error_returns_false_for_live_performance(mock_config, temp_serato_dirs):
    """Test that database errors return False gracefully (critical for live performance)"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/artist_query_scope": "entire_library",
        "serato/libpath": temp_serato_dirs["primary"],
        "serato/additional_libpaths": f"{temp_serato_dirs['external']}\n{temp_serato_dirs['backup']}",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    # Mock database search with error in first database
    with unittest.mock.patch.object(plugin, "_has_tracks_in_entire_library") as mock_search:
        mock_search.side_effect = Exception("Database error in primary")

        # Should return False, not raise exception (critical for live performance)
        try:
            result = await plugin.has_tracks_by_artist("Test Artist")
            assert result is False  # Should return False gracefully
        except Exception as exc:
            pytest.fail(
                f"Database error raised exception: {exc}. "
                f"Must handle all database errors gracefully for live performance."
            )


@pytest.mark.asyncio
async def test_critical_no_exceptions_from_multiple_database_logic(mock_config):
    """CRITICAL: Multiple database logic must never raise exceptions during live performance"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/artist_query_scope": "entire_library",
        "serato/libpath": "/nonexistent/primary/_Serato_",
        "serato/additional_libpaths": "/invalid/path1/_Serato_\n/invalid/path2/_Serato_",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.serato3.Plugin(config=mock_config)

    try:
        result = await plugin.has_tracks_by_artist("Any Artist")
        assert result is False  # Should return False, not raise exception
    except Exception as exc:
        pytest.fail(
            f"Multiple database logic raised exception: {exc}. "
            f"Must handle all database errors gracefully for live performance."
        )
