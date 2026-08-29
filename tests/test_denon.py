#!/usr/bin/env python3
"""Tests for Denon DJ StagelinQ input plugin"""
# pylint: disable=protected-access,redefined-outer-name

import asyncio
import struct
import time

import pytest

import nowplaying.inputs.denon
from nowplaying.denon import StagelinqError
from nowplaying.denon.connection import ConnectionManager, DeviceConnection
from nowplaying.denon.protocol import StagelinqProtocol
from nowplaying.denon.types import MSG_SERVICES_REQUEST, DenonDevice, DenonService, DenonState

DEVICE_TOKEN_1 = b"\x01" * 16
DEVICE_TOKEN_2 = b"\x02" * 16


def _feed_states(processor, token: bytes, states: dict) -> None:
    """Feed synthetic StateMap values into the metadata processor"""
    for name, value in states.items():
        processor.update_state(token, DenonState(name=name, value=value))


@pytest.fixture
def denon_bootstrap(bootstrap):
    """Bootstrap test with Denon configuration"""
    config = bootstrap
    config.cparser.setValue("denon/discovery_timeout", 5.0)  # Use the actual default
    config.cparser.setValue("denon/deckskip", None)
    config.cparser.sync()
    yield config


@pytest.fixture
def denon_plugin(denon_bootstrap):
    """Create a Denon plugin instance for testing"""
    yield nowplaying.inputs.denon.Plugin(config=denon_bootstrap)


@pytest.mark.asyncio
async def test_plugin_creation(denon_plugin):
    """Test plugin can be created"""
    assert denon_plugin.displayname == "Denon DJ"
    assert denon_plugin.token is not None
    assert len(denon_plugin.token) == 16
    assert denon_plugin.token[0] & 0x80 == 0  # MSb must be 0


@pytest.mark.asyncio
async def test_token_generation():
    """Test token generation follows StagelinQ protocol requirements"""
    # Generate multiple tokens to test MSb constraint
    for _ in range(100):
        token = StagelinqProtocol.generate_token()
        assert len(token) == 16
        assert token[0] & 0x80 == 0  # MSb must be 0


@pytest.mark.asyncio
async def test_install_returns_false(denon_plugin):
    """Test install returns False (network devices can't auto-install)"""
    assert not denon_plugin.detect()


@pytest.mark.asyncio
async def test_validmixmodes(denon_plugin):
    """Test valid mix modes"""
    modes = denon_plugin.validmixmodes()
    assert modes == ["newest", "oldest"]


@pytest.mark.asyncio
async def test_mixmode_operations(denon_plugin):
    """Test mix mode get/set operations"""
    # Test setting valid modes
    result = denon_plugin.setmixmode("newest")
    assert result == "newest"
    assert denon_plugin.getmixmode() == "newest"

    result = denon_plugin.setmixmode("oldest")
    assert result == "oldest"
    assert denon_plugin.getmixmode() == "oldest"

    # Test setting invalid mode (should keep current)
    result = denon_plugin.setmixmode("invalid")
    assert result == "oldest"  # Should remain unchanged


@pytest.mark.asyncio
async def test_getplayingtrack_no_metadata(denon_plugin):
    """Test getplayingtrack returns None when no metadata available"""
    result = await denon_plugin.getplayingtrack()
    assert result is None


@pytest.mark.asyncio
async def test_getrandomtrack_not_supported(denon_plugin):
    """Test getrandomtrack returns None (not supported)"""
    result = await denon_plugin.getrandomtrack("test_playlist")
    assert result is None


@pytest.mark.asyncio
async def test_extract_numeric_value(denon_plugin):
    """Test numeric value extraction from StagelinQ data"""
    # Test with valid data field
    data = {"data": 0.75}
    result = denon_plugin.metadata_processor._extract_numeric_value(data)
    assert result == 0.75

    # Test with value field
    data = {"value": 0.5}
    result = denon_plugin.metadata_processor._extract_numeric_value(data)
    assert result == 0.5

    # Test with no valid fields
    data = {"other": "invalid"}
    result = denon_plugin.metadata_processor._extract_numeric_value(data, default=0.25)
    assert result == 0.25

    # Test with non-dict input
    result = denon_plugin.metadata_processor._extract_numeric_value("not_dict", default=0.1)
    assert result == 0.1

    # Test with invalid numeric value
    data = {"data": "not_a_number"}
    result = denon_plugin.metadata_processor._extract_numeric_value(data, default=0.3)
    assert result == 0.3


@pytest.mark.asyncio
async def test_effective_volume_ladder(denon_plugin):
    """Test the audibility ladder: mixer states, then EMV, then default-audible"""
    processor = denon_plugin.metadata_processor
    token = DEVICE_TOKEN_1

    # No mixer signal at all: assume audible (analog mixer case)
    assert processor._effective_volume(token, 1) == 1.0

    # ExternalMixerVolume present but never nonzero (mixerless player
    # reporting an initial 0): still assumed audible
    _feed_states(processor, token, {"/Engine/Deck1/ExternalMixerVolume": {"data": 0.0}})
    assert processor._effective_volume(token, 1) == 1.0

    # A nonzero EMV proves a Denon mixer/controller is driving it;
    # from then on the value is authoritative, including zero
    _feed_states(processor, token, {"/Engine/Deck1/ExternalMixerVolume": {"data": 0.7}})
    assert processor._effective_volume(token, 1) == 0.7
    _feed_states(processor, token, {"/Engine/Deck1/ExternalMixerVolume": {"data": 0.0}})
    assert processor._effective_volume(token, 1) == 0.0

    # Raw mixer states (all-in-one controllers) take precedence over EMV
    _feed_states(
        processor,
        token,
        {
            "/Mixer/CH1faderPosition": {"data": 0.5},
            "/Mixer/CrossfaderPosition": {"data": 0.5},
        },
    )
    assert processor._effective_volume(token, 1) == 0.5


@pytest.mark.asyncio
async def test_calculate_effective_volume_fader_zero(denon_plugin):
    """Test effective volume calculation with zero fader"""
    # Any deck with fader at 0 should have 0 effective volume
    for deck in [1, 2, 3, 4]:
        result = denon_plugin.metadata_processor._calculate_effective_volume(deck, 0.0, 0.5)
        assert result == 0.0


@pytest.mark.asyncio
async def test_calculate_effective_volume_left_decks(denon_plugin):
    """Test effective volume calculation for left side decks (1, 3)"""
    fader_pos = 0.8

    # Crossfader full left - left decks should be audible
    result = denon_plugin.metadata_processor._calculate_effective_volume(1, fader_pos, 0.0)
    assert result == fader_pos

    result = denon_plugin.metadata_processor._calculate_effective_volume(3, fader_pos, 0.0)
    assert result == fader_pos

    # Crossfader full right - left decks should be silent
    result = denon_plugin.metadata_processor._calculate_effective_volume(1, fader_pos, 1.0)
    assert result == 0.0

    result = denon_plugin.metadata_processor._calculate_effective_volume(3, fader_pos, 1.0)
    assert result == 0.0

    # Crossfader center - left decks should be audible
    result = denon_plugin.metadata_processor._calculate_effective_volume(1, fader_pos, 0.5)
    assert result == fader_pos


@pytest.mark.asyncio
async def test_calculate_effective_volume_right_decks(denon_plugin):
    """Test effective volume calculation for right side decks (2, 4)"""
    fader_pos = 0.8

    # Crossfader full right - right decks should be audible
    result = denon_plugin.metadata_processor._calculate_effective_volume(2, fader_pos, 1.0)
    assert result == fader_pos

    result = denon_plugin.metadata_processor._calculate_effective_volume(4, fader_pos, 1.0)
    assert result == fader_pos

    # Crossfader full left - right decks should be silent
    result = denon_plugin.metadata_processor._calculate_effective_volume(2, fader_pos, 0.0)
    assert result == 0.0

    result = denon_plugin.metadata_processor._calculate_effective_volume(4, fader_pos, 0.0)
    assert result == 0.0

    # Crossfader center - right decks should be audible
    result = denon_plugin.metadata_processor._calculate_effective_volume(2, fader_pos, 0.5)
    assert result == fader_pos


@pytest.mark.asyncio
async def test_calculate_effective_volume_crossfader_transition(denon_plugin):
    """Test crossfader transition zones"""
    fader_pos = 1.0

    # Test transition zone for left deck (0.5 < pos <= 0.8)
    # At crossfader 0.65, left deck should be partially audible
    result = denon_plugin.metadata_processor._calculate_effective_volume(1, fader_pos, 0.65)
    expected = fader_pos * (1.0 - ((0.65 - 0.5) / 0.3))  # Should be 0.5
    assert abs(result - expected) < 0.01

    # Test transition zone for right deck (0.2 <= pos < 0.5)
    # At crossfader 0.35, right deck should be partially audible
    result = denon_plugin.metadata_processor._calculate_effective_volume(2, fader_pos, 0.35)
    expected = fader_pos * ((0.35 - 0.2) / 0.3)  # Should be 0.5
    assert abs(result - expected) < 0.01


@pytest.mark.asyncio
async def test_getplayingtrack_single_audible_deck(denon_plugin):
    """Test track selection with single audible deck"""
    # Set up metadata for one playing, audible track
    _feed_states(
        denon_plugin.metadata_processor,
        DEVICE_TOKEN_1,
        {
            "/Engine/Deck1/Play": {"state": True},
            "/Engine/Deck1/Track/ArtistName": {"string": "Test Artist"},
            "/Engine/Deck1/Track/SongName": {"string": "Test Song"},
            "/Mixer/CH1faderPosition": {"data": 0.8},
            "/Mixer/CrossfaderPosition": {"data": 0.5},
        },
    )

    result = await denon_plugin.getplayingtrack()
    assert result is not None
    assert result["artist"] == "Test Artist"
    assert result["title"] == "Test Song"


@pytest.mark.asyncio
async def test_getplayingtrack_inaudible_deck(denon_plugin):
    """Test that tracks with low effective volume are filtered out"""
    # Set up metadata for playing track but with fader down
    _feed_states(
        denon_plugin.metadata_processor,
        DEVICE_TOKEN_1,
        {
            "/Engine/Deck1/Play": {"state": True},
            "/Engine/Deck1/Track/ArtistName": {"string": "Test Artist"},
            "/Engine/Deck1/Track/SongName": {"string": "Test Song"},
            "/Mixer/CH1faderPosition": {"data": 0.05},  # Very low fader
            "/Mixer/CrossfaderPosition": {"data": 0.5},
        },
    )

    result = await denon_plugin.getplayingtrack()
    assert result is None  # Should be filtered out due to low volume


@pytest.mark.asyncio
async def test_getplayingtrack_multiple_decks_volume_priority(denon_plugin):
    """Test track selection prioritizes louder tracks"""
    # Set up two playing tracks with different volumes
    _feed_states(
        denon_plugin.metadata_processor,
        DEVICE_TOKEN_1,
        {
            # Deck 1 - quieter
            "/Engine/Deck1/Play": {"state": True},
            "/Engine/Deck1/Track/ArtistName": {"string": "Quiet Artist"},
            "/Engine/Deck1/Track/SongName": {"string": "Quiet Song"},
            "/Mixer/CH1faderPosition": {"data": 0.3},
            # Deck 2 - louder
            "/Engine/Deck2/Play": {"state": True},
            "/Engine/Deck2/Track/ArtistName": {"string": "Loud Artist"},
            "/Engine/Deck2/Track/SongName": {"string": "Loud Song"},
            "/Mixer/CH2faderPosition": {"data": 0.9},
            "/Mixer/CrossfaderPosition": {"data": 0.5},  # Both sides audible
        },
    )

    # Should select the louder track regardless of timing
    result = await denon_plugin.getplayingtrack()
    assert result is not None
    assert result["artist"] == "Loud Artist"
    assert result["title"] == "Loud Song"


@pytest.mark.asyncio
async def test_getplayingtrack_deck_skip_functionality(denon_plugin):
    """Test that skipped decks are ignored"""
    # Configure deck skip
    denon_plugin.config.cparser.setValue("denon/deckskip", ["1"])

    _feed_states(
        denon_plugin.metadata_processor,
        DEVICE_TOKEN_1,
        {
            # Deck 1 - should be skipped
            "/Engine/Deck1/Play": {"state": True},
            "/Engine/Deck1/Track/ArtistName": {"string": "Skipped Artist"},
            "/Engine/Deck1/Track/SongName": {"string": "Skipped Song"},
            "/Mixer/CH1faderPosition": {"data": 0.9},
            # Deck 2 - should be selected
            "/Engine/Deck2/Play": {"state": True},
            "/Engine/Deck2/Track/ArtistName": {"string": "Selected Artist"},
            "/Engine/Deck2/Track/SongName": {"string": "Selected Song"},
            "/Mixer/CH2faderPosition": {"data": 0.7},
            "/Mixer/CrossfaderPosition": {"data": 0.5},
        },
    )

    result = await denon_plugin.getplayingtrack()
    assert result is not None
    assert result["artist"] == "Selected Artist"
    assert result["title"] == "Selected Song"


@pytest.mark.asyncio
async def test_getplayingtrack_crossfader_filtering(denon_plugin):
    """Test crossfader position affects track selection"""
    _feed_states(
        denon_plugin.metadata_processor,
        DEVICE_TOKEN_1,
        {
            # Left deck (should be audible when crossfader left)
            "/Engine/Deck1/Play": {"state": True},
            "/Engine/Deck1/Track/ArtistName": {"string": "Left Artist"},
            "/Engine/Deck1/Track/SongName": {"string": "Left Song"},
            "/Mixer/CH1faderPosition": {"data": 0.8},
            # Right deck (should be inaudible when crossfader left)
            "/Engine/Deck2/Play": {"state": True},
            "/Engine/Deck2/Track/ArtistName": {"string": "Right Artist"},
            "/Engine/Deck2/Track/SongName": {"string": "Right Song"},
            "/Mixer/CH2faderPosition": {"data": 0.8},
            "/Mixer/CrossfaderPosition": {"data": 0.0},  # Full left
        },
    )

    result = await denon_plugin.getplayingtrack()
    assert result is not None
    assert result["artist"] == "Left Artist"
    assert result["title"] == "Left Song"


@pytest.mark.asyncio
async def test_two_players_logical_deck_numbering(denon_plugin):
    """Test logical decks span devices ordered by DJ-assigned player number"""
    processor = denon_plugin.metadata_processor
    # Two SC6000Ms with an analog mixer: no mixer states at all.
    # Register in reverse order to prove sorting is by player number.
    for token, player, artist in [
        (DEVICE_TOKEN_2, "2", "Second Artist"),
        (DEVICE_TOKEN_1, "1", "First Artist"),
    ]:
        processor.register_device(_make_test_device(token))
        _feed_states(
            processor,
            token,
            {
                "/Client/Preferences/Player": {"string": player},
                "/Engine/Deck1/Play": {"state": True},
                "/Engine/Deck1/Track/ArtistName": {"string": artist},
                "/Engine/Deck1/Track/SongName": {"string": f"Song {player}"},
            },
        )

    decks = processor._get_audible_playing_decks()
    # JP14 = SC6000M = 2 decks per device: player 1 owns logical 1-2,
    # player 2 owns logical 3-4; layer A of each is playing
    assert [(deck["deck"], deck["artist"]) for deck in decks] == [
        (1, "First Artist"),
        (3, "Second Artist"),
    ]


@pytest.mark.asyncio
async def test_two_players_deckskip_spans_devices(denon_plugin):
    """Test deckskip logical numbers address decks on any device"""
    processor = denon_plugin.metadata_processor
    denon_plugin.config.cparser.setValue("denon/deckskip", ["1"])

    for token, player, artist in [
        (DEVICE_TOKEN_1, "1", "First Artist"),
        (DEVICE_TOKEN_2, "2", "Second Artist"),
    ]:
        processor.register_device(_make_test_device(token))
        _feed_states(
            processor,
            token,
            {
                "/Client/Preferences/Player": {"string": player},
                "/Engine/Deck1/Play": {"state": True},
                "/Engine/Deck1/Track/ArtistName": {"string": artist},
                "/Engine/Deck1/Track/SongName": {"string": f"Song {player}"},
            },
        )

    decks = processor._get_audible_playing_decks()
    assert [(deck["deck"], deck["artist"]) for deck in decks] == [(3, "Second Artist")]


@pytest.mark.asyncio
async def test_deck_label_player_and_layer(denon_plugin):
    """Test deck labels combine player number and layer letter"""
    processor = denon_plugin.metadata_processor
    _feed_states(processor, DEVICE_TOKEN_1, {"/Client/Preferences/Player": {"string": "2"}})

    label = processor._deck_label({"token": DEVICE_TOKEN_1, "deck_idx": 2, "deck": 4})
    assert label == "2B"

    # Without a player number, fall back to the logical deck number
    label = processor._deck_label({"token": DEVICE_TOKEN_2, "deck_idx": 1, "deck": 1})
    assert label == "1"


@pytest.mark.asyncio
async def test_get_all_decks_includes_paused(denon_plugin):
    """Test the multi-deck snapshot shows loaded decks regardless of play state"""
    processor = denon_plugin.metadata_processor
    for token, player in [(DEVICE_TOKEN_1, "1"), (DEVICE_TOKEN_2, "2")]:
        processor.register_device(_make_test_device(token))
        _feed_states(processor, token, {"/Client/Preferences/Player": {"string": player}})

    # Player 1 layer A: playing
    _feed_states(
        processor,
        DEVICE_TOKEN_1,
        {
            "/Engine/Deck1/Play": {"state": True},
            "/Engine/Deck1/Track/ArtistName": {"string": "Playing Artist"},
            "/Engine/Deck1/Track/SongName": {"string": "Playing Song"},
            "/Engine/Deck1/Track/BPM": {"data": 128},
        },
    )
    # Player 2 layer B: loaded but paused
    _feed_states(
        processor,
        DEVICE_TOKEN_2,
        {
            "/Engine/Deck2/Play": {"state": False},
            "/Engine/Deck2/Track/SongLoaded": {"state": True},
            "/Engine/Deck2/Track/ArtistName": {"string": "Cued Artist"},
            "/Engine/Deck2/Track/SongName": {"string": "Cued Song"},
        },
    )

    decks = processor.get_all_decks()
    assert [(deck["deck"], deck["label"], deck["artist"], deck["playing"]) for deck in decks] == [
        (1, "1A", "Playing Artist", True),
        (4, "2B", "Cued Artist", False),
    ]
    assert decks[0]["bpm"] == "128"

    # The playing-track selection still only sees the audible playing deck
    track = processor.get_playing_track()
    assert track is not None
    assert track["artist"] == "Playing Artist"


@pytest.mark.asyncio
async def test_stop_clears_metadata_state(denon_plugin):
    """Test plugin stop drops device state so a restart cannot see stale decks"""
    processor = denon_plugin.metadata_processor
    processor.register_device(_make_test_device(DEVICE_TOKEN_1))
    _feed_states(
        processor,
        DEVICE_TOKEN_1,
        {
            "/Engine/Deck1/Play": {"state": True},
            "/Engine/Deck1/Track/ArtistName": {"string": "Stale Artist"},
            "/Engine/Deck1/Track/SongName": {"string": "Stale Song"},
        },
    )
    assert processor.get_playing_track() is not None

    await denon_plugin.stop()

    assert processor.get_playing_track() is None
    assert not processor._devices
    assert not processor._deck_play_times


@pytest.mark.asyncio
async def test_unregister_device_clears_state(denon_plugin):
    """Test device unregistration removes its decks from consideration"""
    processor = denon_plugin.metadata_processor
    processor.register_device(_make_test_device(DEVICE_TOKEN_1))
    _feed_states(
        processor,
        DEVICE_TOKEN_1,
        {
            "/Engine/Deck1/Play": {"state": True},
            "/Engine/Deck1/Track/ArtistName": {"string": "Test Artist"},
            "/Engine/Deck1/Track/SongName": {"string": "Test Song"},
        },
    )
    assert processor.get_playing_track() is not None

    processor.unregister_device(DEVICE_TOKEN_1)
    assert processor.get_playing_track() is None
    assert not processor._deck_play_times


def test_pack_utf16_string():
    """Test UTF-16 string packing"""
    # ASCII
    result = StagelinqProtocol.pack_utf16_string("Test")
    # Should be 4 bytes length + UTF-16 BE encoded "Test"
    assert len(result) >= 4
    # First 4 bytes should be length in big endian
    length = int.from_bytes(result[:4], "big")
    assert length == len(result) - 4

    # Non-ASCII: accented letter
    s_accented = "Café"
    result_accented = StagelinqProtocol.pack_utf16_string(s_accented)
    length_accented = int.from_bytes(result_accented[:4], "big")
    assert length_accented == len(result_accented) - 4
    # Decode and check
    decoded_accented = result_accented[4:].decode("utf-16-be")
    assert decoded_accented == s_accented

    # Non-ASCII: emoji
    s_emoji = "Test 🎵"
    result_emoji = StagelinqProtocol.pack_utf16_string(s_emoji)
    length_emoji = int.from_bytes(result_emoji[:4], "big")
    assert length_emoji == len(result_emoji) - 4
    decoded_emoji = result_emoji[4:].decode("utf-16-be")
    assert decoded_emoji == s_emoji


def test_unpack_utf16_string():
    """Test UTF-16 string unpacking"""
    # ASCII
    test_string = "Hello"
    packed = StagelinqProtocol.pack_utf16_string(test_string)
    unpacked, offset = StagelinqProtocol.unpack_utf16_string(packed)
    assert unpacked == test_string
    assert offset == len(packed)

    # Non-ASCII: accented letter
    s_accented = "Café"
    packed_accented = StagelinqProtocol.pack_utf16_string(s_accented)
    unpacked_accented, offset_accented = StagelinqProtocol.unpack_utf16_string(packed_accented)
    assert unpacked_accented == s_accented
    assert offset_accented == len(packed_accented)

    # Non-ASCII: emoji
    s_emoji = "Test 🎵"
    packed_emoji = StagelinqProtocol.pack_utf16_string(s_emoji)
    unpacked_emoji, offset_emoji = StagelinqProtocol.unpack_utf16_string(packed_emoji)
    assert unpacked_emoji == s_emoji
    assert offset_emoji == len(packed_emoji)


def test_unpack_utf16_string_insufficient_data():
    """Test unpacking with insufficient data raises error"""
    with pytest.raises(StagelinqError):
        StagelinqProtocol.unpack_utf16_string(b"abc")  # Too short


@pytest.mark.asyncio
async def test_defaults(denon_bootstrap):
    """Test default configuration values are set correctly"""
    _plugin = nowplaying.inputs.denon.Plugin(config=denon_bootstrap)

    # Check that defaults were applied
    timeout = denon_bootstrap.cparser.value("denon/discovery_timeout", type=float)
    assert timeout == 5.0

    deckskip = denon_bootstrap.cparser.value("denon/deckskip")
    assert deckskip is None


@pytest.mark.asyncio
async def test_load_save_deckskip_settings(denon_plugin):
    """Test deck skip settings load/save"""

    # Mock widget with checkboxes
    class MockWidget:  # pylint: disable=too-few-public-methods
        """mock"""

        def __init__(self):
            self.denon_deck1_skip_checkbox = MockCheckbox()
            self.denon_deck2_skip_checkbox = MockCheckbox()
            self.denon_deck3_skip_checkbox = MockCheckbox()
            self.denon_deck4_skip_checkbox = MockCheckbox()

    class MockCheckbox:
        """mock"""

        def __init__(self):
            self._checked = False

        def setChecked(self, checked):  # pylint: disable=invalid-name
            """mock"""
            self._checked = checked

        def isChecked(self):  # pylint: disable=invalid-name
            """mock"""
            return self._checked

    widget = MockWidget()

    # Test saving with some checkboxes checked
    widget.denon_deck1_skip_checkbox.setChecked(True)
    widget.denon_deck3_skip_checkbox.setChecked(True)

    denon_plugin._save_deckskip_settings(widget)

    # Check that values were saved
    deckskip = denon_plugin.config.cparser.value("denon/deckskip")
    assert set(deckskip) == {"1", "3"}

    # Test loading back
    widget2 = MockWidget()
    denon_plugin._load_deckskip_settings(widget2)

    assert widget2.denon_deck1_skip_checkbox.isChecked()
    assert not widget2.denon_deck2_skip_checkbox.isChecked()
    assert widget2.denon_deck3_skip_checkbox.isChecked()
    assert not widget2.denon_deck4_skip_checkbox.isChecked()


class FakeStreamWriter:
    """Minimal StreamWriter stand-in for connection tests"""

    def __init__(self):
        self.written = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        """collect written bytes"""
        self.written += data

    async def drain(self) -> None:
        """no-op"""

    def close(self) -> None:
        """mark closed"""
        self.closed = True

    async def wait_closed(self) -> None:
        """no-op"""

    @staticmethod
    def get_extra_info(_name: str) -> tuple[str, int]:
        """fake socket address info"""
        return ("127.0.0.1", 12345)


def _make_test_device(token: bytes, software_name: str = "JP14") -> DenonDevice:
    """Build a DenonDevice for connection tests"""
    return DenonDevice(
        ipaddr="127.0.0.1",
        port=50010,
        name="sc6000m",
        software_name=software_name,
        software_version="3.4.0",
        token=token,
    )


def _patch_open_connection(monkeypatch, reader, writer):
    """Patch asyncio.open_connection to return the given fake streams"""

    async def fake_open_connection(_host, _port):
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)


@pytest.mark.asyncio
async def test_connect_to_device_handles_device_services_request(monkeypatch):
    """Test service reading survives the device sending its own ServicesRequest first"""
    our_token = StagelinqProtocol.generate_token()
    device_token = StagelinqProtocol.generate_token()
    manager = ConnectionManager(our_token)
    device = _make_test_device(device_token)

    reader = asyncio.StreamReader()
    # Device asks what services we offer before announcing its own
    reader.feed_data(struct.pack(">I", MSG_SERVICES_REQUEST) + device_token)
    reader.feed_data(StagelinqProtocol.create_service_announcement(device_token, "StateMap", 42))
    reader.feed_data(StagelinqProtocol.create_reference_message(device_token, our_token))
    writer = FakeStreamWriter()
    _patch_open_connection(monkeypatch, reader, writer)

    services = await manager.connect_to_device(device)

    assert [(service.name, service.port) for service in services] == [("StateMap", 42)]
    await manager.cleanup()


@pytest.mark.asyncio
async def test_connect_to_device_unknown_message_stops_cleanly(monkeypatch):
    """Test an unknown message id stops parsing without discarding found services"""
    our_token = StagelinqProtocol.generate_token()
    device_token = StagelinqProtocol.generate_token()
    manager = ConnectionManager(our_token)
    device = _make_test_device(device_token)

    reader = asyncio.StreamReader()
    reader.feed_data(StagelinqProtocol.create_service_announcement(device_token, "StateMap", 42))
    # Unknown message id: cannot be skipped safely, must stop parsing
    reader.feed_data(struct.pack(">I", 0xDEADBEEF))
    writer = FakeStreamWriter()
    _patch_open_connection(monkeypatch, reader, writer)

    services = await manager.connect_to_device(device)

    assert [(service.name, service.port) for service in services] == [("StateMap", 42)]
    await manager.cleanup()


@pytest.mark.asyncio
async def test_disconnect_device_releases_connection(monkeypatch):
    """Test disconnect_device cancels the keepalive task and closes the writer"""
    our_token = StagelinqProtocol.generate_token()
    device_token = StagelinqProtocol.generate_token()
    manager = ConnectionManager(our_token)
    device = _make_test_device(device_token)

    reader = asyncio.StreamReader()
    reader.feed_data(StagelinqProtocol.create_reference_message(device_token, our_token))
    writer = FakeStreamWriter()
    _patch_open_connection(monkeypatch, reader, writer)

    await manager.connect_to_device(device)
    assert manager.active[device_token].main_writer is writer
    ref_task = manager.active[device_token].ref_task

    await manager.disconnect_device(device_token)

    assert writer.closed
    assert not manager.active
    assert ref_task.done()

    # Disconnecting an unknown device is a no-op
    await manager.disconnect_device(device_token)


@pytest.mark.asyncio
async def test_connect_to_device_failure_stops_keepalive(monkeypatch):
    """Test handshake failure cancels the keepalive task and closes the writer"""
    our_token = StagelinqProtocol.generate_token()
    device_token = StagelinqProtocol.generate_token()
    manager = ConnectionManager(our_token)
    device = _make_test_device(device_token)

    class FailingWriter(FakeStreamWriter):
        """Writer whose drain fails, aborting the handshake"""

        async def drain(self) -> None:
            raise OSError("handshake failure")

    reader = asyncio.StreamReader()
    writer = FailingWriter()
    _patch_open_connection(monkeypatch, reader, writer)

    pre_tasks = set(asyncio.all_tasks())

    with pytest.raises(OSError):
        await manager.connect_to_device(device)

    assert writer.closed
    assert not manager.active
    # The keepalive task must be fully finished before the exception
    # propagates, not left pending in the event loop; compare against a
    # pre-call snapshot so unrelated runner tasks cannot flake this
    leftover = [task for task in asyncio.all_tasks() - pre_tasks if not task.done()]
    assert not leftover


@pytest.mark.asyncio
async def test_source_agent_version_semantic_lowest(denon_plugin):
    """Test mixed-firmware rigs report the semantically lowest version"""
    manager = denon_plugin.connection_manager
    for token, version in [(DEVICE_TOKEN_1, "5.0.10"), (DEVICE_TOKEN_2, "5.0.4")]:
        device = DenonDevice(
            ipaddr="127.0.0.1",
            port=50010,
            name="sc6000m",
            software_name="JP14",
            software_version=version,
            token=token,
        )
        manager.active[token] = DeviceConnection(
            device=device,
            main_writer=FakeStreamWriter(),
            ref_task=asyncio.create_task(asyncio.sleep(0)),
        )

    data = denon_plugin.get_source_agent_data()
    # Lexicographic sort would pick "5.0.10"; semantic ordering picks "5.0.4"
    assert data["source_agent_version"] == "5.0.4"
    await manager.cleanup()


@pytest.mark.asyncio
async def test_connect_to_device_cancellation_stops_keepalive(monkeypatch):
    """Test cancelling an in-flight connect releases the keepalive and socket"""
    our_token = StagelinqProtocol.generate_token()
    device_token = StagelinqProtocol.generate_token()
    manager = ConnectionManager(our_token)
    device = _make_test_device(device_token)

    # Reader never receives data: connect blocks in readexactly
    reader = asyncio.StreamReader()
    writer = FakeStreamWriter()
    _patch_open_connection(monkeypatch, reader, writer)

    pre_tasks = set(asyncio.all_tasks())

    connect_task = asyncio.create_task(manager.connect_to_device(device))
    await asyncio.sleep(0)  # let it reach the read loop
    connect_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connect_task

    assert writer.closed
    assert not manager.active
    leftover = [task for task in asyncio.all_tasks() - pre_tasks if not task.done()]
    assert not leftover


@pytest.mark.asyncio
async def test_duplicate_player_numbers_warn_once(denon_plugin, caplog):
    """Test duplicate player numbers warn once and keep a stable ordering"""
    processor = denon_plugin.metadata_processor
    for token in (DEVICE_TOKEN_1, DEVICE_TOKEN_2):
        processor.register_device(_make_test_device(token))
        _feed_states(
            processor,
            token,
            {
                "/Client/Preferences/Player": {"string": "1"},
                "/Engine/Deck1/Play": {"state": True},
                "/Engine/Deck1/Track/ArtistName": {"string": "Artist"},
                "/Engine/Deck1/Track/SongName": {"string": "Song"},
            },
        )

    with caplog.at_level("WARNING"):
        first = processor._enumerate_logical_decks()
        second = processor._enumerate_logical_decks()

    warnings = [rec for rec in caplog.records if "same player number" in rec.message]
    assert len(warnings) == 1
    # Ordering is arbitrary but stable across enumerations
    assert first == second
    assert [deck for deck, _, _ in first] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_reconcile_devices_guards(denon_plugin, monkeypatch):
    """Test reconciliation skips connected, in-flight, and backed-off devices"""
    attempted = []

    async def fake_setup(device):
        attempted.append(device.token)
        denon_plugin._attempting.discard(device.token)

    monkeypatch.setattr(denon_plugin, "_setup_device", fake_setup)
    device1 = _make_test_device(DEVICE_TOKEN_1)
    device2 = _make_test_device(DEVICE_TOKEN_2)

    # Duplicate announcements in one pass produce a single attempt
    denon_plugin._reconcile_devices([device1, device1])
    await asyncio.gather(*denon_plugin._setup_tasks)
    assert attempted == [DEVICE_TOKEN_1]

    # An in-flight attempt is not duplicated
    denon_plugin._attempting.add(DEVICE_TOKEN_1)
    denon_plugin._reconcile_devices([device1])
    await asyncio.gather(*denon_plugin._setup_tasks)
    assert attempted == [DEVICE_TOKEN_1]
    denon_plugin._attempting.discard(DEVICE_TOKEN_1)

    # A backed-off device is skipped; others still connect
    denon_plugin._backoff_until[DEVICE_TOKEN_1] = time.monotonic() + 60.0
    denon_plugin._reconcile_devices([device1, device2])
    await asyncio.gather(*denon_plugin._setup_tasks)
    assert attempted == [DEVICE_TOKEN_1, DEVICE_TOKEN_2]

    # Once the backoff expires, the device is retried
    denon_plugin._backoff_until[DEVICE_TOKEN_1] = time.monotonic() - 1.0
    denon_plugin._reconcile_devices([device1])
    await asyncio.gather(*denon_plugin._setup_tasks)
    assert attempted == [DEVICE_TOKEN_1, DEVICE_TOKEN_2, DEVICE_TOKEN_1]


@pytest.mark.asyncio
async def test_monitor_subscribes_expected_states(monkeypatch):
    """Test StateMap subscriptions include audibility and device-identity states"""
    our_token = StagelinqProtocol.generate_token()
    device_token = StagelinqProtocol.generate_token()
    manager = ConnectionManager(our_token)
    device = _make_test_device(device_token)
    service = DenonService(name="StateMap", port=50011)

    reader = asyncio.StreamReader()
    reader.feed_eof()
    writer = FakeStreamWriter()
    _patch_open_connection(monkeypatch, reader, writer)

    await manager.monitor_state_changes(device, service, lambda state: None)

    for state_path in [
        "/Engine/Deck1/Track/ArtistName",
        "/Engine/Deck4/ExternalMixerVolume",
        "/Engine/Deck1/DeckIsMaster",
        "/Client/Preferences/Player",
        "/Engine/DeckCount",
        "/Engine/Sync/Network/MasterStatus",
        "/Mixer/CrossfaderPosition",
    ]:
        assert state_path.encode("utf-16be") in writer.written

    await manager.cleanup()


@pytest.mark.parametrize(
    "software_name,expected",
    [
        ("JP14", True),  # SC6000M - player
        ("JP07", True),  # SC5000 - player
        ("JC11", True),  # PRIME 4 - controller
        ("NH08", True),  # MIXSTREAM PRO - controller
        ("JM08", False),  # DN-X1800 Prime - mixer, refuses inbound connections
        ("JM10", False),  # DN-X1850 Prime - mixer
        ("JC20", False),  # LC6000 - accessory, no engine
        ("OfflineAnalyzer", False),
        ("SoundSwitchEmbedded", False),
        ("SSS0", False),  # SoundSwitch desktop
        ("Resolume Arena", False),
        ("XX99", True),  # unknown software name - assume future hardware
    ],
)
def test_device_is_connectable(software_name, expected):
    """Test discovery classification: only players/controllers get connections"""
    token = StagelinqProtocol.generate_token()
    device = _make_test_device(token, software_name=software_name)
    assert device.is_connectable() is expected


def test_get_broadcast_addresses():
    """Test broadcast address enumeration always includes the global broadcast"""
    addresses = ConnectionManager._get_broadcast_addresses()
    assert "255.255.255.255" in addresses
    for address in addresses:
        assert not address.startswith("127.")
