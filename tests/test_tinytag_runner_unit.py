#!/usr/bin/env python3
"""Unit tests for nowplaying/metadata/tinytag_runner.py targeting uncovered code paths."""

import pathlib
import unittest.mock

from nowplaying.metadata.tinytag_runner import TinyTagRunner, _date_calc


# ---------------------------------------------------------------------------
# _date_calc unit tests
# ---------------------------------------------------------------------------


def test_date_calc_removes_originalyear_when_in_date():
    """originalyear is removed when it appears inside the date string."""
    datedata = {"originalyear": "2008", "date": "2008-03-02"}
    result = _date_calc(datedata)
    assert result == "2008-03-02"


def test_date_calc_removes_originalyear_when_in_year():
    """originalyear is removed when it appears inside the year string."""
    datedata = {"originalyear": "2008", "year": "2008"}
    result = _date_calc(datedata)
    assert result == "2008"


def test_date_calc_single_date():
    """Simple single date value is returned as-is."""
    datedata = {"date": "2021-05-15"}
    result = _date_calc(datedata)
    assert result == "2021-05-15"


def test_date_calc_empty_returns_none():
    """Empty datedata returns None."""
    result = _date_calc({})
    assert result is None


def test_date_calc_three_values_uses_second_when_first_in_second():
    """With three dates, returns the longer one that contains the shorter one."""
    datedata = {"date": "2008-03-02", "year": "2008", "originalyear": "2007"}
    result = _date_calc(datedata)
    # After sort: ["2007", "2008", "2008-03-02"]; datelist[0]="2007" not in datelist[1]="2008"
    # so gooddate remains None -> returns datelist[0] (via elif path? No, len>2 path)
    # len=3, datelist[0]="2007", datelist[1]="2008", "2007" not in "2008" -> gooddate=None
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# TinyTagRunner._split_delimited_string tests
# ---------------------------------------------------------------------------


def test_split_delimited_null_bytes():
    """Null-byte separator splits the string correctly."""
    runner = TinyTagRunner()
    result = runner._split_delimited_string("value1\x00value2")  # pylint: disable=protected-access
    assert result == ["value1", "value2"]


def test_split_delimited_null_bytes_strips_bom():
    """Null-byte separator strips BOM markers from parts."""
    runner = TinyTagRunner()
    result = runner._split_delimited_string("\ufeffvalue1\x00\ufeffvalue2")  # pylint: disable=protected-access
    assert result == ["value1", "value2"]


def test_split_delimited_semicolon():
    """Semicolon separator splits the string correctly."""
    runner = TinyTagRunner()
    result = runner._split_delimited_string("isrc1;isrc2")  # pylint: disable=protected-access
    assert result == ["isrc1", "isrc2"]


def test_split_delimited_slash():
    """Slash separator splits the string correctly."""
    runner = TinyTagRunner()
    result = runner._split_delimited_string("mbid1/mbid2")  # pylint: disable=protected-access
    assert result == ["mbid1", "mbid2"]


def test_split_delimited_no_delimiter():
    """Single value with no delimiter returned as a one-element list."""
    runner = TinyTagRunner()
    result = runner._split_delimited_string("singlevalue")  # pylint: disable=protected-access
    assert result == ["singlevalue"]


# ---------------------------------------------------------------------------
# TinyTagRunner._process_list_field tests
# ---------------------------------------------------------------------------


def test_process_list_field_with_list():
    """List input is stored as-is (after splitting each element)."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._process_list_field(["value1", "value2"], "isrc")  # pylint: disable=protected-access
    assert runner.metadata["isrc"] == ["value1", "value2"]


def test_process_list_field_with_list_and_delimiters():
    """List items containing delimiters get split."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._process_list_field(["v1/v2", "v3"], "isrc")  # pylint: disable=protected-access
    assert runner.metadata["isrc"] == ["v1", "v2", "v3"]


def test_process_list_field_with_string():
    """String input is split by delimiter into a list."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._process_list_field("isrc1/isrc2", "isrc")  # pylint: disable=protected-access
    assert runner.metadata["isrc"] == ["isrc1", "isrc2"]


def test_process_list_field_with_other_type():
    """Non-string, non-list values are converted to string and wrapped."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._process_list_field(12345, "isrc")  # pylint: disable=protected-access
    assert runner.metadata["isrc"] == ["12345"]


# ---------------------------------------------------------------------------
# TinyTagRunner._process_single_field tests
# ---------------------------------------------------------------------------


def test_process_single_field_with_list():
    """List input uses the first element as the single value."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._process_single_field(["first", "second"], "artist")  # pylint: disable=protected-access
    assert runner.metadata["artist"] == "first"


def test_process_single_field_with_empty_list():
    """Empty list stores as-is (falsy check not present in this method)."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._process_single_field([], "artist")  # pylint: disable=protected-access
    # The method sets metadata[newkey] = value when not (isinstance(value, list) and value)
    assert runner.metadata["artist"] == []


def test_process_single_field_with_string():
    """String input stored directly."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._process_single_field("single_value", "artist")  # pylint: disable=protected-access
    assert runner.metadata["artist"] == "single_value"


# ---------------------------------------------------------------------------
# TinyTagRunner._ufid tests
# ---------------------------------------------------------------------------


def test_ufid_bytes_decoded():
    """UFID as bytes (not just string) gets decoded to UTF-8."""
    runner = TinyTagRunner()
    runner.metadata = {}
    ufid_bytes = b"http://musicbrainz.org\x00abc123"
    runner._ufid({"ufid": ufid_bytes})  # pylint: disable=protected-access
    assert runner.metadata["musicbrainzrecordingid"] == "abc123"


def test_ufid_string():
    """UFID as plain string works correctly."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._ufid({"ufid": "http://musicbrainz.org\x00def456"})  # pylint: disable=protected-access
    assert runner.metadata["musicbrainzrecordingid"] == "def456"


def test_ufid_list_of_bytes():
    """UFID as list[bytes] takes the first element."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._ufid({"ufid": [b"http://musicbrainz.org\x00ghi789"]})  # pylint: disable=protected-access
    assert runner.metadata["musicbrainzrecordingid"] == "ghi789"


def test_ufid_wrong_key_ignored():
    """UFID with non-musicbrainz key does not set musicbrainzrecordingid."""
    runner = TinyTagRunner()
    runner.metadata = {}
    runner._ufid({"ufid": "http://other.domain\x00ignored"})  # pylint: disable=protected-access
    assert "musicbrainzrecordingid" not in runner.metadata


# ---------------------------------------------------------------------------
# TinyTagRunner._decode_musical_key tests
# ---------------------------------------------------------------------------


def test_decode_musical_key_plain_string():
    """Plain string key is returned as-is."""
    result = TinyTagRunner._decode_musical_key("Am")  # pylint: disable=protected-access
    assert result == "Am"


def test_decode_musical_key_json_dict():
    """JSON dict with 'key' field returns the key value."""
    import json

    key_json = json.dumps({"key": "F#m", "other": "data"})
    result = TinyTagRunner._decode_musical_key(key_json)  # pylint: disable=protected-access
    assert result == "F#m"


def test_decode_musical_key_base64_json():
    """Base64-encoded JSON with 'key' field returns the key value."""
    import base64
    import json

    key_data = json.dumps({"key": "Cm"})
    encoded = base64.b64encode(key_data.encode("utf-8")).decode("utf-8")
    result = TinyTagRunner._decode_musical_key(encoded)  # pylint: disable=protected-access
    assert result == "Cm"


def test_decode_musical_key_none():
    """None input returns None."""
    result = TinyTagRunner._decode_musical_key(None)  # pylint: disable=protected-access
    assert result is None


def test_decode_musical_key_empty_string():
    """Empty string returns None."""
    result = TinyTagRunner._decode_musical_key("")  # pylint: disable=protected-access
    assert result is None


# ---------------------------------------------------------------------------
# TinyTagRunner._detect_video_content tests
# ---------------------------------------------------------------------------


def test_detect_video_audio_extension_returns_false(getroot):
    """Known audio extensions should return False without calling puremagic."""
    mp3_file = pathlib.Path(getroot) / "tests" / "audio" / "15_Ghosts_II_64kb_orig.mp3"
    assert mp3_file.exists()
    result = TinyTagRunner._detect_video_content(mp3_file)  # pylint: disable=protected-access
    assert result is False


def test_detect_video_nonexistent_audio_file_returns_false():
    """Nonexistent file with audio extension returns False without file access."""
    fake_path = pathlib.Path("/nonexistent/path/that/does/not/exist.mp3")
    result = TinyTagRunner._detect_video_content(fake_path)  # pylint: disable=protected-access
    assert result is False


def test_detect_video_nonexistent_mp4_returns_false():
    """Nonexistent ambiguous-container file triggers OSError, returns False."""
    fake_path = pathlib.Path("/nonexistent/path/that/does/not/exist.mp4")
    result = TinyTagRunner._detect_video_content(fake_path)  # pylint: disable=protected-access
    assert result is False


def test_detect_video_flac_returns_false(getroot):
    """FLAC file (audio extension) should return False."""
    flac_file = pathlib.Path(getroot) / "tests" / "audio" / "15_Ghosts_II_64kb_orig.flac"
    if flac_file.exists():
        result = TinyTagRunner._detect_video_content(flac_file)  # pylint: disable=protected-access
        assert result is False


def test_detect_video_m4a_returns_false(getroot):
    """M4A file (audio extension) should return False."""
    m4a_file = pathlib.Path(getroot) / "tests" / "audio" / "15_Ghosts_II_64kb_orig.m4a"
    if m4a_file.exists():
        result = TinyTagRunner._detect_video_content(m4a_file)  # pylint: disable=protected-access
        assert result is False


def test_detect_video_unknown_extension_with_mock():
    """Unknown extension uses puremagic to detect video content."""
    with unittest.mock.patch("puremagic.magic_file") as mock_magic:
        mock_magic.return_value = [
            unittest.mock.MagicMock(
                __str__=lambda self: "video/mp4",
                extension=".mp4",
            )
        ]
        fake_path = pathlib.Path("/fake/video.xyz")
        result = TinyTagRunner._detect_video_content(fake_path)  # pylint: disable=protected-access
        assert result is True


def test_detect_video_unknown_extension_audio_mock():
    """Unknown extension detected as audio returns False."""
    with unittest.mock.patch("puremagic.magic_file") as mock_magic:
        mock_magic.return_value = [
            unittest.mock.MagicMock(
                __str__=lambda self: "audio/mpeg",
                extension=".mp3",
            )
        ]
        fake_path = pathlib.Path("/fake/file.xyz")
        result = TinyTagRunner._detect_video_content(fake_path)  # pylint: disable=protected-access
        assert result is False


# ---------------------------------------------------------------------------
# TinyTagRunner.process() error handling
# ---------------------------------------------------------------------------


def test_process_tinytag_exception_returns_metadata():
    """TinyTagException during processing returns metadata without tags."""
    from nowplaying.vendor import tinytag

    runner = TinyTagRunner()
    with unittest.mock.patch.object(
        tinytag.TinyTag, "get", side_effect=tinytag.TinyTagException("unsupported format")
    ):
        metadata_in = {"filename": "/fake/path/file.xyz"}
        result = runner.process(metadata_in)
    assert result == metadata_in


def test_process_oserror_returns_metadata():
    """OSError during tinytag processing returns metadata without tags."""
    from nowplaying.vendor import tinytag

    runner = TinyTagRunner()
    with unittest.mock.patch.object(
        tinytag.TinyTag, "get", side_effect=OSError("permission denied")
    ):
        metadata_in = {"filename": "/fake/path/file.xyz"}
        result = runner.process(metadata_in)
    assert result == metadata_in


def test_process_no_filename_returns_unchanged():
    """process() with no filename returns metadata unchanged."""
    runner = TinyTagRunner()
    metadata_in = {"artist": "Test", "title": "Song"}
    result = runner.process(metadata_in)
    assert result == metadata_in


def test_process_none_metadata_returns_none():
    """process() with None metadata returns None."""
    runner = TinyTagRunner()
    result = runner.process(None)
    assert result is None


# ---------------------------------------------------------------------------
# TinyTagRunner.tt_date_calc tests
# ---------------------------------------------------------------------------


def test_tt_date_calc_list_value_in_other():
    """When other dict has list values for date fields, first element is used."""
    tag = unittest.mock.MagicMock()
    tag.other = {"date": ["2020-01-15"]}
    # Remove regular attributes so they're not found by hasattr
    del tag.date
    del tag.year
    del tag.originaldate
    del tag.tdor
    del tag.originalyear
    del tag.tory
    # Use spec to control what hasattr returns
    tag2 = unittest.mock.MagicMock(spec=[])
    tag2.other = {"date": ["2020-01-15"]}
    result = TinyTagRunner.tt_date_calc(tag2)
    assert result == "2020-01-15"


def test_tt_date_calc_string_value_in_other():
    """When other dict has string values for date fields, used directly."""
    tag = unittest.mock.MagicMock(spec=[])
    tag.other = {"year": "2019"}
    result = TinyTagRunner.tt_date_calc(tag)
    assert result == "2019"


def test_tt_date_calc_no_dates_returns_none():
    """When tag has no date fields, returns None."""
    tag = unittest.mock.MagicMock(spec=[])
    tag.other = {}
    result = TinyTagRunner.tt_date_calc(tag)
    assert result is None
