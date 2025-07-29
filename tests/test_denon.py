#!/usr/bin/env python3
"""Tests for Denon DJ StagelinQ input plugin"""
# pylint: disable=protected-access,redefined-outer-name

import pytest

import nowplaying.inputs.denon


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
        token = nowplaying.inputs.denon.Plugin._generate_token()
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
    result = denon_plugin._extract_numeric_value(data)
    assert result == 0.75

    # Test with value field
    data = {"value": 0.5}
    result = denon_plugin._extract_numeric_value(data)
    assert result == 0.5

    # Test with no valid fields
    data = {"other": "invalid"}
    result = denon_plugin._extract_numeric_value(data, default=0.25)
    assert result == 0.25

    # Test with non-dict input
    result = denon_plugin._extract_numeric_value("not_dict", default=0.1)
    assert result == 0.1

    # Test with invalid numeric value
    data = {"data": "not_a_number"}
    result = denon_plugin._extract_numeric_value(data, default=0.3)
    assert result == 0.3


@pytest.mark.asyncio
async def test_get_crossfader_position(denon_plugin):
    """Test crossfader position retrieval"""
    # Test with no crossfader data (should default to center)
    denon_plugin.current_metadata = {}
    result = denon_plugin._get_crossfader_position()
    assert result == 0.5

    # Test with crossfader data
    denon_plugin.current_metadata = {"/Mixer/CrossfaderPosition": {"data": 0.8}}
    result = denon_plugin._get_crossfader_position()
    assert result == 0.8


@pytest.mark.asyncio
async def test_calculate_effective_volume_fader_zero(denon_plugin):
    """Test effective volume calculation with zero fader"""
    # Any deck with fader at 0 should have 0 effective volume
    for deck in [1, 2, 3, 4]:
        result = denon_plugin._calculate_effective_volume(deck, 0.0, 0.5)
        assert result == 0.0


@pytest.mark.asyncio
async def test_calculate_effective_volume_left_decks(denon_plugin):
    """Test effective volume calculation for left side decks (1, 3)"""
    fader_pos = 0.8

    # Crossfader full left - left decks should be audible
    result = denon_plugin._calculate_effective_volume(1, fader_pos, 0.0)
    assert result == fader_pos

    result = denon_plugin._calculate_effective_volume(3, fader_pos, 0.0)
    assert result == fader_pos

    # Crossfader full right - left decks should be silent
    result = denon_plugin._calculate_effective_volume(1, fader_pos, 1.0)
    assert result == 0.0

    result = denon_plugin._calculate_effective_volume(3, fader_pos, 1.0)
    assert result == 0.0

    # Crossfader center - left decks should be audible
    result = denon_plugin._calculate_effective_volume(1, fader_pos, 0.5)
    assert result == fader_pos


@pytest.mark.asyncio
async def test_calculate_effective_volume_right_decks(denon_plugin):
    """Test effective volume calculation for right side decks (2, 4)"""
    fader_pos = 0.8

    # Crossfader full right - right decks should be audible
    result = denon_plugin._calculate_effective_volume(2, fader_pos, 1.0)
    assert result == fader_pos

    result = denon_plugin._calculate_effective_volume(4, fader_pos, 1.0)
    assert result == fader_pos

    # Crossfader full left - right decks should be silent
    result = denon_plugin._calculate_effective_volume(2, fader_pos, 0.0)
    assert result == 0.0

    result = denon_plugin._calculate_effective_volume(4, fader_pos, 0.0)
    assert result == 0.0

    # Crossfader center - right decks should be audible
    result = denon_plugin._calculate_effective_volume(2, fader_pos, 0.5)
    assert result == fader_pos


@pytest.mark.asyncio
async def test_calculate_effective_volume_crossfader_transition(denon_plugin):
    """Test crossfader transition zones"""
    fader_pos = 1.0

    # Test transition zone for left deck (0.5 < pos <= 0.8)
    # At crossfader 0.65, left deck should be partially audible
    result = denon_plugin._calculate_effective_volume(1, fader_pos, 0.65)
    expected = fader_pos * (1.0 - ((0.65 - 0.5) / 0.3))  # Should be 0.5
    assert abs(result - expected) < 0.01

    # Test transition zone for right deck (0.2 <= pos < 0.5)
    # At crossfader 0.35, right deck should be partially audible
    result = denon_plugin._calculate_effective_volume(2, fader_pos, 0.35)
    expected = fader_pos * ((0.35 - 0.2) / 0.3)  # Should be 0.5
    assert abs(result - expected) < 0.01


@pytest.mark.asyncio
async def test_getplayingtrack_single_audible_deck(denon_plugin):
    """Test track selection with single audible deck"""
    # Set up metadata for one playing, audible track
    denon_plugin.current_metadata = {
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
    denon_plugin.current_metadata = {
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
    denon_plugin.current_metadata = {
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

    denon_plugin.current_metadata = {
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
    denon_plugin.current_metadata = {
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
    result = nowplaying.inputs.denon._pack_utf16_string("Test")
    # Should be 4 bytes length + UTF-16 BE encoded "Test"
    assert len(result) >= 4
    # First 4 bytes should be length in big endian
    length = int.from_bytes(result[:4], "big")
    assert length == len(result) - 4


def test_unpack_utf16_string():
    """Test UTF-16 string unpacking"""
    # Create a packed string
    test_string = "Hello"
    packed = nowplaying.inputs.denon._pack_utf16_string(test_string)

    # Unpack it
    unpacked, offset = nowplaying.inputs.denon._unpack_utf16_string(packed)
    assert unpacked == test_string
    assert offset == len(packed)


def test_unpack_utf16_string_insufficient_data():
    """Test unpacking with insufficient data raises error"""
    with pytest.raises(nowplaying.inputs.denon.StagelinqError):
        nowplaying.inputs.denon._unpack_utf16_string(b"abc")  # Too short


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
