#!/usr/bin/env python3
"""Tests for Denon DJ StagelinQ input plugin"""
# pylint: disable=protected-access,redefined-outer-name

import asyncio
import struct

import pytest

import nowplaying.inputs.denon
from nowplaying.denon import StagelinqError
from nowplaying.denon.connection import ConnectionManager, _is_ignored_device
from nowplaying.denon.protocol import StagelinqProtocol
from nowplaying.denon.types import MSG_SERVICES_REQUEST, DenonDevice, DenonService


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
    assert denon_plugin.install() is False


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
async def test_get_crossfader_position(denon_plugin):
    """Test crossfader position retrieval"""
    # Test with no crossfader data (should default to center)
    denon_plugin.metadata_processor.current_metadata = {}
    result = denon_plugin.metadata_processor._get_crossfader_position()
    assert result == 0.5

    # Test with crossfader data
    denon_plugin.metadata_processor.current_metadata = {"/Mixer/CrossfaderPosition": {"data": 0.8}}
    result = denon_plugin.metadata_processor._get_crossfader_position()
    assert result == 0.8


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
    denon_plugin.metadata_processor.current_metadata = {
        "/Engine/Deck1/Play": {"state": True},
        "/Engine/Deck1/Track/ArtistName": {"string": "Test Artist"},
        "/Engine/Deck1/Track/SongName": {"string": "Test Song"},
        "/Mixer/CH1faderPosition": {"data": 0.8},
        "/Mixer/CrossfaderPosition": {"data": 0.5},
    }

    result = await denon_plugin.getplayingtrack()
    assert result is not None
    assert result["artist"] == "Test Artist"
    assert result["title"] == "Test Song"


@pytest.mark.asyncio
async def test_getplayingtrack_inaudible_deck(denon_plugin):
    """Test that tracks with low effective volume are filtered out"""
    # Set up metadata for playing track but with fader down
    denon_plugin.metadata_processor.current_metadata = {
        "/Engine/Deck1/Play": {"state": True},
        "/Engine/Deck1/Track/ArtistName": {"string": "Test Artist"},
        "/Engine/Deck1/Track/SongName": {"string": "Test Song"},
        "/Mixer/CH1faderPosition": {"data": 0.05},  # Very low fader
        "/Mixer/CrossfaderPosition": {"data": 0.5},
    }

    result = await denon_plugin.getplayingtrack()
    assert result is None  # Should be filtered out due to low volume


@pytest.mark.asyncio
async def test_getplayingtrack_multiple_decks_volume_priority(denon_plugin):
    """Test track selection prioritizes louder tracks"""
    # Set up two playing tracks with different volumes
    denon_plugin.metadata_processor.current_metadata = {
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
    }

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

    denon_plugin.metadata_processor.current_metadata = {
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
    }

    result = await denon_plugin.getplayingtrack()
    assert result is not None
    assert result["artist"] == "Selected Artist"
    assert result["title"] == "Selected Song"


@pytest.mark.asyncio
async def test_getplayingtrack_crossfader_filtering(denon_plugin):
    """Test crossfader position affects track selection"""
    denon_plugin.metadata_processor.current_metadata = {
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
    }

    result = await denon_plugin.getplayingtrack()
    assert result is not None
    assert result["artist"] == "Left Artist"
    assert result["title"] == "Left Song"


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
async def test_disconnect_main_releases_connection(monkeypatch):
    """Test disconnect_main cancels the keepalive task and closes the writer"""
    our_token = StagelinqProtocol.generate_token()
    device_token = StagelinqProtocol.generate_token()
    manager = ConnectionManager(our_token)
    device = _make_test_device(device_token)

    reader = asyncio.StreamReader()
    reader.feed_data(StagelinqProtocol.create_reference_message(device_token, our_token))
    writer = FakeStreamWriter()
    _patch_open_connection(monkeypatch, reader, writer)

    await manager.connect_to_device(device)
    assert manager.connections == [writer]
    assert len(manager.tasks) == 1

    await manager.disconnect_main()

    assert writer.closed
    assert not manager.connections
    assert not manager.tasks


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
    assert not manager.connections
    assert not manager.tasks
    # The keepalive task must be fully finished before the exception
    # propagates, not left pending in the event loop; compare against a
    # pre-call snapshot so unrelated runner tasks cannot flake this
    leftover = [task for task in asyncio.all_tasks() - pre_tasks if not task.done()]
    assert not leftover


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
        ("JP14", False),
        ("OfflineAnalyzer", True),
        ("SoundSwitchEmbedded", True),
    ],
)
def test_is_ignored_device(software_name, expected):
    """Test non-player StagelinQ processes are filtered from discovery"""
    token = StagelinqProtocol.generate_token()
    device = _make_test_device(token, software_name=software_name)
    assert _is_ignored_device(device) is expected


def test_get_broadcast_addresses():
    """Test broadcast address enumeration always includes the global broadcast"""
    addresses = ConnectionManager._get_broadcast_addresses()
    assert "255.255.255.255" in addresses
    for address in addresses:
        assert not address.startswith("127.")
