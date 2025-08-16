#!/usr/bin/env python3
"""Test video detection functionality"""

import pathlib
import tempfile
import unittest.mock

import pytest

from nowplaying.metadata import TinyTagRunner, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS


class TestVideoDetection:
    """Test video detection using puremagic"""

    def test_audio_only_extensions(self):
        """Test that known audio extensions are detected as audio-only"""
        # Test audio extensions from constants
        for ext in AUDIO_EXTENSIONS:
            # Create a fake path (doesn't need to exist for this test)
            fake_path = pathlib.Path(f"test_audio{ext}")

            # Mock puremagic to return empty types (like our MP3 test file)
            with unittest.mock.patch("nowplaying.metadata.puremagic.magic_file", return_value=[]):
                result = TinyTagRunner._detect_video_content(fake_path)
                assert result is False, f"Extension {ext} should be detected as audio-only"

    def test_video_extensions(self):
        """Test that known video extensions are detected as video"""
        # Test video extensions from constants
        for ext in VIDEO_EXTENSIONS:
            fake_path = pathlib.Path(f"test_video{ext}")

            # Mock puremagic to return empty types
            with unittest.mock.patch("nowplaying.metadata.puremagic.magic_file", return_value=[]):
                result = TinyTagRunner._detect_video_content(fake_path)
                assert result is True, f"Extension {ext} should be detected as video"

    def test_mp4_ambiguous_container(self):
        """Test MP4 container detection logic"""
        mp4_path = pathlib.Path("test.mp4")

        # Mock video-only MP4 file
        mock_video_type = unittest.mock.MagicMock()
        mock_video_type.extension = ".mp4"
        mock_video_type.__str__ = lambda self: "MPEG-4 video"

        with unittest.mock.patch(
            "nowplaying.metadata.puremagic.magic_file", return_value=[mock_video_type]
        ):
            result = TinyTagRunner._detect_video_content(mp4_path)
            assert result is True, "MP4 with video indicator should be detected as video"

        # Mock audio-only MP4 file
        mock_audio_type = unittest.mock.MagicMock()
        mock_audio_type.extension = ".mp4"
        mock_audio_type.__str__ = lambda self: "MPEG-4 audio"

        with unittest.mock.patch(
            "nowplaying.metadata.puremagic.magic_file", return_value=[mock_audio_type]
        ):
            result = TinyTagRunner._detect_video_content(mp4_path)
            # Should be False when puremagic indicates audio content
            assert result is False, "MP4 with audio indicator should be detected as audio"

        # Test MP4 with no clear indicators - should default to video
        mock_neutral_type = unittest.mock.MagicMock()
        mock_neutral_type.extension = ".mp4"
        mock_neutral_type.__str__ = lambda self: "MPEG-4 container"

        with unittest.mock.patch(
            "nowplaying.metadata.puremagic.magic_file", return_value=[mock_neutral_type]
        ):
            result = TinyTagRunner._detect_video_content(mp4_path)
            assert result is True, (
                "MP4 extension should default to video when no clear audio/video indicator"
            )

    def test_unknown_extension_fallback(self):
        """Test fallback to puremagic for unknown extensions"""
        unknown_path = pathlib.Path("test.unknown")

        # Mock with video type
        mock_video_type = unittest.mock.MagicMock()
        mock_video_type.__str__ = lambda self: "Some video format"

        with unittest.mock.patch(
            "nowplaying.metadata.puremagic.magic_file", return_value=[mock_video_type]
        ):
            result = TinyTagRunner._detect_video_content(unknown_path)
            assert result is True, "Unknown extension with video type should be detected as video"

        # Mock with audio type
        mock_audio_type = unittest.mock.MagicMock()
        mock_audio_type.__str__ = lambda self: "Some audio format"

        with unittest.mock.patch(
            "nowplaying.metadata.puremagic.magic_file", return_value=[mock_audio_type]
        ):
            result = TinyTagRunner._detect_video_content(unknown_path)
            assert result is False, "Unknown extension with audio type should be detected as audio"

    def test_puremagic_exception_handling(self):
        """Test that exceptions in puremagic are handled gracefully"""
        test_path = pathlib.Path("test.mp3")

        with unittest.mock.patch(
            "nowplaying.metadata.puremagic.magic_file", side_effect=Exception("Test error")
        ):
            result = TinyTagRunner._detect_video_content(test_path)
            assert result is False, "Exceptions should default to audio-only"

    def test_real_audio_files(self):
        """Test with real audio files from test suite"""
        # Test real MP3 file
        mp3_path = pathlib.Path("tests/audio/15_Ghosts_II_64kb_orig.mp3")
        if mp3_path.exists():
            result = TinyTagRunner._detect_video_content(mp3_path)
            assert result is False, "Real MP3 file should be detected as audio-only"

        # Test real M4A file
        m4a_path = pathlib.Path("tests/audio/15_Ghosts_II_64kb_orig.m4a")
        if m4a_path.exists():
            result = TinyTagRunner._detect_video_content(m4a_path)
            assert result is False, "Real M4A file should be detected as audio-only"

    def test_excludes_audio_containers_from_video_detection(self):
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
            result = TinyTagRunner._detect_video_content(m4a_path)
            assert result is False, "M4A extension should override video type detection"

        # Test .f4a extension
        f4a_path = pathlib.Path("test.f4a")
        with unittest.mock.patch(
            "nowplaying.metadata.puremagic.magic_file", return_value=[mock_video_type]
        ):
            result = TinyTagRunner._detect_video_content(f4a_path)
            assert result is False, "F4A extension should override video type detection"
