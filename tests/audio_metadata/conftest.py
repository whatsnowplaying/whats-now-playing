#!/usr/bin/env python3
"""Enhanced pytest fixtures for audio metadata testing."""

import os
import sys
from pathlib import Path

import pytest

# Add project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(scope="session")
def audio_test_config():
    """Configuration for audio metadata tests."""
    return {
        "libraries": ["tinytag"],
        "formats": [".mp3", ".flac", ".m4a", ".aiff"],
        "test_categories": ["basic", "complex", "multi_value", "multi_image"],
        "stable_test_timeout": 10.0,  # seconds
        "performance_test_iterations": 10,
    }


@pytest.fixture(scope="session")
def audio_test_files(getroot):
    """Organized audio test files by category."""
    audio_dir = Path(getroot) / "tests" / "audio"

    return {
        "basic": {
            "mp3": audio_dir / "15_Ghosts_II_64kb_orig.mp3",
            "flac": audio_dir / "15_Ghosts_II_64kb_orig.flac",
            "m4a": audio_dir / "15_Ghosts_II_64kb_orig.m4a",
            "aiff": audio_dir / "15_Ghosts_II_64kb_orig.aiff",
        },
        "complex": {
            "mp3": audio_dir / "15_Ghosts_II_64kb_füllytâgged.mp3",
            "flac": audio_dir / "15_Ghosts_II_64kb_füllytâgged.flac",
            "m4a": audio_dir / "15_Ghosts_II_64kb_füllytâgged.m4a",
            "aiff": audio_dir / "15_Ghosts_II_64kb_füllytâgged.aiff",
        },
        "multi_value": {
            "mp3": audio_dir / "multi.mp3",
            "flac": audio_dir / "multi.flac",
            "m4a": audio_dir / "multi.m4a",
        },
        "multi_image": {"m4a": audio_dir / "multiimage.m4a"},
        "edge_cases": {
            "fake_origdate_mp3": audio_dir / "15_Ghosts_II_64kb_fake_origdate.mp3",
            "fake_origdate_m4a": audio_dir / "15_Ghosts_II_64kb_fake_origdate.m4a",
            "fake_origyear_mp3": audio_dir / "15_Ghosts_II_64kb_fake_origyear.mp3",
            "fake_origyear_m4a": audio_dir / "15_Ghosts_II_64kb_fake_origyear.m4a",
            "fake_ody_mp3": audio_dir / "15_Ghosts_II_64kb_fake_ody.mp3",
            "fake_ody_m4a": audio_dir / "15_Ghosts_II_64kb_fake_ody.m4a",
        },
    }


@pytest.fixture
def skip_missing_files():
    """Fixture to skip tests when audio files are missing."""

    def _skip_if_missing(file_path):
        if not file_path.exists():
            pytest.skip(f"Audio test file not found: {file_path}")

    return _skip_if_missing


@pytest.fixture
def library_compatibility():
    """Fixture providing known library compatibility information."""
    return {
        "tinytag": {
            "supported_formats": [".mp3", ".flac", ".m4a", ".aiff", ".wav", ".ogg"],
            "image_support": True,
            "multivalue_handling": "extra_dict",
            "known_limitations": [],
        },
        # audio_metadata no longer available
    }


@pytest.fixture
def expected_metadata_fields():
    """Fixture providing expected metadata fields for test validation."""
    return {
        "basic_fields": ["artist", "title", "album"],
        "common_optional": ["duration", "bitrate", "genre", "date", "track"],
        "advanced_fields": [
            "albumartist",
            "composer",
            "disc",
            "track_total",
            "disc_total",
            "bpm",
            "key",
            "isrc",
            "label",
            "publisher",
        ],
        "musicbrainz_fields": [
            "musicbrainz_artistid",
            "musicbrainz_albumid",
            "musicbrainz_trackid",
            "musicbrainz_releasegroupid",
        ],
        "image_fields": ["coverimageraw", "front_cover", "pictures"],
        "multivalue_fields": ["isrc", "musicbrainz_artistid", "artistwebsites"],
    }


@pytest.fixture
def metadata_extraction_helper():
    """Helper fixture for consistent metadata extraction."""
    import tinytag  # pylint: disable=import-outside-toplevel

    class MetadataExtractor:
        """Helper class for extracting metadata from audio files."""

        @staticmethod
        def extract_tinytag(filepath, include_images=False):
            """Extract metadata using tinytag with error handling."""
            try:
                return tinytag.TinyTag.get(str(filepath), image=include_images)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                return {"error": str(exc)}

        @staticmethod
        def normalize_field_names(data, library):
            """Normalize field names for consistent comparison."""
            if library == "tinytag":
                # TinyTag uses direct attributes and other dict
                normalized = {}
                if hasattr(data, "__dict__"):
                    for key, value in data.__dict__.items():
                        if value is not None and key != "extra":
                            normalized[key] = value

                    if hasattr(data, "other") and data.other:
                        for key, value in data.other.items():
                            normalized[f"other_{key}"] = value
                return normalized

            # Return empty dict for unsupported libraries
            return {}

    return MetadataExtractor()


@pytest.fixture
def performance_timer():
    """Fixture for timing metadata extraction operations."""
    import time  # pylint: disable=import-outside-toplevel
    from contextlib import contextmanager  # pylint: disable=import-outside-toplevel

    class PerformanceTimer:
        """Helper class for timing performance operations."""

        def __init__(self):
            self.timings = {}

        @contextmanager
        def time_operation(self, operation_name):
            """Context manager for timing operations."""
            start_time = time.time()
            try:
                yield
            finally:
                elapsed = time.time() - start_time
                if operation_name not in self.timings:
                    self.timings[operation_name] = []
                self.timings[operation_name].append(elapsed)

        def get_average_time(self, operation_name):
            """Get average time for an operation."""
            if operation_name in self.timings:
                times = self.timings[operation_name]
                return sum(times) / len(times)
            return None

        def get_all_timings(self):
            """Get all timing data."""
            return dict(self.timings)

    return PerformanceTimer()


@pytest.fixture(scope="session")
def test_data_validation():
    """Validate that required test data files exist and are accessible."""

    def _validate_test_data(audio_test_files):  # pylint: disable=redefined-outer-name
        """Validate test data and report missing files."""
        missing_files = []
        accessible_files = []

        for category, files in audio_test_files.items():
            for file_type, file_path in files.items():
                if not file_path.exists():
                    missing_files.append(f"{category}/{file_type}: {file_path}")
                else:
                    try:
                        # Try to read a few bytes to ensure file is accessible
                        with open(file_path, "rb") as file_handle:
                            file_handle.read(1024)
                        accessible_files.append(f"{category}/{file_type}")
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        missing_files.append(
                            f"{category}/{file_type}: {file_path} (read error: {exc})"
                        )

        return {
            "missing_files": missing_files,
            "accessible_files": accessible_files,
            "total_files": len(missing_files) + len(accessible_files),
        }

    return _validate_test_data


# Pytest markers for categorizing tests
def pytest_configure(config):  # pylint: disable=unused-argument
    """Configure custom pytest markers."""
    config.addinivalue_line("markers", "library_matrix: mark test as library feature matrix test")
    config.addinivalue_line("markers", "golden_master: mark test as golden master regression test")
    config.addinivalue_line("markers", "format_specific: mark test as format-specific test")
    config.addinivalue_line("markers", "multivalue: mark test as multi-value field test")
    config.addinivalue_line("markers", "upgrade_detection: mark test as upgrade detection test")
    config.addinivalue_line("markers", "performance: mark test as performance benchmark")
    config.addinivalue_line("markers", "slow: mark test as slow running")


# Test collection hook to report test organization
def pytest_collection_modifyitems(config, items):  # pylint: disable=unused-argument
    """Modify test collection to add marker-based organization."""
    for item in items:
        # Add slow marker to tests that might take time
        if "golden_master" in item.keywords or "upgrade_detection" in item.keywords:
            item.add_marker(pytest.mark.slow)

        # Add format-specific marker based on test name patterns
        if any(fmt in item.name for fmt in ["mp3", "flac", "m4a", "aiff"]):
            item.add_marker(pytest.mark.format_specific)


# Session-level reporting
def pytest_sessionfinish(session, exitstatus):  # pylint: disable=unused-argument
    """Report session-level test results."""
    if hasattr(session.config, "getoption") and session.config.getoption("--tb") != "no":
        print("\n" + "=" * 60)
        print("Audio Metadata Testing Session Complete")
        print("=" * 60)

        # Count tests by marker
        total_tests = len(session.items)
        matrix_tests = len([item for item in session.items if "library_matrix" in item.keywords])
        golden_tests = len([item for item in session.items if "golden_master" in item.keywords])
        format_tests = len([item for item in session.items if "format_specific" in item.keywords])

        print(f"Total audio metadata tests: {total_tests}")
        print(f"  Library matrix tests: {matrix_tests}")
        print(f"  Golden master tests: {golden_tests}")
        print(f"  Format-specific tests: {format_tests}")
        print("=" * 60)
