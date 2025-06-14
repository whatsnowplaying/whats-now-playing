#!/usr/bin/env python3
"""Tests for configuration export/import functionality"""

import json
import pathlib
import sys
import tempfile
import pytest


@pytest.fixture
def temp_config(bootstrap):
    """Create a test configuration with some sample settings"""
    config = bootstrap

    # Set some test values to export/import
    config.cparser.setValue('settings/delay', '2.5')
    config.cparser.setValue('settings/loglevel', 'INFO')
    config.cparser.setValue('artistextras/enabled', True)
    config.cparser.setValue('musicbrainz/enabled', False)
    config.cparser.setValue('serato/libpath', '/test/path/to/serato')
    config.cparser.setValue('textoutput/file', '/test/output.txt')
    config.cparser.setValue('weboutput/httpport', '9000')

    # Set some sensitive data
    config.cparser.setValue('discogs/apikey', 'discogs_key_12345')  # pragma: allowlist secret
    # pragma: allowlist secret
    config.cparser.setValue('twitchbot/chattoken', 'oauth:test_token_67890')

    # Set some runtime state that should be excluded
    config.cparser.setValue('settings/initialized', True)
    config.cparser.setValue('settings/lastsavedate', '20241214123456')
    config.cparser.setValue('control/paused', False)
    config.cparser.setValue('testmode/enabled', True)

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
        assert '_export_info' in exported_data
        export_info = exported_data['_export_info']
        assert 'version' in export_info
        assert 'export_date' in export_info
        assert 'warning' in export_info

        # Check that user settings are included
        assert exported_data['settings/delay'] == '2.5'
        assert exported_data['settings/loglevel'] == 'INFO'
        assert exported_data['artistextras/enabled'] is True
        assert exported_data['serato/libpath'] == '/test/path/to/serato'

        # Check that sensitive data is included (as required for version upgrades)
        assert exported_data['discogs/apikey'] == 'discogs_key_12345' # pragma: allowlist secret
        assert exported_data['twitchbot/chattoken'] == 'oauth:test_token_67890'


def test_export_excludes_runtime_state(temp_config):    # pylint: disable=redefined-outer-name
    """Test that runtime state is excluded from export"""
    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "test_export.json"

        result = temp_config.export_config(export_path)
        assert result is True

        exported_data = json.loads(export_path.read_text())

        # Check that runtime state is excluded
        assert 'settings/initialized' not in exported_data
        assert 'settings/lastsavedate' not in exported_data
        assert 'control/paused' not in exported_data
        assert 'testmode/enabled' not in exported_data


def test_export_file_permissions(temp_config):   # pylint: disable=redefined-outer-name
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


def test_import_config_basic(temp_config):    # pylint: disable=redefined-outer-name
    """Test basic import functionality"""
    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "test_config.json"

        # Create test import data
        import_data = {
            '_export_info': {
                'version': '4.2.0',
                'export_date': '2024-12-14 12:34:56',
                'application': 'NowPlaying',
                'organization': 'WhatsNowPlaying',
                'warning': 'Contains sensitive data'
            },
            'settings/delay': '3.0',
            'settings/loglevel': 'WARNING',
            'artistextras/enabled': False,
            'musicbrainz/enabled': True,
            'serato/libpath': '/imported/path/to/serato',
            'discogs/apikey': 'imported_discogs_key',  # pragma: allowlist secret
            'textoutput/file': '/imported/output.txt'
        }

        # Write test data
        export_path.write_text(json.dumps(import_data, indent=2))

        # Import the configuration
        result = temp_config.import_config(export_path)
        assert result is True

        # Verify imported settings
        temp_config.cparser.sync()
        assert temp_config.cparser.value('settings/delay') == '3.0'
        assert temp_config.cparser.value('settings/loglevel') == 'WARNING'
        assert temp_config.cparser.value('artistextras/enabled', type=bool) is False
        assert temp_config.cparser.value('musicbrainz/enabled', type=bool) is True
        assert temp_config.cparser.value('serato/libpath') == '/imported/path/to/serato'
        # pragma: allowlist secret
        assert temp_config.cparser.value('discogs/apikey') == 'imported_discogs_key'


def test_import_nonexistent_file(temp_config):    # pylint: disable=redefined-outer-name
    """Test importing from a nonexistent file"""
    nonexistent_path = pathlib.Path("/nonexistent/config.json")
    result = temp_config.import_config(nonexistent_path)
    assert result is False


def test_import_invalid_json(temp_config):    # pylint: disable=redefined-outer-name
    """Test importing invalid JSON"""
    with tempfile.TemporaryDirectory() as temp_dir:
        invalid_json_path = pathlib.Path(temp_dir) / "invalid.json"
        invalid_json_path.write_text("{ invalid json content")

        result = temp_config.import_config(invalid_json_path)
        assert result is False


def test_export_import_roundtrip(temp_config):  # pylint: disable=redefined-outer-name
    """Test that export followed by import preserves settings"""
    original_delay = temp_config.cparser.value('settings/delay')
    original_loglevel = temp_config.cparser.value('settings/loglevel')
    original_apikey = temp_config.cparser.value('discogs/apikey')  # pragma: allowlist secret

    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "roundtrip.json"

        # Export
        export_result = temp_config.export_config(export_path)
        assert export_result is True

        # Change some settings
        temp_config.cparser.setValue('settings/delay', '999')
        temp_config.cparser.setValue('settings/loglevel', 'CRITICAL')
        temp_config.cparser.setValue('discogs/apikey', 'changed_key')  # pragma: allowlist secret
        temp_config.cparser.sync()

        # Import
        import_result = temp_config.import_config(export_path)
        assert import_result is True

        # Verify original settings are restored
        temp_config.cparser.sync()
        assert temp_config.cparser.value('settings/delay') == original_delay
        assert temp_config.cparser.value('settings/loglevel') == original_loglevel
        # pragma: allowlist secret
        assert temp_config.cparser.value('discogs/apikey') == original_apikey


def test_import_clears_cache_settings(temp_config):  # pylint: disable=redefined-outer-name
    """Test that import clears cache and runtime settings before importing"""
    # Set some cache/runtime settings
    temp_config.cparser.setValue('settings/initialized', True)
    temp_config.cparser.setValue('settings/lastsavedate', '20241214000000')
    temp_config.cparser.setValue('control/paused', True)
    temp_config.cparser.sync()

    with tempfile.TemporaryDirectory() as temp_dir:
        import_path = pathlib.Path(temp_dir) / "test_import.json"

        import_data = {
            '_export_info': {'version': '4.2.0'},
            'settings/delay': '1.5'
        }

        import_path.write_text(json.dumps(import_data))

        # Import
        result = temp_config.import_config(import_path)
        assert result is True

        # Verify cache settings were cleared
        temp_config.cparser.sync()
        # Default value
        assert temp_config.cparser.value('settings/initialized', type=bool) is False
        assert temp_config.cparser.value('settings/lastsavedate') is None
        # Default value
        assert temp_config.cparser.value('control/paused', type=bool) is False


def test_export_handles_different_data_types(temp_config):  # pylint: disable=redefined-outer-name
    """Test that export properly handles different QSettings data types"""
    # Set various data types
    temp_config.cparser.setValue('test/string', 'text_value')
    temp_config.cparser.setValue('test/int', 42)
    temp_config.cparser.setValue('test/float', 3.14)
    temp_config.cparser.setValue('test/bool', True)
    temp_config.cparser.setValue('test/list', ['item1', 'item2', 'item3'])
    temp_config.cparser.setValue('test/none', None)
    temp_config.cparser.sync()

    with tempfile.TemporaryDirectory() as temp_dir:
        export_path = pathlib.Path(temp_dir) / "types_test.json"

        result = temp_config.export_config(export_path)
        assert result is True

        exported_data = json.loads(export_path.read_text())

        # Verify data types are preserved or converted appropriately
        assert exported_data['test/string'] == 'text_value'
        assert exported_data['test/int'] == 42
        assert exported_data['test/float'] == 3.14
        assert exported_data['test/bool'] is True
        assert exported_data['test/list'] == ['item1', 'item2', 'item3']
        assert exported_data['test/none'] is None
