#!/usr/bin/env python3
''' test remote input plugin '''

from unittest.mock import MagicMock, patch

import pytest

import nowplaying.inputs.remote
import nowplaying.db


@pytest.fixture
def remote_bootstrap(bootstrap):
    ''' bootstrap test for remote plugin '''
    config = bootstrap
    remotedb_file = config.testdir.joinpath('remote.db')
    config.cparser.setValue('remote/remotedb', str(remotedb_file))
    config.cparser.sync()
    yield config


@pytest.mark.asyncio
async def test_remote_plugin_init(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test remote plugin initialization '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    assert plugin.displayname == "Remote"
    assert str(plugin.remotedbfile) == str(config.testdir.joinpath('remote.db'))
    assert plugin.remotedb is None
    assert plugin.mixmode == "newest"
    assert plugin.metadata == {'artist': None, 'title': None, 'filename': None}
    assert plugin.observer is None


@pytest.mark.asyncio
async def test_remote_plugin_install(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test remote plugin install method '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    assert plugin.install() is False


@pytest.mark.asyncio
async def test_remote_plugin_reset_meta(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test metadata reset '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Set some metadata
    plugin.metadata = {'artist': 'Test Artist', 'title': 'Test Title', 'filename': 'test.mp3'}

    # Reset metadata
    plugin._reset_meta()  # pylint: disable=protected-access

    assert plugin.metadata == {'artist': None, 'title': None, 'filename': None}


@pytest.mark.asyncio
async def test_remote_plugin_setup_watcher(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test watcher setup '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    with patch('nowplaying.db.DBWatcher') as mock_watcher_class:
        mock_watcher = MagicMock()
        mock_watcher_class.return_value = mock_watcher

        await plugin.setup_watcher()

        mock_watcher_class.assert_called_once_with(databasefile=str(plugin.remotedbfile))
        mock_watcher.start.assert_called_once_with(
            customhandler=plugin._read_track) # pylint: disable=protected-access
        assert plugin.observer == mock_watcher


@pytest.mark.asyncio
async def test_remote_plugin_read_track_directory_event(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test _read_track with directory event '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Mock event as directory
    event = MagicMock()
    event.is_directory = True

    # Should return early for directory events
    plugin._read_track(event)  # pylint: disable=protected-access

    # Metadata should remain unchanged
    assert plugin.metadata == {'artist': None, 'title': None, 'filename': None}


@pytest.mark.asyncio
async def test_remote_plugin_read_track_no_metadata(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test _read_track with no metadata from database '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Mock event as file
    event = MagicMock()
    event.is_directory = False

    # Mock database returning None
    plugin.remotedb = MagicMock()
    plugin.remotedb.read_last_meta.return_value = None

    # Set initial metadata
    plugin.metadata = {'artist': 'Old Artist', 'title': 'Old Title', 'filename': 'old.mp3'}

    plugin._read_track(event)  # pylint: disable=protected-access

    # Should reset metadata
    assert plugin.metadata == {'artist': None, 'title': None, 'filename': None}
    plugin.remotedb.read_last_meta.assert_called_once()


@pytest.mark.asyncio
async def test_remote_plugin_read_track_with_metadata(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test _read_track with metadata from database '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Mock event as file
    event = MagicMock()
    event.is_directory = False

    # Mock database returning metadata
    new_metadata = {'artist': 'New Artist', 'title': 'New Title', 'filename': 'new.mp3'}
    plugin.remotedb = MagicMock()
    plugin.remotedb.read_last_meta.return_value = new_metadata

    plugin._read_track(event)  # pylint: disable=protected-access

    # Should update metadata
    assert plugin.metadata == new_metadata
    plugin.remotedb.read_last_meta.assert_called_once()


@pytest.mark.asyncio
async def test_remote_plugin_start(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test start method '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    with patch.object(plugin, 'setup_watcher') as mock_setup:
        await plugin.start()
        mock_setup.assert_called_once()


@pytest.mark.asyncio
async def test_remote_plugin_getplayingtrack(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test getplayingtrack method '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Set metadata
    test_metadata = {'artist': 'Test Artist', 'title': 'Test Title', 'filename': 'test.mp3'}
    plugin.metadata = test_metadata

    # Mock the database initialization in start() to avoid actual file operations
    with patch('nowplaying.db.MetadataDB'), patch('nowplaying.db.DBWatcher'):
        result = await plugin.getplayingtrack()
        assert result == test_metadata


@pytest.mark.asyncio
async def test_remote_plugin_getrandomtrack(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test getrandomtrack method '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    result = await plugin.getrandomtrack("test_playlist")
    assert result is None


@pytest.mark.asyncio
async def test_remote_plugin_stop(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test stop method '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Set up observer
    plugin.observer = MagicMock()
    plugin.metadata = {'artist': 'Test Artist', 'title': 'Test Title', 'filename': 'test.mp3'}

    await plugin.stop()

    # Should reset metadata and stop observer
    assert plugin.metadata == {'artist': None, 'title': None, 'filename': None}
    plugin.observer.stop.assert_called_once()


@pytest.mark.asyncio
async def test_remote_plugin_stop_no_observer(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test stop method when no observer exists '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # No observer set
    plugin.observer = None
    plugin.metadata = {'artist': 'Test Artist', 'title': 'Test Title', 'filename': 'test.mp3'}

    await plugin.stop()

    # Should still reset metadata
    assert plugin.metadata == {'artist': None, 'title': None, 'filename': None}


@pytest.mark.asyncio
async def test_remote_plugin_settingsui_methods(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test settings UI methods '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Mock QWidget
    qwidget = MagicMock()
    uihelp = MagicMock()

    # Test connect_settingsui
    plugin.connect_settingsui(qwidget, uihelp)
    assert plugin.qwidget == qwidget
    assert plugin.uihelp == uihelp

    # Test on_m3u_dir_button (should do nothing)
    plugin.on_m3u_dir_button()

    # Test load_settingsui (should do nothing)
    plugin.load_settingsui(qwidget)

    # Test verify_settingsui (should do nothing)
    plugin.verify_settingsui(qwidget)

    # Test save_settingsui (should do nothing)
    plugin.save_settingsui(qwidget)


@pytest.mark.asyncio
async def test_remote_plugin_desc_settingsui(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test desc_settingsui method '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Mock QWidget
    qwidget = MagicMock()

    plugin.desc_settingsui(qwidget)

    qwidget.setText.assert_called_once_with('Remote gets input from one or more other WNP setups.')


@pytest.mark.asyncio
async def test_remote_plugin_mixmode_methods(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test mixmode methods '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Test validmixmodes (inherited from InputPlugin)
    assert plugin.validmixmodes() == ['newest']

    # Test setmixmode (inherited from InputPlugin)
    assert plugin.setmixmode('oldest') == 'newest'

    # Test getmixmode (inherited from InputPlugin)
    assert plugin.getmixmode() == 'newest'


@pytest.mark.asyncio
async def test_remote_plugin_with_real_metadatadb(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test with real MetadataDB '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Create a real MetadataDB instance
    metadb = nowplaying.db.MetadataDB(databasefile=plugin.remotedbfile, initialize=True)

    # Write test metadata
    test_metadata = {'artist': 'Test Artist', 'title': 'Test Title', 'filename': 'test.mp3'}
    await metadb.write_to_metadb(metadata=test_metadata)

    # Set the database on the plugin
    plugin.remotedb = metadb

    # Test reading track
    event = MagicMock()
    event.is_directory = False

    plugin._read_track(event)  # pylint: disable=protected-access

    assert plugin.metadata['artist'] == 'Test Artist'
    assert plugin.metadata['title'] == 'Test Title'
    assert plugin.metadata['filename'] == 'test.mp3'


@pytest.mark.asyncio
async def test_remote_plugin_config_missing_remotedb(bootstrap):
    ''' test plugin when remotedb config is missing '''
    config = bootstrap
    # Don't set remote/remotedb configuration

    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Plugin now sets a default path via defaults() method
    # So remotedbfile should contain a valid path, not be None/empty
    assert plugin.remotedbfile is not None
    assert 'remote.db' in str(plugin.remotedbfile)


@pytest.mark.asyncio
async def test_remote_plugin_integration_with_metadatadb_write(remote_bootstrap):  # pylint: disable=redefined-outer-name
    ''' test remote plugin integration with metadata writing '''
    config = remote_bootstrap
    plugin = nowplaying.inputs.remote.Plugin(config=config)

    # Create a real MetadataDB instance
    metadb = nowplaying.db.MetadataDB(databasefile=plugin.remotedbfile, initialize=True)
    plugin.remotedb = metadb

    # Write multiple metadata entries
    test_metadata_1 = {'artist': 'Artist One', 'title': 'Title One', 'filename': 'track1.mp3'}
    test_metadata_2 = {'artist': 'Artist Two', 'title': 'Title Two', 'filename': 'track2.mp3'}

    await metadb.write_to_metadb(metadata=test_metadata_1)
    await metadb.write_to_metadb(metadata=test_metadata_2)

    # Test that plugin reads the latest metadata
    event = MagicMock()
    event.is_directory = False

    plugin._read_track(event)  # pylint: disable=protected-access

    # Should have the latest (second) metadata
    assert plugin.metadata['artist'] == 'Artist Two'
    assert plugin.metadata['title'] == 'Title Two'
    assert plugin.metadata['filename'] == 'track2.mp3'
