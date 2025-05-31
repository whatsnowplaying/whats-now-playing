#!/usr/bin/env python3
"""Test tinytag functionality for audio metadata extraction."""

from pathlib import Path

import pytest

import tinytag


@pytest.fixture
def test_files(getroot) -> dict[str, list[str]]:
    """Get organized test files by category."""
    audio_dir = Path(getroot) / 'tests' / 'audio'
    return {
        'basic': [
            audio_dir / '15_Ghosts_II_64kb_orig.mp3', audio_dir / '15_Ghosts_II_64kb_orig.flac',
            audio_dir / '15_Ghosts_II_64kb_orig.m4a', audio_dir / '15_Ghosts_II_64kb_orig.aiff'
        ],
        'complex': [
            audio_dir / '15_Ghosts_II_64kb_füllytâgged.mp3',
            audio_dir / '15_Ghosts_II_64kb_füllytâgged.flac',
            audio_dir / '15_Ghosts_II_64kb_füllytâgged.m4a',
            audio_dir / '15_Ghosts_II_64kb_füllytâgged.aiff'
        ],
        'multi_value': [audio_dir / 'multi.mp3', audio_dir / 'multi.flac', audio_dir / 'multi.m4a'],
        'multi_image': [audio_dir / 'multiimage.m4a'],
        'discsubtitle': [
            audio_dir / 'discsubtitle.mp3', audio_dir / 'discsubtitle.flac',
            audio_dir / 'discsubtitle.m4a'
        ]
    }


def _extract_basic_attributes(tag, results: dict) -> None:
    """Extract basic attributes from tinytag."""
    basic_attrs = [
        'album', 'albumartist', 'artist', 'bitrate', 'bpm', 'comment', 'disc', 'disc_total',
        'duration', 'filesize', 'genre', 'samplerate', 'title', 'track', 'track_total', 'year'
    ]

    for attr in basic_attrs:
        if hasattr(tag, attr):
            value = getattr(tag, attr)
            if value is not None:
                results[attr] = value


def _extract_other_fields(tag, results: dict) -> None:
    """Extract other/extra fields from tinytag."""
    if hasattr(tag, 'other') and tag.other:
        for key, value in tag.other.items():
            if value is not None:
                results[f'other_{key}'] = value


def _extract_image_info(tag, results: dict) -> None:
    """Extract image information from tinytag."""
    if not (hasattr(tag, 'images') and tag.images):
        return

    all_images = []
    image_hashes = set()

    # Add front_cover if present
    if tag.images.front_cover:
        all_images.append(tag.images.front_cover)
        image_hashes.add(hash(tag.images.front_cover.data))

    # Add cover list images (avoiding duplicates)
    images_dict = tag.images.as_dict()
    if 'cover' in images_dict and images_dict['cover']:
        for img in images_dict['cover']:
            img_hash = hash(img.data)
            if img_hash not in image_hashes:
                all_images.append(img)
                image_hashes.add(img_hash)

    if all_images:
        results['image_count'] = len(all_images)
        results['image_sizes'] = [len(img.data) for img in all_images]


def extract_tinytag_metadata(filepath: str) -> dict[str, any]:
    """Extract metadata using tinytag."""
    results = {}
    try:
        tag = tinytag.TinyTag.get(filepath, image=True)
        _extract_basic_attributes(tag, results)
        _extract_other_fields(tag, results)
        _extract_image_info(tag, results)
    except (FileNotFoundError, tinytag.TinyTagException) as exc:
        results['error'] = str(exc)
    return results


@pytest.mark.parametrize("file_category", ["basic", "complex", "multi_value", "multi_image"])
def test_tinytag_extraction_matrix(test_files, file_category):  # pylint: disable=redefined-outer-name
    """Test what tinytag can extract from each file category."""

    for test_file in test_files[file_category]:
        if not test_file.exists():
            pytest.skip(f"Test file not found: {test_file}")

        result = extract_tinytag_metadata(str(test_file))

        # Handle known limitations and errors
        if 'error' in result:
            pytest.fail(f"TinyTag failed to process {test_file.name}: {result['error']}")

        # Check if tinytag extracted meaningful metadata
        basic_fields = ['artist', 'title', 'album']
        extracted_basic = [field for field in basic_fields if field in result]

        assert len(extracted_basic) > 0, \
            f"TinyTag extracted no basic metadata from {test_file.name}"


def test_discsubtitle_extraction(test_files):  # pylint: disable=redefined-outer-name
    """Test discsubtitle extraction from tinytag."""
    discsubtitle_files = test_files.get('discsubtitle', [])

    for test_file in discsubtitle_files:
        if not test_file.exists():
            pytest.skip(f"Discsubtitle test file not found: {test_file}")

        print(f"\nTesting discsubtitle in {test_file.name}:")

        # TinyTag extraction
        tt_result = extract_tinytag_metadata(str(test_file))
        tt_discsubtitle = None

        # Look for discsubtitle in TinyTag other fields
        for key, value in tt_result.items():
            if 'subtitle' in key.lower() and 'other_' in key:
                tt_discsubtitle = value
                print(f"  TinyTag found: {key} = {value}")
                break

        # TinyTag should find discsubtitle
        assert tt_discsubtitle is not None, \
            f"TinyTag did not find discsubtitle in {test_file.name}"


def test_format_support_matrix(test_files):  # pylint: disable=redefined-outer-name
    """Test which formats tinytag supports."""
    support_matrix = {}

    all_files = []
    for category_files in test_files.values():
        all_files.extend(category_files)

    for test_file in set(all_files):  # Remove duplicates
        if not test_file.exists():
            continue

        file_format = test_file.suffix

        # Test tinytag
        tt_result = extract_tinytag_metadata(str(test_file))
        support_matrix[file_format] = 'error' not in tt_result

    # Print support matrix for documentation
    print("\nTinyTag Format Support Matrix:")
    print("Format   | TinyTag")
    print("---------|--------")
    for fmt in sorted(support_matrix):
        tt_support = "[OK]" if support_matrix[fmt] else "[FAIL]"
        print(f"{fmt:8} |    {tt_support}")


def test_metadata_field_coverage(test_files):  # pylint: disable=redefined-outer-name
    """Test which metadata fields tinytag can extract."""
    field_coverage = set()

    # Test on fully tagged files for maximum coverage
    for test_file in test_files['complex']:
        if not test_file.exists():
            continue

        # TinyTag fields
        tt_result = extract_tinytag_metadata(str(test_file))
        if 'error' not in tt_result:
            field_coverage.update(tt_result.keys())

    print(f"\nTinyTag Field Coverage: {len(field_coverage)} fields")
    print(f"Fields: {sorted(field_coverage)}")

    # Ensure tinytag extracts some metadata
    assert len(field_coverage) > 0, "TinyTag extracted no fields"


@pytest.mark.parametrize("test_file_name", [
    "15_Ghosts_II_64kb_füllytâgged.mp3", "15_Ghosts_II_64kb_füllytâgged.flac",
    "15_Ghosts_II_64kb_füllytâgged.m4a"
])
def test_complex_metadata_extraction(getroot, test_file_name):
    """Test tinytag extraction from fully tagged files."""
    test_file = Path(getroot) / 'tests' / 'audio' / test_file_name
    if not test_file.exists():
        pytest.skip(f"Test file not found: {test_file}")

    result = extract_tinytag_metadata(str(test_file))

    if 'error' in result:
        pytest.fail(f"TinyTag failed to process {test_file_name}: {result['error']}")

    # Should extract basic metadata
    assert 'artist' in result, f"Missing artist in {test_file_name}"
    assert 'title' in result, f"Missing title in {test_file_name}"
    assert 'album' in result, f"Missing album in {test_file_name}"

    # Should extract additional fields from complex files
    other_fields = [key for key in result if key.startswith('other_')]
    assert len(other_fields) > 0, f"No additional metadata fields found in {test_file_name}"


def test_unsupported_format_handling(tmp_path):
    """Test how tinytag handles unsupported formats."""
    # Create a fake audio file
    fake_file = tmp_path / "fake.xyz"
    fake_file.write_bytes(b"fake audio data")

    # TinyTag should handle unsupported formats gracefully
    with pytest.raises(tinytag.TinyTagException):
        tinytag.TinyTag.get(str(fake_file))


def test_corrupted_file_handling(tmp_path):
    """Test handling of corrupted audio files."""
    # Create files with audio extensions but invalid content
    corrupt_test_files = [(tmp_path / "corrupt.mp3", b"not mp3 data"),
                          (tmp_path / "corrupt.flac", b"not flac data"),
                          (tmp_path / "corrupt.m4a", b"not m4a data")]

    for corrupt_file, content in corrupt_test_files:
        corrupt_file.write_bytes(content)

        # TinyTag should handle corruption gracefully
        try:
            tag = tinytag.TinyTag.get(str(corrupt_file))
            # If it doesn't raise an exception, check what it extracted
            assert tag is not None
        except tinytag.TinyTagException:
            # Expected for corrupted files
            pass


@pytest.mark.parametrize("file_type", ["basic", "complex", "multi"])
def test_mp3_id3_tag_extraction(test_files, file_type):  # pylint: disable=redefined-outer-name
    """Test ID3 tag extraction from MP3 files."""
    mp3_files = [f for f in test_files.get(file_type, []) if str(f).endswith('.mp3')]

    for mp3_file in mp3_files:
        if not mp3_file.exists():
            pytest.skip(f"MP3 test file not found: {mp3_file}")

        # TinyTag extraction
        tag = tinytag.TinyTag.get(str(mp3_file))

        # Should extract basic ID3 fields from complex files
        if file_type == 'complex':
            assert tag.artist == 'Nine Inch Nails'
            assert tag.title == '15 Ghosts II'
            assert tag.album == 'Ghosts I-IV'

        # All files should have basic metadata
        assert tag.artist is not None, f"TinyTag should extract artist from {file_type}"
        assert tag.title is not None, f"TinyTag should extract title from {file_type}"


@pytest.mark.parametrize("file_type", ["basic", "complex", "multi"])
def test_mp3_stream_info_extraction(test_files, file_type):  # pylint: disable=redefined-outer-name
    """Test MP3 stream information extraction."""
    mp3_files = [f for f in test_files.get(file_type, []) if str(f).endswith('.mp3')]

    for mp3_file in mp3_files:
        if not mp3_file.exists():
            pytest.skip(f"MP3 test file not found: {mp3_file}")

        # TinyTag stream info
        tag = tinytag.TinyTag.get(str(mp3_file))

        # Check that TinyTag extracts bitrate and duration
        assert tag.bitrate is not None, f"TinyTag didn't extract bitrate from {file_type}"
        assert tag.duration is not None, f"TinyTag didn't extract duration from {file_type}"
        assert tag.samplerate is not None, f"TinyTag didn't extract samplerate from {file_type}"


def test_flac_vorbis_comments(test_files):  # pylint: disable=redefined-outer-name
    """Test FLAC Vorbis comment extraction."""
    flac_files = []
    for category_files in test_files.values():
        flac_files.extend([f for f in category_files if str(f).endswith('.flac')])

    for flac_file in flac_files:
        if not flac_file.exists():
            pytest.skip(f"FLAC test file not found: {flac_file}")

        # TinyTag extraction
        tag = tinytag.TinyTag.get(str(flac_file))

        # Should extract basic metadata
        assert tag.artist is not None, f"TinyTag didn't extract artist from {flac_file.name}"
        assert tag.title is not None, f"TinyTag didn't extract title from {flac_file.name}"


def test_flac_encoding_detection(test_files):  # pylint: disable=redefined-outer-name
    """Test FLAC encoder detection."""
    flac_files = []
    for category_files in test_files.values():
        flac_files.extend([f for f in category_files if str(f).endswith('.flac')])

    for flac_file in flac_files:
        if not flac_file.exists():
            continue

        # Check for encoder information
        tag = tinytag.TinyTag.get(str(flac_file))

        # TinyTag might have encoder in other (tinytag 2.1.1+ API)
        if hasattr(tag, 'other') and tag.other:
            encoder_info = tag.other.get('encoder')
            if encoder_info:
                print(f"TinyTag encoder info for {flac_file.name}: {encoder_info}")


def test_m4a_freeform_tags(test_files):  # pylint: disable=redefined-outer-name
    """Test M4A freeform tag handling."""
    m4a_files = []
    for category_files in test_files.values():
        m4a_files.extend([f for f in category_files if str(f).endswith('.m4a')])

    for m4a_file in m4a_files:
        if not m4a_file.exists():
            continue

        # TinyTag should extract freeform tags
        tag = tinytag.TinyTag.get(str(m4a_file))

        # Check for MusicBrainz IDs in freeform tags (tinytag 2.1.1+ API)
        if hasattr(tag, 'other') and tag.other:
            musicbrainz_fields = [key for key in tag.other.keys()
                                if 'musicbrainz' in key.lower()]

            if musicbrainz_fields:
                print(f"TinyTag MusicBrainz freeform tags in {m4a_file.name}: "
                      f"{musicbrainz_fields}")


def test_aiff_metadata_support(test_files):  # pylint: disable=redefined-outer-name
    """Test AIFF metadata extraction support."""
    aiff_files = []
    for category_files in test_files.values():
        aiff_files.extend([f for f in category_files if str(f).endswith('.aiff')])

    for aiff_file in aiff_files:
        if not aiff_file.exists():
            pytest.skip(f"AIFF test file not found: {aiff_file}")

        # TinyTag should support AIFF
        tag = tinytag.TinyTag.get(str(aiff_file))
        assert tag.artist is not None, f"TinyTag didn't extract artist from AIFF {aiff_file.name}"
        assert tag.title is not None, f"TinyTag didn't extract title from AIFF {aiff_file.name}"


def test_aiff_format_detection(test_files):  # pylint: disable=redefined-outer-name
    """Test AIFF format detection and properties."""
    aiff_files = []
    for category_files in test_files.values():
        aiff_files.extend([f for f in category_files if str(f).endswith('.aiff')])

    for aiff_file in aiff_files:
        if not aiff_file.exists():
            continue

        # TinyTag should provide basic stream info for AIFF
        tag = tinytag.TinyTag.get(str(aiff_file))

        assert tag.duration is not None, f"TinyTag missing duration for AIFF {aiff_file.name}"
        assert tag.samplerate is not None, f"TinyTag missing samplerate for AIFF {aiff_file.name}"
