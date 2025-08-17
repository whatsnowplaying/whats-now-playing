#!/usr/bin/env python3
"""Test video detection functionality"""

import pathlib
import tempfile
import unittest.mock

import puremagic

from nowplaying.metadata import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, TinyTagRunner


def test_audio_only_extensions():
    """Test that known audio extensions are detected as audio-only"""
    # Test audio extensions from constants
    for ext in AUDIO_EXTENSIONS:
        # Create a fake path (doesn't need to exist for this test)
        fake_path = pathlib.Path(f"test_audio{ext}")

        # Mock puremagic to return empty types (like our MP3 test file)
        with unittest.mock.patch("nowplaying.metadata.puremagic.magic_file", return_value=[]):
            result = TinyTagRunner._detect_video_content(fake_path)  # pylint: disable=protected-access
            assert result is False, f"Extension {ext} should be detected as audio-only"


def test_video_extensions():
    """Test that known video extensions are detected as video"""
    # Test video extensions from constants
    for ext in VIDEO_EXTENSIONS:
        fake_path = pathlib.Path(f"test_video{ext}")

        # Mock puremagic to return empty types
        with unittest.mock.patch("nowplaying.metadata.puremagic.magic_file", return_value=[]):
            result = TinyTagRunner._detect_video_content(fake_path)  # pylint: disable=protected-access
            assert result is True, f"Extension {ext} should be detected as video"


def test_mp4_ambiguous_container():
    """Test MP4 container detection logic"""
    mp4_path = pathlib.Path("test.mp4")

    # Mock video-only MP4 file
    mock_video_type = unittest.mock.MagicMock()
    mock_video_type.extension = ".mp4"
    mock_video_type.__str__ = lambda self: "MPEG-4 video"

    with unittest.mock.patch(
        "nowplaying.metadata.puremagic.magic_file", return_value=[mock_video_type]
    ):
        result = TinyTagRunner._detect_video_content(mp4_path)  # pylint: disable=protected-access
        assert result is True, "MP4 with video indicator should be detected as video"

    # Mock audio-only MP4 file
    mock_audio_type = unittest.mock.MagicMock()
    mock_audio_type.extension = ".mp4"
    mock_audio_type.__str__ = lambda self: "MPEG-4 audio"

    with unittest.mock.patch(
        "nowplaying.metadata.puremagic.magic_file", return_value=[mock_audio_type]
    ):
        result = TinyTagRunner._detect_video_content(mp4_path)  # pylint: disable=protected-access
        # Should be False when puremagic indicates audio content
        assert result is False, "MP4 with audio indicator should be detected as audio"

    # Test MP4 with no clear indicators - should default to video
    mock_neutral_type = unittest.mock.MagicMock()
    mock_neutral_type.extension = ".mp4"
    mock_neutral_type.__str__ = lambda self: "MPEG-4 container"

    with unittest.mock.patch(
        "nowplaying.metadata.puremagic.magic_file", return_value=[mock_neutral_type]
    ):
        result = TinyTagRunner._detect_video_content(mp4_path)  # pylint: disable=protected-access
        assert result is True, (
            "MP4 extension should default to video when no clear audio/video indicator"
        )


def test_unknown_extension_fallback():
    """Test fallback to puremagic for unknown extensions"""
    unknown_path = pathlib.Path("test.unknown")

    # Mock with video type
    mock_video_type = unittest.mock.MagicMock()
    mock_video_type.__str__ = lambda self: "Some video format"

    with unittest.mock.patch(
        "nowplaying.metadata.puremagic.magic_file", return_value=[mock_video_type]
    ):
        result = TinyTagRunner._detect_video_content(unknown_path)  # pylint: disable=protected-access
        assert result is True, "Unknown extension with video type should be detected as video"

    # Mock with audio type
    mock_audio_type = unittest.mock.MagicMock()
    mock_audio_type.__str__ = lambda self: "Some audio format"

    with unittest.mock.patch(
        "nowplaying.metadata.puremagic.magic_file", return_value=[mock_audio_type]
    ):
        result = TinyTagRunner._detect_video_content(unknown_path)  # pylint: disable=protected-access
        assert result is False, "Unknown extension with audio type should be detected as audio"


def test_puremagic_exception_handling():
    """Test that exceptions in puremagic are handled gracefully"""
    unknown_path = pathlib.Path("test.unknown")  # Unknown extension to trigger puremagic call

    # Test various exception types - all should return False (default to audio)
    exception_types = [
        OSError("File not found"),
        IOError("I/O error"),
        PermissionError("Access denied"),
        ValueError("Input was empty"),
        puremagic.PureError("Not a regular file"),
        RuntimeError("Unexpected issue"),
    ]

    for error_type in exception_types:
        with unittest.mock.patch(
            "nowplaying.metadata.puremagic.magic_file", side_effect=error_type
        ):
            result = TinyTagRunner._detect_video_content(unknown_path)  # pylint: disable=protected-access
            assert result is False, f"{type(error_type).__name__} should default to audio-only"


def test_real_audio_files():
    """Test with real audio files from test suite"""
    # Test real MP3 file
    mp3_path = pathlib.Path("tests/audio/15_Ghosts_II_64kb_orig.mp3")
    if mp3_path.exists():
        result = TinyTagRunner._detect_video_content(mp3_path)  # pylint: disable=protected-access
        assert result is False, "Real MP3 file should be detected as audio-only"

    # Test real M4A file
    m4a_path = pathlib.Path("tests/audio/15_Ghosts_II_64kb_orig.m4a")
    if m4a_path.exists():
        result = TinyTagRunner._detect_video_content(m4a_path)  # pylint: disable=protected-access
        assert result is False, "Real M4A file should be detected as audio-only"


def test_excludes_audio_containers_from_video_detection():
    """Test that .m4a/.f4a extensions are never detected as video"""
    # Mock a scenario where puremagic detects video types but file has audio extension
    mock_video_type = unittest.mock.MagicMock()
    mock_video_type.extension = ".mp4"  # This might trigger video detection
    mock_video_type.__str__ = lambda self: "MPEG-4 video"

    # Test .m4a extension
    m4a_path = pathlib.Path("test.m4a")
    with unittest.mock.patch(
        "nowplaying.metadata.puremagic.magic_file", return_value=[mock_video_type]
    ):
        result = TinyTagRunner._detect_video_content(m4a_path)  # pylint: disable=protected-access
        assert result is False, "M4A extension should override video type detection"

    # Test .f4a extension
    f4a_path = pathlib.Path("test.f4a")
    with unittest.mock.patch(
        "nowplaying.metadata.puremagic.magic_file", return_value=[mock_video_type]
    ):
        result = TinyTagRunner._detect_video_content(f4a_path)  # pylint: disable=protected-access
        assert result is False, "F4A extension should override video type detection"


def test_puremagic_optimization():
    """Test that video detection optimizes by short-circuiting puremagic calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = pathlib.Path(tmpdir)

        # Test audio extensions - should short-circuit without calling puremagic
        for ext in [".mp3", ".flac", ".wav", ".ogg"]:
            test_file = tmp_path / f"test{ext}"
            test_file.touch()

            with unittest.mock.patch("nowplaying.metadata.puremagic.magic_file") as mock_puremagic:
                result = TinyTagRunner._detect_video_content(test_file)  # pylint: disable=protected-access
                assert result is False, f"Audio extension {ext} should return False"
                assert not mock_puremagic.called, (
                    f"Audio extension {ext} should not call puremagic"
                )

        # Test clear video extensions - should short-circuit without calling puremagic
        for ext in [".avi", ".mkv", ".wmv", ".flv", ".webm", ".vob", ".ogv"]:
            test_file = tmp_path / f"test{ext}"
            test_file.touch()

            with unittest.mock.patch("nowplaying.metadata.puremagic.magic_file") as mock_puremagic:
                result = TinyTagRunner._detect_video_content(test_file)  # pylint: disable=protected-access
                assert result is True, f"Video extension {ext} should return True"
                assert not mock_puremagic.called, (
                    f"Video extension {ext} should not call puremagic"
                )

        # Test ambiguous containers - should call puremagic for verification
        for ext in [".mp4", ".m4v", ".mov"]:
            test_file = tmp_path / f"test{ext}"
            test_file.touch()

            with unittest.mock.patch("nowplaying.metadata.puremagic.magic_file") as mock_puremagic:
                # Mock to return video content
                mock_type = unittest.mock.MagicMock()
                mock_type.extension = ext
                mock_type.__str__ = lambda self: "video/mp4"
                mock_puremagic.return_value = [mock_type]

                result = TinyTagRunner._detect_video_content(test_file)  # pylint: disable=protected-access
                assert result is True, (
                    f"Ambiguous extension {ext} should return True with video content"
                )
                assert mock_puremagic.called, f"Ambiguous extension {ext} should call puremagic"

        # Test unknown extensions - should call puremagic
        for ext in [".xyz", ".unknown"]:
            test_file = tmp_path / f"test{ext}"
            test_file.touch()

            with unittest.mock.patch("nowplaying.metadata.puremagic.magic_file") as mock_puremagic:
                # Mock to return non-video content
                mock_type = unittest.mock.MagicMock()
                mock_type.__str__ = lambda self: "application/octet-stream"
                mock_puremagic.return_value = [mock_type]

                result = TinyTagRunner._detect_video_content(test_file)  # pylint: disable=protected-access
                assert result is False, (
                    f"Unknown extension {ext} should return False with non-video content"
                )
                assert mock_puremagic.called, f"Unknown extension {ext} should call puremagic"
