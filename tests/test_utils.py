#!/usr/bin/env python3
"""test utils not covered elsewhere"""

from unittest.mock import Mock

import pytest

import nowplaying.utils  # pylint: disable=import-error
import nowplaying.utils.filters  # pylint: disable=import-error


def results(expected, metadata):
    """take a metadata result and compare to expected"""
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]
    assert metadata == {}


def test_songsubst1(bootstrap):
    """test file name substition1"""
    config = bootstrap
    config.cparser.setValue("quirks/filesubst", True)
    config.cparser.setValue("quirks/filesubstin", "/songs")
    config.cparser.setValue("quirks/filesubstout", "/newlocation")
    location = nowplaying.utils.songpathsubst(config, "/songs/mysong")
    assert location == "/newlocation/mysong"


def test_songsubst2forward(bootstrap):
    """test file name substition1"""
    config = bootstrap
    config.cparser.setValue("quirks/filesubst", True)
    config.cparser.setValue("quirks/slashmode", "toback")
    location = nowplaying.utils.songpathsubst(config, "/songs/myband/mysong")
    assert location == "\\songs\\myband\\mysong"


def test_songsubst2backward(bootstrap):
    """test file name substition1"""
    config = bootstrap
    config.cparser.setValue("quirks/filesubst", True)
    config.cparser.setValue("quirks/slashmode", "toforward")
    location = nowplaying.utils.songpathsubst(config, "\\songs\\myband\\mysong")
    assert location == "/songs/myband/mysong"


def test_songsubst_tounix(bootstrap):
    """test file name substition1"""
    config = bootstrap
    config.cparser.setValue("quirks/filesubst", True)
    config.cparser.setValue("quirks/filesubstin", "Z:/Music")
    config.cparser.setValue("quirks/filesubstout", "/Music")
    config.cparser.setValue("quirks/slashmode", "toforward")
    location = nowplaying.utils.songpathsubst(config, "Z:\\Music\\Band\\Song")
    assert location == "/Music/Band/Song"


def test_songsubst_towindows(bootstrap):
    """test file name substition1"""
    config = bootstrap
    config.cparser.setValue("quirks/filesubst", True)
    config.cparser.setValue("quirks/filesubstin", "\\Music")
    config.cparser.setValue("quirks/filesubstout", "Z:\\Music")
    config.cparser.setValue("quirks/slashmode", "toback")
    location = nowplaying.utils.songpathsubst(config, "/Music/Band/Song")
    assert location == "Z:\\Music\\Band\\Song"


@pytest.mark.parametrize(
    "input_title,expected_clean_title",
    [
        ("Test - Explicit", "Test"),
        ("Test - Dirty", "Test"),
        ("Test - Clean", "Test"),
        ("Clean", "Clean"),
        ("Test (Clean)", "Test"),
        ("Test [Clean]", "Test"),
        ("Test (Clean) (Single Mix)", "Test (Single Mix)"),
        ("Test (Clean) (Official Music Video)", "Test"),
        ("Test (Clean) [official music video]", "Test"),
        ("Clean [official music video]", "Clean"),
        ("Clean - Clean", "Clean"),
        ("Clean - Official Music Video", "Clean"),
    ],
)
def test_basicstrip_parameterized(bootstrap, input_title, expected_clean_title):
    """Test title stripping with various patterns"""
    config = bootstrap
    config.cparser.setValue("settings/stripextras", True)
    metadata = {"title": input_title}
    title = nowplaying.utils.filters.titlestripper(config=config, title=metadata["title"])
    assert metadata["title"] == input_title  # Original unchanged
    assert title == expected_clean_title


@pytest.mark.parametrize(
    "conversion_func,expected_header,format_name",
    [
        (nowplaying.utils.image2png, b"\211PNG\r\n\032\n", "PNG"),
        (nowplaying.utils.image2avif, b"\x00\x00\x00 ftypavif", "AVIF"),
    ],
)
def test_image_conversion_parameterized(getroot, conversion_func, expected_header, format_name):
    """Test image conversion to different formats"""
    filename = getroot.joinpath("tests", "images", "1x1.jpg")
    with open(filename, "rb") as fhin:
        image = fhin.read()

    # Convert image to target format
    converted_data = conversion_func(image)
    assert converted_data.startswith(expected_header), (
        f"Converted {format_name} should have correct header"
    )

    # Convert again (should be idempotent)
    converted_data2 = conversion_func(converted_data)
    assert converted_data2 == converted_data, f"Re-converting {format_name} should be idempotent"


@pytest.mark.parametrize(
    "artist_name,expected_variations",
    [
        ("The Call", ["the call", "call"]),
        ("Prince", ["prince"]),
        (
            "Presidents of the United States of America",
            ["presidents of the united states of america"],
        ),
        (
            "Grimes feat Janelle Monáe",
            ["grimes feat janelle monáe", "grimes feat janelle monae", "grimes"],
        ),
        ("G feat J and featuring U", ["g feat j and featuring u", "g"]),
        (
            "MӨЯIS BLΛK feat. grabyourface",
            [
                "mөяis blλk feat. grabyourface",
                "moris blak feat. grabyourface",
                "mөяis blλk feat grabyourface",
                "moris blak feat grabyourface",
                "mөяis blλk",
                "moris blak",
            ],
        ),
        ("†HR33ΔM", ["†hr33δm", "thr33am", "hr33δm", "hr33am"]),
        ("Ultra Naté", ["ultra naté", "ultra nate"]),
        ("A★Teens", ["a★teens", "a teens"]),  # less than ideal
    ],
)
def test_artist_variations_parameterized(artist_name, expected_variations):
    """Test artist name variations generation"""
    namelist = nowplaying.utils.artist_name_variations(artist_name)
    assert len(namelist) == len(expected_variations)
    for i, expected in enumerate(expected_variations):
        assert namelist[i] == expected


def test_safe_stopevent_check_normal():
    """Test safe_stopevent_check with normal stopevent behavior"""
    # Test normal case - stopevent not set
    mock_stopevent = Mock()
    mock_stopevent.is_set.return_value = False
    assert nowplaying.utils.safe_stopevent_check(mock_stopevent) is False

    # Test normal case - stopevent is set
    mock_stopevent.is_set.return_value = True
    assert nowplaying.utils.safe_stopevent_check(mock_stopevent) is True


@pytest.mark.parametrize(
    "exception_type,error_message,expected_description",
    [
        (BrokenPipeError, "The pipe is being closed", "BrokenPipeError"),
        (EOFError, "EOF error", "EOFError"),
        (OSError, "OS error", "OSError"),
    ],
)
def test_safe_stopevent_check_windows_shutdown_errors(
    exception_type, error_message, expected_description
):
    """Test safe_stopevent_check handles Windows shutdown pipe errors gracefully"""
    mock_stopevent = Mock()
    mock_stopevent.is_set.side_effect = exception_type(error_message)
    result = nowplaying.utils.safe_stopevent_check(mock_stopevent)
    assert result is True, f"{expected_description} should be treated as stop requested"


def test_safe_stopevent_check_windows_specific():
    """Test safe_stopevent_check specifically simulates Windows [WinError 232] scenario"""
    # This simulates the exact Windows error: BrokenPipeError [WinError 232]
    mock_stopevent = Mock()

    # Create a more realistic Windows BrokenPipeError
    windows_error = BrokenPipeError(232, "The pipe is being closed")
    mock_stopevent.is_set.side_effect = windows_error

    result = nowplaying.utils.safe_stopevent_check(mock_stopevent)
    assert result is True, "Windows BrokenPipeError [WinError 232] should be handled gracefully"

    # Verify the mock was called (showing the function tried to check stopevent)
    mock_stopevent.is_set.assert_called_once()


def test_safe_stopevent_check_preserves_other_exceptions():
    """Test that safe_stopevent_check only catches OS-level shutdown errors"""
    mock_stopevent = Mock()

    # Test that non-OS exceptions are not caught (they should propagate)
    mock_stopevent.is_set.side_effect = ValueError("Some other error")

    with pytest.raises(ValueError, match="Some other error"):
        nowplaying.utils.safe_stopevent_check(mock_stopevent)


@pytest.mark.parametrize(
    "input_phrase,expected_success,expected_error_contains",
    [
        ("my custom phrase", True, ""),
        ("", False, "cannot be empty"),
        ("a", False, "at least 2 characters"),
        ("x" * 51, False, "50 characters or less"),
        ("invalid(chars)", False, "invalid characters"),
        ("explicit", False, "already exists in the predefined list"),
        ("clean", False, "already exists in the predefined list"),
        ("  valid phrase  ", True, ""),  # Test trimming
        ("valid-phrase", True, ""),
        ("valid phrase 123", True, ""),
        ("phrase[with]brackets", False, "invalid characters"),
        ("phrase(with)parens", False, "invalid characters"),
        ("phrase\\with\\backslash", False, "invalid characters"),
        ("phrase^with^caret", False, "invalid characters"),
        ("phrase$with$dollar", False, "invalid characters"),
        ("phrase|with|pipe", False, "invalid characters"),
        ("phrase*with*asterisk", False, "invalid characters"),
        ("phrase+with+plus", False, "invalid characters"),
        ("phrase?with?question", False, "invalid characters"),
        ("phrase{with}braces", False, "invalid characters"),
    ],
)
def test_simple_filter_manager_add_custom_phrase_validation(
    input_phrase, expected_success, expected_error_contains
):
    """Test custom phrase validation with various inputs"""
    manager = nowplaying.utils.filters.SimpleFilterManager()

    success, error = manager.add_custom_phrase(input_phrase)
    assert success is expected_success
    if expected_error_contains:
        assert expected_error_contains in error
    else:
        assert error == ""


def test_simple_filter_manager_custom_phrase_lifecycle():
    """Test custom phrase add/remove lifecycle"""
    manager = nowplaying.utils.filters.SimpleFilterManager()

    # Add valid custom phrase
    success, _ = manager.add_custom_phrase("my custom phrase")
    assert success is True
    assert "my custom phrase" in manager.custom_phrases
    assert manager.is_custom_phrase("my custom phrase")

    # Test adding duplicate custom phrase
    success, error = manager.add_custom_phrase("my custom phrase")
    assert success is False
    assert "already exists" in error

    # Test removing custom phrase
    assert manager.remove_custom_phrase("my custom phrase") is True
    assert "my custom phrase" not in manager.custom_phrases

    # Test removing predefined phrase (should fail)
    assert manager.remove_custom_phrase("explicit") is False

    # Test removing non-existent phrase
    assert manager.remove_custom_phrase("nonexistent") is False


def test_simple_filter_manager_get_all_phrases():
    """Test getting all phrases including custom ones"""
    manager = nowplaying.utils.filters.SimpleFilterManager()

    # Initially should have only predefined phrases
    all_phrases = manager.get_all_phrases()
    assert len(all_phrases) == len(nowplaying.utils.filters.SIMPLE_FILTER_PHRASES)
    assert "explicit" in all_phrases

    # Add custom phrase
    manager.add_custom_phrase("my custom phrase")
    all_phrases = manager.get_all_phrases()
    assert len(all_phrases) == len(nowplaying.utils.filters.SIMPLE_FILTER_PHRASES) + 1
    assert "my custom phrase" in all_phrases
    assert all_phrases == sorted(all_phrases)  # Should be sorted


def test_simple_filter_manager_config_with_custom_phrases(bootstrap):
    """Test config save/load with custom phrases"""
    config = bootstrap
    manager = nowplaying.utils.filters.SimpleFilterManager()

    # Add custom phrase and set some formats
    manager.add_custom_phrase("my custom phrase")
    manager.set_phrase_format("my custom phrase", "dash", True)
    manager.set_phrase_format("my custom phrase", "paren", True)

    # Save to config
    manager.save_to_config(config.cparser)

    # Create new manager and load
    manager2 = nowplaying.utils.filters.SimpleFilterManager()
    manager2.load_from_config(config.cparser)

    # Verify custom phrase was loaded
    assert "my custom phrase" in manager2.custom_phrases
    assert manager2.get_phrase_format("my custom phrase", "dash") is True
    assert manager2.get_phrase_format("my custom phrase", "paren") is True
    assert manager2.get_phrase_format("my custom phrase", "bracket") is False


@pytest.mark.parametrize(
    "custom_phrase,enabled_formats,input_title,expected_title",
    [
        ("my custom filter", ["dash"], "Song Title - My Custom Filter", "Song Title"),
        ("my custom filter", ["paren"], "Song Title (My Custom Filter)", "Song Title"),
        ("my custom filter", ["bracket"], "Song Title [My Custom Filter]", "Song Title"),
        ("my custom filter", ["dash", "paren"], "Song Title - My Custom Filter", "Song Title"),
        ("my custom filter", ["dash", "paren"], "Song Title (My Custom Filter)", "Song Title"),
        (
            "my custom filter",
            ["dash", "paren"],
            "Song Title [My Custom Filter]",
            "Song Title [My Custom Filter]",
        ),
        ("special phrase", ["dash"], "Test Song - Special Phrase", "Test Song"),
        ("remix version", ["paren"], "Artist - Track (Remix Version)", "Artist - Track"),
        ("custom edit", ["bracket"], "Song [Custom Edit]", "Song"),
        # Test case insensitive matching
        ("my custom filter", ["dash"], "Song Title - MY CUSTOM FILTER", "Song Title"),
        ("my custom filter", ["paren"], "Song Title (my custom filter)", "Song Title"),
    ],
)
def test_custom_phrase_filtering(
    bootstrap, custom_phrase, enabled_formats, input_title, expected_title
):
    """Test that custom phrases work in title filtering"""
    config = bootstrap
    config.cparser.setValue("settings/stripextras", True)

    # Create manager and add custom phrase
    manager = nowplaying.utils.filters.SimpleFilterManager()
    manager.add_custom_phrase(custom_phrase)

    # Enable specified formats
    for format_type in ["dash", "paren", "bracket"]:
        manager.set_phrase_format(custom_phrase, format_type, format_type in enabled_formats)

    # Save to config
    manager.save_to_config(config.cparser)

    # Test filtering
    result = nowplaying.utils.filters.titlestripper(config=config, title=input_title)
    assert result == expected_title


def test_plain_format_filtering(bootstrap):
    """Test that plain format filtering works correctly"""
    config = bootstrap
    config.cparser.setValue("settings/stripextras", True)

    # Create manager and add phrase with plain format enabled
    manager = nowplaying.utils.filters.SimpleFilterManager()
    manager.add_custom_phrase("my test phrase")
    manager.set_phrase_format("my test phrase", "plain", True)

    # Save to config
    manager.save_to_config(config.cparser)

    # Test plain string removal (anywhere in title)
    result = nowplaying.utils.filters.titlestripper(
        config=config, title="Song Title my test phrase here"
    )
    assert result == "Song Title  here"

    # Test case insensitive
    result = nowplaying.utils.filters.titlestripper(
        config=config, title="Song Title MY TEST PHRASE here"
    )
    assert result == "Song Title  here"


# pylint: disable=protected-access
def test_regex_compilation_caching():
    """Test that regex patterns are cached and only recompiled when dirty"""
    manager = nowplaying.utils.filters.SimpleFilterManager()

    # Add some phrases
    manager.add_custom_phrase("test phrase")
    manager.set_phrase_format("test phrase", "dash", True)

    # First call should compile patterns
    assert manager._patterns_dirty is True
    patterns1 = manager.get_compiled_regex_list()
    assert manager._patterns_dirty is False
    assert len(patterns1) > 0

    # Second call should return cached patterns (same objects)
    patterns2 = manager.get_compiled_regex_list()
    assert patterns1 is patterns2  # Should be the exact same object
    assert manager._patterns_dirty is False

    # Modify configuration - should mark as dirty
    manager.set_phrase_format("test phrase", "paren", True)
    assert manager._patterns_dirty is True

    # Next call should recompile
    patterns3 = manager.get_compiled_regex_list()
    assert patterns1 is not patterns3  # Should be different objects
    assert manager._patterns_dirty is False
    assert len(patterns3) > len(patterns1)  # Should have more patterns

    # Adding custom phrase should mark as dirty
    manager.add_custom_phrase("another phrase")
    assert manager._patterns_dirty is True

    # Removing custom phrase should mark as dirty
    manager.remove_custom_phrase("another phrase")
    assert manager._patterns_dirty is True


def test_regex_caching_across_config_loads():
    """Test that loading from config invalidates cache correctly"""
    manager = nowplaying.utils.filters.SimpleFilterManager()

    # Set up initial state
    manager.add_custom_phrase("test phrase")
    manager.set_phrase_format("test phrase", "dash", True)

    # Get compiled patterns
    patterns1 = manager.get_compiled_regex_list()
    assert manager._patterns_dirty is False

    # Mock config object
    mock_config = Mock()
    mock_config.allKeys.return_value = []

    # Loading from config should mark as dirty
    manager.load_from_config(mock_config)
    assert manager._patterns_dirty is True

    # Next call should recompile
    patterns2 = manager.get_compiled_regex_list()
    assert patterns1 is not patterns2
    assert manager._patterns_dirty is False
