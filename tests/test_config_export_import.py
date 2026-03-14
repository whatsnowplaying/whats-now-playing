#!/usr/bin/env python3
"""Tests for configuration export/import functionality"""

import json
import pathlib
import sys
import tempfile

import pytest

import nowplaying.utils.config_json


@pytest.fixture
def temp_config(bootstrap):
    """Create a test configuration with some sample settings"""
    config = bootstrap

    # Set some test values to export/import
    config.cparser.setValue("settings/delay", "2.5")
    config.cparser.setValue("settings/loglevel", "INFO")
    config.cparser.setValue("artistextras/enabled", True)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("serato/libpath", "/test/path/to/serato")
    config.cparser.setValue("textoutput/file", "/test/output.txt")
    config.cparser.setValue("weboutput/httpport", "9000")

    # Set some sensitive data
    config.cparser.setValue("discogs/apikey", "discogs_key_12345")  # pragma: allowlist secret
    # pragma: allowlist secret
    config.cparser.setValue("twitchbot/chattoken", "oauth:test_token_67890")

    # Set some runtime state that should be excluded
    config.cparser.setValue("settings/initialized", True)
    config.cparser.setValue("settings/lastsavedate", "20241214123456")
    config.cparser.setValue("control/paused", False)
    config.cparser.setValue("testmode/enabled", True)

    config.cparser.sync()
    return config


def test_export_config_basic(temp_config):  # pylint: disable=redefined-outer-name
    """Test basic export functionality"""
    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "test_export.json"

        # Export the configuration
        result = temp_config.export_config(export_path)
        assert result is True
        assert export_path.exists()

        # Load and verify the exported JSON
        exported_data = json.loads(export_path.read_text())

        # Check metadata
        assert "_export_info" in exported_data
        export_info = exported_data["_export_info"]
        assert "version" in export_info
        assert "export_date" in export_info
        assert "warning" in export_info

        # Check that user settings are included
        assert exported_data["settings/delay"] == "2.5"
        assert exported_data["settings/loglevel"] == "INFO"
        assert exported_data["artistextras/enabled"] is True
        assert exported_data["serato/libpath"] == "/test/path/to/serato"

        # Check that sensitive data is included (as required for version upgrades)
        assert exported_data["discogs/apikey"] == "discogs_key_12345"  # pragma: allowlist secret
        assert exported_data["twitchbot/chattoken"] == "oauth:test_token_67890"


def test_export_excludes_runtime_state(temp_config):  # pylint: disable=redefined-outer-name
    """Test that runtime state is excluded from export"""
    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "test_export.json"

        result = temp_config.export_config(export_path)
        assert result is True

        exported_data = json.loads(export_path.read_text())

        # Check that runtime state is excluded
        assert "settings/lastsavedate" not in exported_data
        assert "control/paused" not in exported_data
        assert "testmode/enabled" not in exported_data


def test_export_file_permissions(temp_config):  # pylint: disable=redefined-outer-name
    """Test that exported file has restrictive permissions"""
    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "test_export.json"

        result = temp_config.export_config(export_path)
        assert result is True

        # Check file permissions - Windows and Unix handle this differently
        if sys.platform == "win32":
            # On Windows, just verify the file exists and is readable by owner
            # Windows doesn't support Unix-style permission bits the same way
            assert export_path.exists()
            assert export_path.is_file()
            # Try to read the file to ensure it's accessible
            assert export_path.read_text()
        else:
            # On Unix-like systems, check for restrictive permissions (user read/write only)
            file_mode = export_path.stat().st_mode & 0o777
            assert file_mode == 0o600


def test_import_config_basic(temp_config, tmp_path):  # pylint: disable=redefined-outer-name
    """Test basic import functionality"""
    # Use real paths so the parent-exists check passes
    serato_dir = tmp_path / "serato"
    serato_dir.mkdir()
    output_file = tmp_path / "output.txt"

    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "test_config.json"

        # Create test import data
        import_data = {
            "_export_info": {
                "version": "4.2.0",
                "export_date": "2024-12-14 12:34:56",
                "application": "NowPlaying",
                "organization": "WhatsNowPlaying",
                "warning": "Contains sensitive data",
            },
            "settings/delay": "3.0",
            "settings/loglevel": "WARNING",
            "artistextras/enabled": False,
            "musicbrainz/enabled": True,
            "serato/libpath": str(serato_dir),
            "discogs/apikey": "imported_discogs_key",  # pragma: allowlist secret
            "textoutput/file": str(output_file),
        }

        # Write test data
        export_path.write_text(json.dumps(import_data, indent=2))

        # Import the configuration
        result = temp_config.import_config(export_path)
        assert result is True

        # Verify imported settings
        temp_config.cparser.sync()
        assert temp_config.cparser.value("settings/delay") == "3.0"
        assert temp_config.cparser.value("settings/loglevel") == "WARNING"
        assert temp_config.cparser.value("artistextras/enabled", type=bool) is False
        assert temp_config.cparser.value("musicbrainz/enabled", type=bool) is True
        assert temp_config.cparser.value("serato/libpath") == str(serato_dir)
        # pragma: allowlist secret
        assert temp_config.cparser.value("discogs/apikey") == "imported_discogs_key"


def test_import_skips_nonexistent_paths(temp_config):  # pylint: disable=redefined-outer-name
    """Paths from another OS that don't exist on this system are skipped on import"""
    with tempfile.TemporaryDirectory() as temp_dir:
        import_path = pathlib.Path(temp_dir) / "cross_os.json"

        # Unix-style paths: non-absolute on Windows (no drive letter), so always rejected there.
        # On macOS/Linux they are absolute but the parent directories don't exist.
        # Windows-style path: non-absolute on macOS/Linux (no leading /), so always rejected there.
        # On Windows it is absolute, but the parent directory is deterministically non-existent.
        import_data = {
            "_export_info": {"version": "5.0.0"},
            "settings/delay": "1.0",
            "serato/libpath": "/Users/someuser/Music/Serato",
            "textoutput/file": "/Users/someuser/Documents/nowplaying.txt",
            "weboutput/htmltemplate": "C:\\WNPTESTNONEXISTENT\\templates\\np.htm",
        }
        import_path.write_text(json.dumps(import_data))

        result = temp_config.import_config(import_path)
        assert result is True

        temp_config.cparser.sync()
        # Non-path setting imported normally
        assert temp_config.cparser.value("settings/delay") == "1.0"
        # Path settings from another OS are NOT applied (bad cross-OS paths are skipped).
        # Keys may fall back to system-scope defaults after import clears the user scope;
        # we only verify the imported values were rejected.
        assert temp_config.cparser.value("serato/libpath") != "/Users/someuser/Music/Serato"
        assert (
            temp_config.cparser.value("textoutput/file")
            != "/Users/someuser/Documents/nowplaying.txt"
        )
        assert (
            temp_config.cparser.value("weboutput/htmltemplate")
            != "C:\\WNPTESTNONEXISTENT\\templates\\np.htm"
        )

        # Warnings file should be written next to the import file
        warnings_file = import_path.with_name(import_path.stem + "_import_warnings.txt")
        assert warnings_file.exists()
        warnings_text = warnings_file.read_text()
        assert "serato/libpath" in warnings_text
        assert "textoutput/file" in warnings_text


def test_import_remaps_home_path(temp_config):  # pylint: disable=redefined-outer-name
    """Paths from a different home directory are remapped to the current home on import"""
    home = str(pathlib.Path.home())

    # Build a fake exported path rooted at a fake home — deterministic, not relying on tmp_path
    # location relative to the real home directory.
    fake_home = "/home/otheruser"
    fake_subdir = "Music/Serato"
    raw_path = f"{fake_home}/{fake_subdir}"
    expected_path = f"{home}/{fake_subdir}"

    # Create the parent directory so the path-exists check on import passes
    expected_parent = pathlib.Path(expected_path).parent
    expected_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        import_path = pathlib.Path(temp_dir) / "remapped.json"
        import_data = {
            "_export_info": {
                "version": "5.1.0",
                nowplaying.utils.config_json.HOME_TOKEN: fake_home,
            },
            "serato/libpath": raw_path,
        }
        import_path.write_text(json.dumps(import_data))

        result = temp_config.import_config(import_path)
        assert result is True

        temp_config.cparser.sync()
        imported = temp_config.cparser.value("serato/libpath")
        assert imported == expected_path
        assert imported.startswith(home)
        assert not imported.startswith(fake_home)


def test_export_records_home_in_export_info(temp_config):  # pylint: disable=redefined-outer-name
    """Export records the home directory in _export_info and writes raw paths"""
    home = str(pathlib.Path.home())
    home_path = str(pathlib.Path.home() / "Music" / "Serato")
    temp_config.cparser.setValue("serato/libpath", home_path)
    temp_config.cparser.sync()

    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "export.json"
        result = temp_config.export_config(export_path)
        assert result is True

        exported = json.loads(export_path.read_text())
        # Raw path written to value (not tokenized)
        assert exported.get("serato/libpath") == home_path
        # Home directory recorded in _export_info under HOME_TOKEN key
        assert exported["_export_info"][nowplaying.utils.config_json.HOME_TOKEN] == home


def test_import_nonexistent_file(temp_config):  # pylint: disable=redefined-outer-name
    """Test importing from a nonexistent file"""
    nonexistent_path = pathlib.Path("/nonexistent/config.json")
    result = temp_config.import_config(nonexistent_path)
    assert result is False


def test_import_invalid_json(temp_config):  # pylint: disable=redefined-outer-name
    """Test importing invalid JSON"""
    with tempfile.TemporaryDirectory() as temp_dir:
        invalid_json_path = pathlib.Path(temp_dir) / "invalid.json"
        invalid_json_path.write_text("{ invalid json content")

        result = temp_config.import_config(invalid_json_path)
        assert result is False


def test_export_import_roundtrip(temp_config):  # pylint: disable=redefined-outer-name
    """Test that export followed by import preserves settings"""
    original_delay = temp_config.cparser.value("settings/delay")
    original_loglevel = temp_config.cparser.value("settings/loglevel")
    original_apikey = temp_config.cparser.value("discogs/apikey")  # pragma: allowlist secret

    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "roundtrip.json"

        # Export
        export_result = temp_config.export_config(export_path)
        assert export_result is True

        # Change some settings
        temp_config.cparser.setValue("settings/delay", "999")
        temp_config.cparser.setValue("settings/loglevel", "CRITICAL")
        temp_config.cparser.setValue("discogs/apikey", "changed_key")  # pragma: allowlist secret
        temp_config.cparser.sync()

        # Import
        import_result = temp_config.import_config(export_path)
        assert import_result is True

        # Verify original settings are restored
        temp_config.cparser.sync()
        assert temp_config.cparser.value("settings/delay") == original_delay
        assert temp_config.cparser.value("settings/loglevel") == original_loglevel
        # pragma: allowlist secret
        assert temp_config.cparser.value("discogs/apikey") == original_apikey


def test_import_clears_cache_settings(temp_config):  # pylint: disable=redefined-outer-name
    """Test that import clears cache and runtime settings before importing"""
    # Set some cache/runtime settings
    temp_config.cparser.setValue("settings/initialized", True)
    temp_config.cparser.setValue("settings/lastsavedate", "20241214000000")
    temp_config.cparser.setValue("control/paused", True)
    temp_config.cparser.sync()

    with tempfile.TemporaryDirectory() as temp_dir:
        import_path = pathlib.Path(temp_dir) / "test_import.json"

        import_data = {"_export_info": {"version": "4.2.0"}, "settings/delay": "1.5"}

        import_path.write_text(json.dumps(import_data))

        # Import
        result = temp_config.import_config(import_path)
        assert result is True

        # Verify cache settings were cleared
        temp_config.cparser.sync()
        # Default value
        assert temp_config.cparser.value("settings/lastsavedate") is None
        # Default value
        assert temp_config.cparser.value("control/paused", type=bool) is False


def test_export_handles_different_data_types(temp_config):  # pylint: disable=redefined-outer-name
    """Test that export properly handles different QSettings data types"""
    # Set various data types
    temp_config.cparser.setValue("test/string", "text_value")
    temp_config.cparser.setValue("test/int", 42)
    temp_config.cparser.setValue("test/float", 3.14)
    temp_config.cparser.setValue("test/bool", True)
    temp_config.cparser.setValue("test/list", ["item1", "item2", "item3"])
    temp_config.cparser.setValue("test/none", None)
    temp_config.cparser.sync()

    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "types_test.json"

        result = temp_config.export_config(export_path)
        assert result is True

        exported_data = json.loads(export_path.read_text())

        # Verify data types are preserved or converted appropriately
        assert exported_data["test/string"] == "text_value"
        assert exported_data["test/int"] == 42
        assert exported_data["test/float"] == 3.14
        assert exported_data["test/bool"] is True
        assert exported_data["test/list"] == ["item1", "item2", "item3"]
        assert exported_data["test/none"] is None
