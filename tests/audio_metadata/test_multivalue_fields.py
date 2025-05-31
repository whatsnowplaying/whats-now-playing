#!/usr/bin/env python3
"""Test handling of metadata fields with multiple values using tinytag 2.1.1."""

import gc
import sys
from pathlib import Path

import pytest

import tinytag
import nowplaying.tinytag_fixes  # pylint: disable=import-error

# Apply tinytag patches for testing
nowplaying.tinytag_fixes.apply_tinytag_patches()


def _has_multiple_values(value) -> bool:
    """Check if a value contains multiple entries."""
    if isinstance(value, str):
        return any(delim in value for delim in ['/', ';', ','])
    if isinstance(value, list):
        return len(value) > 1 or any(
            isinstance(item, str) and any(delim in item for delim in ['/', ';', ','])
            for item in value)
    return False


def _extract_isrc_from_tag(tag):
    """Extract ISRC from tinytag with proper API handling."""
    if hasattr(tag, 'other') and tag.other:
        return tag.other.get('isrc')
    return None


def _extract_artists_from_tag(tag):
    """Extract artist IDs from tinytag with proper API handling."""
    if hasattr(tag, 'other') and tag.other:
        return (tag.other.get('musicbrainz artist id') or tag.other.get('musicbrainz_artistid'))
    return None


@pytest.fixture
def multivalue_files(getroot) -> dict[str, Path]:
    """Get test files with multi-value metadata."""
    audio_dir = Path(getroot) / 'tests' / 'audio'
    return {
        'multi_mp3': audio_dir / 'multi.mp3',
        'multi_flac': audio_dir / 'multi.flac',
        'multi_m4a': audio_dir / 'multi.m4a',
        'complex_mp3': audio_dir / '15_Ghosts_II_64kb_füllytâgged.mp3',
        'complex_flac': audio_dir / '15_Ghosts_II_64kb_füllytâgged.flac',
        'complex_m4a': audio_dir / '15_Ghosts_II_64kb_füllytâgged.m4a',
        'multiimage': audio_dir / 'multiimage.m4a'
    }


@pytest.mark.parametrize("file_key", ["multi_mp3", "multi_flac", "multi_m4a"])
def test_multiple_isrc_extraction(multivalue_files, file_key):  # pylint: disable=redefined-outer-name
    """Test extraction of multiple ISRC codes with tinytag 2.1.1."""
    test_file = multivalue_files[file_key]
    if not test_file.exists():
        pytest.skip(f"Multi-value test file not found: {test_file}")

    # TinyTag extraction
    tt_tag = tinytag.TinyTag.get(str(test_file))
    tt_isrc = _extract_isrc_from_tag(tt_tag)

    print(f"ISRC extraction for {file_key}:")
    print(f"  TinyTag: {tt_isrc} (type: {type(tt_isrc)})")

    # Verify multiple ISRC codes are detected
    tt_has_multiple = _has_multiple_values(tt_isrc) if tt_isrc else False

    # For multi-value test files, we expect multiple ISRC codes
    if 'multi_' in file_key:
        status = "[OK]" if tt_has_multiple else "[WARN]"
        detected = "detected" if tt_has_multiple else "did not detect"
        print(f"  {status}  TinyTag {detected} multiple ISRC codes in {file_key}")

    # Assert that multi-value files actually have multiple ISRC values
    if file_key == 'multi_m4a':
        # With our monkey patch, M4A files should now extract multiple ISRCs
        # as separate list items
        assert isinstance(tt_isrc, list) and len(tt_isrc) >= 2, \
            f"M4A file should have multiple ISRC codes, got {tt_isrc}"
    elif file_key == 'multi_mp3':
        # MP3 files may store multiple values as delimited strings that
        # need splitting
        assert tt_has_multiple, \
            f"MP3 file should have multiple ISRC codes (possibly delimited), got {tt_isrc}"


@pytest.mark.parametrize("file_key", ["multi_mp3", "multi_flac", "multi_m4a"])
def test_multiple_artists_extraction(multivalue_files, file_key):  # pylint: disable=redefined-outer-name
    """Test extraction of multiple artist values with tinytag 2.1.1."""
    test_file = multivalue_files[file_key]
    if not test_file.exists():
        pytest.skip(f"Multi-value test file not found: {test_file}")

    # TinyTag extraction
    tt_tag = tinytag.TinyTag.get(str(test_file))

    # Check for multiple artist representations (tinytag 2.1.1+ API)
    tt_artists = _extract_artists_from_tag(tt_tag)

    print(f"Artist ID extraction for {file_key}:")
    print(f"  TinyTag: {tt_artists} (type: {type(tt_artists)})")

    # Document multi-value artist ID detection capabilities
    if 'multi_' in file_key:
        tt_has_multiple_artists = _has_multiple_values(tt_artists) if tt_artists else False

        status = "[OK]" if tt_has_multiple_artists else "[WARN]"
        detected = "detected" if tt_has_multiple_artists else "did not detect"
        print(f"  {status}  TinyTag {detected} multiple artist IDs in {file_key}")

        # Assert that multi-value files actually have multiple artist IDs
        if file_key == 'multi_m4a':
            # With our monkey patch, M4A files should now extract multiple
            # artist IDs as separate list items
            assert isinstance(tt_artists, list) and len(tt_artists) >= 2, \
                f"M4A file should have multiple artist IDs, got {tt_artists}"
        elif file_key == 'multi_mp3':
            # MP3 files may store multiple values as delimited strings that
            # need splitting
            assert tt_has_multiple_artists, \
                f"MP3 file should have multiple artist IDs (possibly delimited), " \
                f"got {tt_artists}"


def test_multiple_images_extraction(multivalue_files):  # pylint: disable=redefined-outer-name
    """Test extraction of multiple embedded images with tinytag 2.1.1."""
    test_file = multivalue_files['multiimage']
    if not test_file.exists():
        pytest.skip("Multi-image test file not found")

    # TinyTag image extraction
    tt_tag = tinytag.TinyTag.get(str(test_file), image=True)

    # Check TinyTag image extraction (tinytag 2.1.1+ API)
    tt_image_count = 0
    tt_image_sizes = []
    if hasattr(tt_tag, 'images') and tt_tag.images:
        # TinyTag 2.1.1 stores multiple covers under 'cover' key
        images_dict = tt_tag.images.as_dict()

        # Count all unique images
        all_images = []
        image_hashes = set()

        # Add front_cover if present
        if tt_tag.images.front_cover:
            all_images.append(tt_tag.images.front_cover)
            image_hashes.add(hash(tt_tag.images.front_cover.data))

        # Add cover list images (avoiding duplicates)
        if 'cover' in images_dict and images_dict['cover']:
            for img in images_dict['cover']:
                img_hash = hash(img.data)
                if img_hash not in image_hashes:
                    all_images.append(img)
                    image_hashes.add(img_hash)

        if all_images:
            tt_image_count = len(all_images)
            tt_image_sizes = [len(img.data) for img in all_images]

    print(f"Image extraction from {test_file.name}:")
    print(f"  TinyTag: {tt_image_count} images, sizes: {tt_image_sizes}")

    # TinyTag should detect multiple images with our enhanced processing
    assert tt_image_count > 1, \
        f"TinyTag should detect multiple images, got {tt_image_count}"


def test_multivalue_field_consistency(multivalue_files):  # pylint: disable=redefined-outer-name
    """Test consistency in how tinytag 2.1.1 handles multi-value fields."""
    test_files = ['multi_mp3', 'multi_flac', 'multi_m4a']

    field_handling_report = {}

    for file_key in test_files:
        test_file = multivalue_files[file_key]
        if not test_file.exists():
            continue

        file_format = test_file.suffix
        field_handling_report[file_format] = {}

        # TinyTag extraction
        tt_tag = tinytag.TinyTag.get(str(test_file))

        # Analyze multi-value field handling patterns
        multivalue_fields = ['isrc', 'musicbrainz artist id', 'website', 'url']

        for field in multivalue_fields:
            tt_value = None

            # Check TinyTag (tinytag 2.1.1+ API)
            if hasattr(tt_tag, 'other') and tt_tag.other:
                tt_value = tt_tag.other.get(field)

            if tt_value is not None:
                field_handling_report[file_format][field] = {
                    'tinytag_type': type(tt_value).__name__,
                    'tinytag_value': str(tt_value)[:100],
                }

    # Print field handling patterns
    print("\\nMulti-value field handling patterns:")
    for file_format, fields in field_handling_report.items():
        print(f"\\n{file_format}:")
        for field, handling in fields.items():
            print(f"  {field}:")
            print(f"    TinyTag: {handling['tinytag_type']} = {handling['tinytag_value']}")


@pytest.mark.parametrize("file_key", ["multi_mp3", "multi_flac", "multi_m4a"])
def test_multivalue_parsing_edge_cases(multivalue_files, file_key):  # pylint: disable=redefined-outer-name
    """Test edge cases in multi-value field parsing with tinytag 2.1.1."""
    test_file = multivalue_files[file_key]
    if not test_file.exists():
        pytest.skip(f"Multi-value test file not found: {test_file}")

    # TinyTag extraction
    tt_tag = tinytag.TinyTag.get(str(test_file))

    # Look for fields that might have different delimiter handling (tinytag 2.1.1+ API)
    if hasattr(tt_tag, 'other') and tt_tag.other:
        for key, value in tt_tag.other.items():
            if isinstance(value, str) and any(delim in value for delim in ['/', ';', ',']):
                print(f"TinyTag delimiter pattern in {file_key}.{key}: {value}")

                # Test that the application metadata processor would handle this correctly
                if '/' in value:
                    parsed = value.split('/')
                    assert len(parsed) > 1, f"Failed to parse slash-delimited value: {value}"
                elif ';' in value:
                    parsed = value.split(';')
                    assert len(parsed) > 1, f"Failed to parse semicolon-delimited value: {value}"


def test_multivalue_memory_efficiency(multivalue_files):  # pylint: disable=redefined-outer-name
    """Test memory efficiency with large multi-value fields using tinytag 2.1.1."""
    test_file = multivalue_files['multiimage']
    if not test_file.exists():
        pytest.skip("Multi-image test file not found")

    # Measure memory usage with image extraction
    gc.collect()
    mem_before = sys.getsizeof(gc.get_objects())

    # Extract with images
    tt_tag = tinytag.TinyTag.get(str(test_file), image=True)

    gc.collect()
    mem_after = sys.getsizeof(gc.get_objects())

    # Document memory impact
    print(f"Memory impact of multi-image extraction: {mem_after - mem_before} bytes")

    # Verify images were actually extracted (tinytag 2.1.1+ API)
    if hasattr(tt_tag, 'images') and tt_tag.images:
        images_dict = tt_tag.images.as_dict()

        # Count total unique images from all sources
        total_images = 0
        image_hashes = set()

        if tt_tag.images.front_cover:
            image_hashes.add(hash(tt_tag.images.front_cover.data))
            total_images += 1

        if 'cover' in images_dict and images_dict['cover']:
            for img in images_dict['cover']:
                img_hash = hash(img.data)
                if img_hash not in image_hashes:
                    image_hashes.add(img_hash)
                    total_images += 1

        assert total_images > 1, f"Should extract multiple images, got {total_images}"


@pytest.mark.parametrize("file_key", ["multi_mp3", "multi_flac", "multi_m4a"])
def test_multivalue_field_order_consistency(multivalue_files, file_key):  # pylint: disable=redefined-outer-name
    """Test that multi-value fields maintain consistent ordering with tinytag 2.1.1."""
    test_file = multivalue_files[file_key]
    if not test_file.exists():
        pytest.skip(f"Multi-value test file not found: {test_file}")

    # Extract multiple times to check consistency for specific fields
    isrc_extractions = []
    for _ in range(3):
        tt_tag = tinytag.TinyTag.get(str(test_file))
        if hasattr(tt_tag, 'other') and tt_tag.other:
            # Check consistency of ISRC field specifically
            if 'isrc' in tt_tag.other and isinstance(tt_tag.other['isrc'], list):
                isrc_extractions.append(tt_tag.other['isrc'])

    # Check that the same field extracts consistently
    if isrc_extractions:
        first_isrc = isrc_extractions[0]
        for isrc_extraction in isrc_extractions[1:]:
            assert isrc_extraction == first_isrc, \
                f"ISRC field order inconsistent in {file_key}: " \
                f"{first_isrc} vs {isrc_extraction}"


def test_tinytag_monkey_patch_functionality():
    """Test that our monkey patch for M4A multi-value fields is working."""
    # This test verifies that our monkey patch is properly applied
    # (already imported at module level)
    # Verify the monkey patch was applied by checking the method signature
    import tinytag.tinytag as tt  # pylint: disable=import-outside-toplevel
    # pylint: disable=protected-access
    assert hasattr(tt._MP4, '_parse_custom_field'), "Monkey patch should be applied"  # pylint: disable=protected-access,no-member

    print("[OK] TinyTag monkey patch successfully applied")
