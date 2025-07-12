#!/usr/bin/env python3
''' test stagelinq input plugin '''

import asyncio
import datetime
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

import nowplaying.inputs.stagelinq
from nowplaying.inputs.stagelinq import DeckInfo, StagelinqHandler
from nowplaying.vendor.stagelinq.discovery import Device
from nowplaying.vendor.stagelinq.device import AsyncDevice
from nowplaying.vendor.stagelinq.messages import Token


@pytest.fixture
def stagelinq_bootstrap(bootstrap):
    ''' bootstrap test for stagelinq plugin '''
    config = bootstrap
    config.cparser.setValue('stagelinq/mixmode', 'newest')
    config.cparser.sync()
    yield config


def test_deckinfo_init_default():
    ''' test DeckInfo initialization with defaults '''
    deck = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc))

    assert deck.track is None
    assert deck.artist is None
    assert deck.bpm is None
    assert deck.playing is False
    assert deck.updated is not None


def test_deckinfo_init_with_values():
    ''' test DeckInfo initialization with values '''
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    deck = DeckInfo(updated=now, track="Test Track", artist="Test Artist", bpm=120, playing=True)

    assert deck.track == "Test Track"
    assert deck.artist == "Test Artist"
    assert deck.bpm == 120
    assert deck.playing is True
    assert deck.updated == now


def test_deckinfo_post_init_no_updated():
    ''' test DeckInfo __post_init__ sets updated when None '''
    with patch('nowplaying.inputs.stagelinq.datetime') as mock_datetime:
        mock_now = datetime.datetime.now(tz=datetime.timezone.utc)
        mock_datetime.datetime.now.return_value = mock_now
        mock_datetime.timezone.utc = datetime.timezone.utc

        deck = DeckInfo(updated=None)

        assert deck.updated == mock_now


def test_deckinfo_less_than_comparison():
    ''' test DeckInfo __lt__ comparison '''
    earlier = datetime.datetime.now(tz=datetime.timezone.utc)
    later = earlier + datetime.timedelta(seconds=1)

    deck1 = DeckInfo(updated=earlier)
    deck2 = DeckInfo(updated=later)

    assert deck1 < deck2
    assert not deck2 < deck1


def test_deckinfo_copy():
    ''' test DeckInfo copy method '''
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    deck = DeckInfo(updated=now, track="Test Track", artist="Test Artist", bpm=120, playing=True)

    copied_deck = deck.copy()

    assert copied_deck.track == deck.track
    assert copied_deck.artist == deck.artist
    assert copied_deck.bpm == deck.bpm
    assert copied_deck.playing == deck.playing
    assert copied_deck.updated == deck.updated
    assert copied_deck is not deck


def test_deckinfo_same_content_true():
    ''' test DeckInfo same_content returns True for same track/artist '''
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    deck1 = DeckInfo(updated=now, track="Test Track", artist="Test Artist")
    deck2 = DeckInfo(updated=now, track="Test Track", artist="Test Artist")

    assert deck1.same_content(deck2)
    assert deck2.same_content(deck1)


def test_deckinfo_same_content_false_different_track():
    ''' test DeckInfo same_content returns False for different track '''
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    deck1 = DeckInfo(updated=now, track="Test Track", artist="Test Artist")
    deck2 = DeckInfo(updated=now, track="Different Track", artist="Test Artist")

    assert not deck1.same_content(deck2)
    assert not deck2.same_content(deck1)


def test_deckinfo_same_content_false_different_artist():
    ''' test DeckInfo same_content returns False for different artist '''
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    deck1 = DeckInfo(updated=now, track="Test Track", artist="Test Artist")
    deck2 = DeckInfo(updated=now, track="Test Track", artist="Different Artist")

    assert not deck1.same_content(deck2)
    assert not deck2.same_content(deck1)


def test_deckinfo_same_content_none_values():
    ''' test DeckInfo same_content with None values '''
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    deck1 = DeckInfo(updated=now, track=None, artist=None)
    deck2 = DeckInfo(updated=now, track=None, artist=None)

    assert deck1.same_content(deck2)


def test_stagelinq_handler_init():
    ''' test StagelinqHandler initialization '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    assert handler.event == event
    assert handler.device is None
    assert handler.loop_task is None
    assert handler.decks == {}


@pytest.mark.asyncio
async def test_stagelinq_handler_get_device_not_found():
    ''' test get_device when no device is found '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    with patch('nowplaying.inputs.stagelinq.discover_stagelinq_devices') as mock_discover:
        mock_discovery = AsyncMock()
        mock_discovery.start_announcing = AsyncMock()
        mock_discovery.get_devices = AsyncMock(return_value=[])
        mock_discover.return_value.__aenter__ = AsyncMock(return_value=mock_discovery)
        mock_discover.return_value.__aexit__ = AsyncMock()

        # Set event before calling to prevent infinite loop
        event.set()

        await handler.get_device()

        assert handler.device is None


@pytest.mark.asyncio
async def test_stagelinq_handler_get_device_found():
    ''' test get_device when device is found '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Mock device with all required parameters
    mock_token = Token(b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f")
    mock_device = Device(ip="192.168.1.100",
                         name="Test Device",
                         software_name="Test Software",
                         software_version="1.0.0",
                         port=12345,
                         token=mock_token)

    with patch('nowplaying.inputs.stagelinq.discover_stagelinq_devices') as mock_discover:
        mock_discovery = AsyncMock()
        mock_discovery.start_announcing = AsyncMock()
        mock_discovery.get_devices = AsyncMock(return_value=[mock_device])
        mock_discover.return_value.__aenter__ = AsyncMock(return_value=mock_discovery)
        mock_discover.return_value.__aexit__ = AsyncMock()

        # Actually call the get_device method
        await handler.get_device()

        # Verify the method worked correctly
        assert handler.device is not None
        assert handler.device.name == "Test Device"
        assert handler.device.ip == "192.168.1.100"
        assert isinstance(handler.device, AsyncDevice)

        # Verify discovery mocks were called as expected
        mock_discovery.start_announcing.assert_called_once()
        mock_discovery.get_devices.assert_called_once()


@pytest.mark.asyncio
async def test_stagelinq_handler_get_device_exception():
    ''' test get_device handles exceptions '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    with patch('nowplaying.inputs.stagelinq.discover_stagelinq_devices') as mock_discover:
        mock_discover.side_effect = Exception("Test exception")

        # Set event to stop the loop after first iteration
        event.set()

        await handler.get_device()

        assert handler.device is None


def test_stagelinq_handler_process_state_update_artist():
    ''' test process_state_update for artist name '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Initialize temp_decks
    temp_decks = {1: DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc))}

    # Mock state
    mock_state = MagicMock()
    mock_state.name = "Deck1.ArtistName"
    mock_state.get_typed_value.return_value = "Test Artist"

    handler.process_state_update(temp_decks, mock_state)

    assert temp_decks[1].artist == "Test Artist"


def test_stagelinq_handler_process_state_update_track():
    ''' test process_state_update for song name '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Initialize temp_decks
    temp_decks = {1: DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc))}

    # Mock state
    mock_state = MagicMock()
    mock_state.name = "Deck1.SongName"
    mock_state.get_typed_value.return_value = "Test Track"

    handler.process_state_update(temp_decks, mock_state)

    assert temp_decks[1].track == "Test Track"


def test_stagelinq_handler_process_state_update_bpm():
    ''' test process_state_update for BPM '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Initialize temp_decks
    temp_decks = {1: DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc))}

    # Mock state
    mock_state = MagicMock()
    mock_state.name = "Deck1.CurrentBPM"
    mock_state.get_typed_value.return_value = 120.0

    handler.process_state_update(temp_decks, mock_state)

    assert temp_decks[1].bpm == 120.0


def test_stagelinq_handler_process_state_update_playing():
    ''' test process_state_update for play state '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Initialize temp_decks
    temp_decks = {1: DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc))}

    # Mock state
    mock_state = MagicMock()
    mock_state.name = "Deck1.PlayState"
    mock_state.get_typed_value.return_value = True

    handler.process_state_update(temp_decks, mock_state)

    assert temp_decks[1].playing is True


def test_stagelinq_handler_process_state_update_no_deck():
    ''' test process_state_update with no deck number in state name '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    temp_decks = {}

    # Mock state without deck number
    mock_state = MagicMock()
    mock_state.name = "GlobalState.Something"

    handler.process_state_update(temp_decks, mock_state)

    # Should not modify temp_decks
    assert temp_decks == {}


def test_stagelinq_handler_process_state_update_empty_values():
    ''' test process_state_update with empty/None values '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Initialize temp_decks
    temp_decks = {1: DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc))}

    # Mock state with None value
    mock_state = MagicMock()
    mock_state.name = "Deck1.ArtistName"
    mock_state.get_typed_value.return_value = None

    handler.process_state_update(temp_decks, mock_state)

    assert temp_decks[1].artist == ""


def test_stagelinq_handler_update_current_tracks_new_playing():
    ''' test update_current_tracks with new playing deck '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Initialize temp_decks with playing deck
    temp_decks = {
        1:
        DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc),
                 track="Test Track",
                 artist="Test Artist",
                 playing=True)
    }

    # Initialize empty decks for all deck numbers
    for deck_num in range(1, 5):
        temp_decks[deck_num] = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc),
                                        playing=(deck_num == 1))

    handler.update_current_tracks(temp_decks)

    assert 1 in handler.decks
    assert handler.decks[1].playing is True


def test_stagelinq_handler_update_current_tracks_stopped_playing():
    ''' test update_current_tracks with deck that stopped playing '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Set up existing playing deck
    handler.decks[1] = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc),
                                track="Test Track",
                                artist="Test Artist",
                                playing=True)

    # Initialize temp_decks with stopped deck
    temp_decks = {}
    for deck_num in range(1, 5):
        temp_decks[deck_num] = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc),
                                        playing=False)

    handler.update_current_tracks(temp_decks)

    # Deck should be removed since it's not playing
    assert 1 not in handler.decks


def test_stagelinq_handler_update_current_tracks_content_changed():
    ''' test update_current_tracks with content change '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Set up existing deck
    handler.decks[1] = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc),
                                track="Old Track",
                                artist="Old Artist",
                                playing=True)

    # Initialize temp_decks with updated content
    temp_decks = {}
    for deck_num in range(1, 5):
        temp_decks[deck_num] = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc),
                                        track="New Track" if deck_num == 1 else None,
                                        artist="New Artist" if deck_num == 1 else None,
                                        playing=(deck_num == 1))

    handler.update_current_tracks(temp_decks)

    assert handler.decks[1].track == "New Track"
    assert handler.decks[1].artist == "New Artist"


@pytest.mark.asyncio
async def test_stagelinq_handler_start():
    ''' test start method '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    with patch.object(handler, 'loop', new_callable=AsyncMock) as mock_loop:
        await handler.start()

        # Check that the loop_task was created
        assert handler.loop_task is not None
        assert isinstance(handler.loop_task, asyncio.Task)


@pytest.mark.asyncio
async def test_stagelinq_handler_stop():
    ''' test stop method '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Set up mock task
    mock_task = MagicMock()
    handler.loop_task = mock_task

    await handler.stop()

    assert event.is_set()
    mock_task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_stagelinq_handler_stop_no_task():
    ''' test stop method with no task '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    handler.loop_task = None

    await handler.stop()

    assert event.is_set()


@pytest.mark.asyncio
async def test_stagelinq_handler_get_track_newest():
    ''' test get_track with newest mixmode '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Set up decks with different timestamps
    earlier = datetime.datetime.now(tz=datetime.timezone.utc)
    later = earlier + datetime.timedelta(seconds=1)

    handler.decks[1] = DeckInfo(updated=earlier, track="Old Track")
    handler.decks[2] = DeckInfo(updated=later, track="New Track")

    result = await handler.get_track("newest")

    assert result.track == "New Track"


@pytest.mark.asyncio
async def test_stagelinq_handler_get_track_oldest():
    ''' test get_track with oldest mixmode '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    # Set up decks with different timestamps
    earlier = datetime.datetime.now(tz=datetime.timezone.utc)
    later = earlier + datetime.timedelta(seconds=1)

    handler.decks[1] = DeckInfo(updated=earlier, track="Old Track")
    handler.decks[2] = DeckInfo(updated=later, track="New Track")

    result = await handler.get_track("oldest")

    assert result.track == "Old Track"


@pytest.mark.asyncio
async def test_stagelinq_handler_get_track_no_decks():
    ''' test get_track with no decks '''
    event = asyncio.Event()
    handler = StagelinqHandler(event)

    result = await handler.get_track("newest")

    assert result is None


@pytest.mark.asyncio
async def test_stagelinq_plugin_init(stagelinq_bootstrap):
    ''' test StagelinqPlugin initialization '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    assert plugin.displayname == "StagelinQ"
    assert plugin.url is None
    assert plugin.mixmode == "newest"
    assert plugin.testmode is False
    assert plugin.handler is None
    assert plugin.event is not None


@pytest.mark.asyncio
async def test_stagelinq_plugin_desc_settingsui(stagelinq_bootstrap):
    ''' test desc_settingsui method '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    # Mock QWidget
    qwidget = MagicMock()

    plugin.desc_settingsui(qwidget)

    qwidget.setText.assert_called_once_with('Denon StagelinQ compatible equipment')


@pytest.mark.asyncio
async def test_stagelinq_plugin_install(stagelinq_bootstrap):
    ''' test install method '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    assert plugin.install() is False


@pytest.mark.asyncio
async def test_stagelinq_plugin_validmixmodes(stagelinq_bootstrap):
    ''' test validmixmodes method '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    assert plugin.validmixmodes() == ['newest', 'oldest']


@pytest.mark.asyncio
async def test_stagelinq_plugin_setmixmode_valid(stagelinq_bootstrap):
    ''' test setmixmode with valid mode '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    result = plugin.setmixmode('oldest')

    assert result == 'oldest'
    assert config.cparser.value('stagelinq/mixmode') == 'oldest'


@pytest.mark.asyncio
async def test_stagelinq_plugin_setmixmode_invalid(stagelinq_bootstrap):
    ''' test setmixmode with invalid mode '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    # Set a known value first
    config.cparser.setValue('stagelinq/mixmode', 'newest')

    result = plugin.setmixmode('invalid')

    assert result == 'newest'  # Should fall back to config value


@pytest.mark.asyncio
async def test_stagelinq_plugin_getmixmode(stagelinq_bootstrap):
    ''' test getmixmode method '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    # Set mixmode in config
    config.cparser.setValue('stagelinq/mixmode', 'oldest')

    result = plugin.getmixmode()

    assert result == 'oldest'


@pytest.mark.asyncio
async def test_stagelinq_plugin_getplayingtrack_no_handler(stagelinq_bootstrap):
    ''' test getplayingtrack with no handler '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    result = await plugin.getplayingtrack()

    assert result is None


@pytest.mark.asyncio
async def test_stagelinq_plugin_getplayingtrack_no_deck(stagelinq_bootstrap):
    ''' test getplayingtrack with handler but no deck '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    # Set up handler
    plugin.handler = MagicMock()
    plugin.handler.get_track = AsyncMock(return_value=None)

    result = await plugin.getplayingtrack()

    assert result == {}


@pytest.mark.asyncio
async def test_stagelinq_plugin_getplayingtrack_with_deck(stagelinq_bootstrap):
    ''' test getplayingtrack with deck data '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    # Set up handler with deck
    mock_deck = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc),
                         track="Test Track",
                         artist="Test Artist",
                         bpm=120.0,
                         playing=True)
    plugin.handler = MagicMock()
    plugin.handler.get_track = AsyncMock(return_value=mock_deck)

    result = await plugin.getplayingtrack()

    assert result['track'] == "Test Track"
    assert result['artist'] == "Test Artist"
    assert result['bpm'] == "120.0"


@pytest.mark.asyncio
async def test_stagelinq_plugin_getplayingtrack_partial_data(stagelinq_bootstrap):
    ''' test getplayingtrack with partial deck data '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    # Set up handler with partial deck data
    mock_deck = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc),
                         track="Test Track",
                         artist=None,
                         bpm=None,
                         playing=True)
    plugin.handler = MagicMock()
    plugin.handler.get_track = AsyncMock(return_value=mock_deck)

    result = await plugin.getplayingtrack()

    assert result['track'] == "Test Track"
    assert 'artist' not in result
    assert 'bpm' not in result


@pytest.mark.asyncio
async def test_stagelinq_plugin_getrandomtrack(stagelinq_bootstrap):
    ''' test getrandomtrack method '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    with pytest.raises(NotImplementedError):
        await plugin.getrandomtrack("test_playlist")


@pytest.mark.asyncio
async def test_stagelinq_plugin_start(stagelinq_bootstrap):
    ''' test start method '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    with patch('nowplaying.inputs.stagelinq.StagelinqHandler') as mock_handler_class:
        mock_handler = MagicMock()
        mock_handler.start = AsyncMock()
        mock_handler_class.return_value = mock_handler

        await plugin.start()

        mock_handler_class.assert_called_once_with(event=plugin.event)
        mock_handler.start.assert_called_once()
        assert plugin.handler == mock_handler


@pytest.mark.asyncio
async def test_stagelinq_plugin_stop(stagelinq_bootstrap):
    ''' test stop method '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    # Set up handler
    mock_handler = MagicMock()
    mock_handler.stop = AsyncMock()
    plugin.handler = mock_handler

    await plugin.stop()

    assert plugin.event.is_set()
    mock_handler.stop.assert_called_once()


@pytest.mark.asyncio
async def test_stagelinq_plugin_stop_no_handler(stagelinq_bootstrap):
    ''' test stop method with no handler '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    plugin.handler = None

    await plugin.stop()

    assert plugin.event.is_set()


@pytest.mark.asyncio
async def test_stagelinq_plugin_full_workflow(stagelinq_bootstrap):
    ''' test full workflow from start to getplayingtrack '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    with patch('nowplaying.inputs.stagelinq.StagelinqHandler') as mock_handler_class:
        mock_handler = MagicMock()
        mock_handler.start = AsyncMock()
        mock_handler.stop = AsyncMock()

        # Mock get_track to return a deck
        mock_deck = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc),
                             track="Integration Test Track",
                             artist="Integration Test Artist",
                             bpm=128.0,
                             playing=True)
        mock_handler.get_track = AsyncMock(return_value=mock_deck)
        mock_handler_class.return_value = mock_handler

        # Start plugin
        await plugin.start()

        # Get playing track
        result = await plugin.getplayingtrack()

        # Verify results
        assert result['track'] == "Integration Test Track"
        assert result['artist'] == "Integration Test Artist"
        assert result['bpm'] == "128.0"

        # Stop plugin
        await plugin.stop()

        mock_handler.start.assert_called_once()
        mock_handler.stop.assert_called_once()
        assert plugin.event.is_set()


@pytest.mark.asyncio
async def test_stagelinq_plugin_mixmode_workflow(stagelinq_bootstrap):
    ''' test mixmode setting and usage '''
    config = stagelinq_bootstrap
    plugin = nowplaying.inputs.stagelinq.Plugin(config=config)

    # Test setting mixmode
    assert plugin.setmixmode('oldest') == 'oldest'
    assert plugin.getmixmode() == 'oldest'

    # Test that mixmode is passed to handler
    with patch('nowplaying.inputs.stagelinq.StagelinqHandler') as mock_handler_class:
        mock_handler = MagicMock()
        mock_handler.start = AsyncMock()
        mock_handler.get_track = AsyncMock(return_value=None)
        mock_handler_class.return_value = mock_handler

        await plugin.start()

        # Set mixmode on plugin
        plugin.mixmode = 'oldest'

        # Get playing track (should pass mixmode to handler)
        await plugin.getplayingtrack()

        mock_handler.get_track.assert_called_once_with(mixmode='oldest')
