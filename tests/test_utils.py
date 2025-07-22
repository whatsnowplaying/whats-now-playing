#!/usr/bin/env python3
"""test utils not covered elsewhere"""

from unittest.mock import Mock

import pytest

import nowplaying.utils  # pylint: disable=import-error


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
def test_basicstrip_parameterized(input_title, expected_clean_title):
    """Test title stripping with various patterns"""
    metadata = {"title": input_title}
    title = nowplaying.utils.titlestripper_basic(title=metadata["title"])
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
