# Audio Metadata Testing Framework

This directory contains comprehensive integration tests for the audio metadata
extraction library used in the What's Now Playing application: `tinytag`.

## Overview

The testing framework is designed to:

1. **Document library capabilities** - Know exactly what each library can extract
2. **Detect upgrade changes** - Identify what breaks or gets added during
   library upgrades
3. **Ensure format compatibility** - Test across all supported audio formats
4. **Validate multi-value handling** - Test complex metadata scenarios
5. **Performance monitoring** - Track extraction performance over time

## Test Structure

### Core Test Modules

- **`test_library_feature_matrix.py`** - Maps what each library can extract
  from each format
- **`test_golden_master.py`** - Regression testing using golden master approach
- **`test_format_specific.py`** - Format-specific deep testing (MP3, FLAC, M4A, AIFF)
- **`test_multivalue_fields.py`** - Multi-value metadata field handling
- **`test_upgrade_detection.py`** - Automated upgrade change detection

### Supporting Infrastructure

- **`conftest.py`** - Enhanced pytest fixtures and test configuration
- **`golden_masters/`** - Stored baseline outputs for regression testing
- **`specifications/`** - Library version tracking and capability documentation

## Running Tests

### Run All Audio Metadata Tests

```bash
pytest tests/audio_metadata/ -v
```

### Run Specific Test Categories

```bash
# Library feature matrix tests
pytest tests/audio_metadata/test_library_feature_matrix.py -v

# Golden master regression tests  
pytest tests/audio_metadata/test_golden_master.py -v

# Format-specific tests
pytest tests/audio_metadata/test_format_specific.py -v

# Multi-value field tests
pytest tests/audio_metadata/test_multivalue_fields.py -v

# Upgrade detection tests
pytest tests/audio_metadata/test_upgrade_detection.py -v
```

### Run Tests by Marker

```bash
# Run only fast tests (exclude slow golden master tests)
pytest tests/audio_metadata/ -m "not slow" -v

# Run only format-specific tests
pytest tests/audio_metadata/ -m "format_specific" -v

# Run only library matrix tests
pytest tests/audio_metadata/ -m "library_matrix" -v
```

## Test Categories

### 1. Library Feature Matrix Tests

**Purpose**: Document exactly what metadata fields each library can extract
from each audio format.

**Key Tests**:

- `test_library_extraction_matrix` - Systematic extraction testing
- `test_format_support_matrix` - Which formats each library supports
- `test_metadata_field_coverage` - Which fields each library can extract
- `test_library_parity_check` - Compare outputs for equivalent fields

**Output**: Comprehensive matrices showing library capabilities.

### 2. Golden Master Tests

**Purpose**: Detect regressions and changes when libraries are upgraded.

**Key Tests**:

- `test_create_golden_masters` - Establish baseline outputs (run manually)
- `test_golden_master_regression` - Compare current vs. baseline outputs
- `test_library_upgrade_impact_analysis` - Analyze scope of changes

**Output**: Detailed diff reports showing exactly what changed after upgrades.

### 3. Format-Specific Deep Tests

**Purpose**: Test format-specific metadata extraction capabilities.

**Test Classes**:

- `TestMP3Metadata` - ID3 tags, LAME headers, version handling
- `TestFLACMetadata` - Vorbis comments, stream properties, encoding
- `TestM4AMetadata` - Freeform tags, codec detection
- `TestAIFFMetadata` - Basic metadata support, format detection

**Output**: Format-specific capability documentation and edge case handling.

### 4. Multi-Value Field Tests

**Purpose**: Test handling of metadata fields with multiple values.

**Key Tests**:

- `test_multiple_isrc_extraction` - Multiple ISRC codes
- `test_multiple_artists_extraction` - Multiple artist IDs
- `test_multiple_images_extraction` - Multiple embedded images
- `test_multivalue_field_consistency` - Consistent handling patterns

**Output**: Documentation of how libraries handle complex metadata scenarios.

### 5. Upgrade Detection Tests

**Purpose**: Automatically detect and document library upgrade changes.

**Key Tests**:

- `test_current_library_versions` - Document current state
- `test_detect_version_changes` - Compare with previous versions
- `test_new_feature_detection` - Identify new capabilities
- `test_extraction_capability_regression` - Test for capability regressions

**Output**: Automated change detection and feature evolution tracking.

## Test Data

The tests use audio files from `tests/audio/`:

### Basic Files (minimal metadata)

- `15_Ghosts_II_64kb_orig.{mp3,flac,m4a,aiff}`

### Complex Files (fully tagged)

- `15_Ghosts_II_64kb_füllytâgged.{mp3,flac,m4a,aiff}`

### Multi-Value Files

- `multi.{mp3,flac,m4a}`

### Special Cases

- `multiimage.m4a` - Multiple embedded images
- `*_fake_orig*.{mp3,m4a}` - Edge case date handling

## Usage Patterns

### Before Library Upgrades

1. **Establish baseline**:

   ```bash
   pytest tests/audio_metadata/test_upgrade_detection.py::\
     test_current_library_versions -v
   ```

2. **Create golden masters** (if needed):

   ```bash
   # Uncomment the skip in test_create_golden_masters and run:
   pytest tests/audio_metadata/test_golden_master.py::\
     test_create_golden_masters -v
   ```

### After Library Upgrades

1. **Check for regressions**:

   ```bash
   pytest tests/audio_metadata/test_golden_master.py::\
     test_golden_master_regression -v
   ```

2. **Detect changes**:

   ```bash
   pytest tests/audio_metadata/test_upgrade_detection.py::\
     test_detect_version_changes -v
   ```

3. **Validate capabilities**:

   ```bash
   pytest tests/audio_metadata/test_library_feature_matrix.py -v
   ```

### Regular Development

1. **Quick capability check**:

   ```bash
   pytest tests/audio_metadata/test_library_feature_matrix.py::\
     test_format_support_matrix -v
   ```

2. **Multi-value validation**:

   ```bash
   pytest tests/audio_metadata/test_multivalue_fields.py -v
   ```

## Expected Output Examples

### Format Support Matrix

```text
Format   | TinyTag | Audio_metadata
---------|---------|---------------
.mp3     |    ✓    |       ✓
.flac    |    ✓    |       ✓
.m4a     |    ✓    |       ✗
.aiff    |    ✓    |       ✗
```

### Field Coverage Analysis

```text
Field Coverage Analysis:
Common fields (15): ['album', 'artist', 'bitrate', 'duration', ...]
TinyTag only (25): ['filesize', 'samplerate', 'extra_*', ...]
Audio_metadata only (8): ['stream_*', 'tag_usertext', ...]
```

### Upgrade Change Detection

```text
Version Changes Detected:
tinytag: 1.8.1 -> 1.9.0 (upgraded)

Capability Changes Detected:
tinytag:
  Added extensions: ['.opus']
  Added available_attributes: ['get_parser_class']
```

## Integration with Existing Tests

This framework complements the existing `test_metadata.py` by:

- **Focusing on library-specific testing** vs. application integration testing
- **Providing upgrade safety** vs. functional correctness testing  
- **Documenting capabilities** vs. validating business logic
- **Performance tracking** vs. feature validation

## Maintenance

### Adding New Test Files

1. Add files to `tests/audio/`
2. Update `conftest.py` fixtures if needed
3. Run baseline establishment tests

### Adding New Libraries

1. Add extraction methods to helper classes
2. Update compatibility fixtures
3. Add library-specific test cases

### Updating Golden Masters

Golden masters should be updated when:

- Library upgrades introduce expected changes
- New test files are added
- Test extraction logic changes

```bash
# Update golden masters after validating changes
pytest tests/audio_metadata/test_golden_master.py::test_create_golden_masters -v
```

This testing framework ensures you always know exactly what audio metadata
extraction capabilities are available, what changes during upgrades, and what
features are gained or lost over time.
