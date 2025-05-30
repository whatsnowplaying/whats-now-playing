#!/usr/bin/env python3
"""
Comprehensive metadata analysis script comparing tinytag and audio_metadata libraries.

This script analyzes audio files in a directory using both tinytag and audio_metadata
libraries, compares their capabilities, and generates a detailed report.

Usage:
    python analyze_audio_metadata.py                           # Use default paths
    python analyze_audio_metadata.py --audio-dir /path/to/audio
    python analyze_audio_metadata.py --output-file /path/to/results.json
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add the nowplaying package to the path (relative to this script)
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

try:
    from tinytag import TinyTag
    print("✓ Successfully imported TinyTag from vendor")
except ImportError as import_error:
    print(f"✗ Failed to import TinyTag from vendor: {import_error}")
    try:
        from tinytag import TinyTag
        print("✓ Successfully imported TinyTag from system")
    except ImportError as import_error2:
        print(f"✗ Failed to import TinyTag from system: {import_error2}")
        sys.exit(1)

try:
    import audio_metadata
    print("✓ Successfully imported audio_metadata")
except ImportError as import_error:
    print(f"✗ Failed to import audio_metadata: {import_error}")
    print("Installing audio_metadata...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "audio-metadata"])
    import audio_metadata
    print("✓ Successfully installed and imported audio_metadata")


def clean_metadata_for_json(obj):
    """Clean metadata object for JSON serialization."""
    if hasattr(obj, '__dict__'):
        return {
            k: clean_metadata_for_json(v)
            for k, v in obj.__dict__.items() if not k.startswith('_')
        }
    if isinstance(obj, (list, tuple)):
        return [clean_metadata_for_json(item) for item in obj]
    if isinstance(obj, dict):
        return {k: clean_metadata_for_json(v) for k, v in obj.items()}
    if hasattr(obj, 'decode'):  # bytes-like object
        try:
            return obj.decode('utf-8', errors='replace')
        except (UnicodeDecodeError, AttributeError):
            return f"<bytes: {len(obj)} bytes>"
    return obj


def extract_tinytag_metadata(file_path: str) -> dict[str, Any]:
    """Extract metadata using TinyTag."""
    try:
        tag = TinyTag.get(file_path, image=True)

        # Get all available attributes
        metadata = {}
        for attr in dir(tag):
            if not attr.startswith('_') and not callable(getattr(tag, attr)):
                value = getattr(tag, attr)
                if value is not None:
                    metadata[attr] = value

        # Handle artwork specially
        if hasattr(tag, 'get_image') and tag.get_image():
            artwork = tag.get_image()
            metadata['artwork_info'] = {
                'size': len(artwork) if artwork else 0,
                'type': type(artwork).__name__
            }

        return metadata
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return {'error': str(exc)}


def extract_audio_metadata_metadata(file_path: str) -> dict[str, Any]:
    """Extract metadata using audio_metadata."""
    try:
        metadata_obj = audio_metadata.load(file_path)  # pylint: disable=no-member

        # Convert to dictionary and clean for JSON serialization
        metadata = clean_metadata_for_json(metadata_obj)

        # Add some summary info
        if hasattr(metadata_obj, 'pictures') and metadata_obj.pictures:
            metadata['pictures_info'] = {
                'count':
                len(metadata_obj.pictures),
                'types':
                [pic.type for pic in metadata_obj.pictures] if metadata_obj.pictures else [],
                'sizes': [len(pic.data) if pic.data else 0
                          for pic in metadata_obj.pictures] if metadata_obj.pictures else []
            }

        return metadata
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return {'error': str(exc)}


def analyze_file(file_path: str) -> dict[str, Any]:
    """Analyze a single audio file with both libraries."""
    print(f"Analyzing: {os.path.basename(file_path)}")

    result = {
        'file': os.path.basename(file_path),
        'file_size': os.path.getsize(file_path),
        'tinytag': extract_tinytag_metadata(file_path),
        'audio_metadata': extract_audio_metadata_metadata(file_path)
    }

    return result


def compare_metadata(tinytag_data: dict, audio_metadata_data: dict) -> dict[str, Any]:
    """Compare metadata between the two libraries."""
    comparison = {
        'common_fields': [],
        'tinytag_only': [],
        'audio_metadata_only': [],
        'value_differences': []
    }

    # Skip error cases
    if 'error' in tinytag_data or 'error' in audio_metadata_data:
        return comparison

    # Get field names (excluding special info fields)
    tinytag_fields = set(k for k in tinytag_data.keys() if not k.endswith('_info'))
    audio_metadata_fields = set(k for k in audio_metadata_data.keys() if not k.endswith('_info'))

    # Map some common field name variations
    field_mappings = {
        'albumartist': 'album_artist',
        'track': 'track_number',
        'disc': 'disc_number',
        'year': 'date',
    }

    # Find common fields (accounting for field name variations)
    for tt_field in tinytag_fields:
        mapped_field = field_mappings.get(tt_field, tt_field)
        if mapped_field in audio_metadata_fields or tt_field in audio_metadata_fields:
            comparison['common_fields'].append(tt_field)

    # Find library-specific fields
    mapped_audio_fields = {field_mappings.get(f, f) for f in audio_metadata_fields}

    for field in tinytag_fields:
        if field not in mapped_audio_fields and field_mappings.get(
                field, field) not in audio_metadata_fields:
            comparison['tinytag_only'].append(field)

    for field in audio_metadata_fields:
        reverse_mapping = {v: k for k, v in field_mappings.items()}
        mapped_field = reverse_mapping.get(field, field)
        if field not in tinytag_fields and mapped_field not in tinytag_fields:
            comparison['audio_metadata_only'].append(field)

    return comparison


def main():
    """Main analysis function."""
    parser = argparse.ArgumentParser(
        description='Analyze audio metadata using tinytag and audio_metadata libraries'
    )
    parser.add_argument(
        '--audio-dir',
        type=Path,
        default=None,
        help='Directory containing audio files to analyze (default: ./tests/audio)'
    )
    parser.add_argument(
        '--output-file',
        type=Path,
        default=None,
        help='Output JSON file path (default: ./metadata_analysis_results.json)'
    )

    args = parser.parse_args()

    # Use command line arguments or defaults based on script location
    base_dir = Path(__file__).parent
    audio_dir = args.audio_dir or (base_dir / 'tests' / 'audio')
    output_file = args.output_file or (base_dir / 'metadata_analysis_results.json')

    # Validate audio directory exists
    if not audio_dir.exists():
        print(f"Error: Audio directory does not exist: {audio_dir}")
        print("Please specify a valid directory with --audio-dir")
        sys.exit(1)

    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Get all audio files (excluding JSON)
    audio_files = [
        f for f in audio_dir.glob('*') if f.suffix.lower() in ['.mp3', '.m4a', '.flac', '.aiff']
    ]
    audio_files.sort()

    results = []

    print(f"Found {len(audio_files)} audio files to analyze\n")

    for file_path in audio_files:
        result = analyze_file(str(file_path))
        results.append(result)

        # Add comparison analysis
        result['comparison'] = compare_metadata(result['tinytag'], result['audio_metadata'])

        tinytag_field_count = len([k for k in result['tinytag'] if not k.endswith('_info')])
        audio_metadata_field_count = len([k for k in result['audio_metadata']
                                         if not k.endswith('_info')])
        print(f"  - TinyTag fields: {tinytag_field_count}")
        print(f"  - audio_metadata fields: {audio_metadata_field_count}")
        if 'error' in result['tinytag']:
            print(f"  - TinyTag error: {result['tinytag']['error']}")
        if 'error' in result['audio_metadata']:
            print(f"  - audio_metadata error: {result['audio_metadata']['error']}")
        print()

    # Save detailed results to JSON
    with open(output_file, 'w', encoding='utf-8') as json_file:
        json.dump(results, json_file, indent=2, default=str, ensure_ascii=False)

    print(f"Detailed results saved to: {output_file}")

    # Generate summary report
    generate_summary_report(results)


def _print_format_analysis(results: list[dict]) -> None:
    """Print format-specific analysis."""
    formats = {}
    for result in results:
        ext = result['file'].split('.')[-1].lower()
        if ext not in formats:
            formats[ext] = {'tinytag': 0, 'audio_metadata': 0, 'total': 0}
        formats[ext]['total'] += 1
        if 'error' not in result['tinytag']:
            formats[ext]['tinytag'] += 1
        if 'error' not in result['audio_metadata']:
            formats[ext]['audio_metadata'] += 1

    print("\nFORMAT SUPPORT:")
    for fmt, stats in formats.items():
        print(f"  {fmt.upper()}: TinyTag {stats['tinytag']}/{stats['total']}, "
              f"audio_metadata {stats['audio_metadata']}/{stats['total']}")


def _print_detailed_analysis(results: list[dict]) -> None:
    """Print detailed file analysis."""
    print("\nDETAILED FILE ANALYSIS:")
    print("-" * 80)

    for result in results:
        print(f"\nFile: {result['file']}")
        print(f"Size: {result['file_size']:,} bytes")

        if 'error' in result['tinytag']:
            print(f"TinyTag: ERROR - {result['tinytag']['error']}")
        else:
            tt_fields = [k for k in result['tinytag'] if not k.endswith('_info')]
            print(f"TinyTag: {len(tt_fields)} fields")
            if tt_fields:
                print(f"  Fields: {', '.join(sorted(tt_fields))}")

        if 'error' in result['audio_metadata']:
            print(f"audio_metadata: ERROR - {result['audio_metadata']['error']}")
        else:
            am_fields = [k for k in result['audio_metadata'] if not k.endswith('_info')]
            print(f"audio_metadata: {len(am_fields)} fields")
            if am_fields:
                print(f"  Fields: {', '.join(sorted(am_fields))}")

        # Show comparison if both succeeded
        if 'error' not in result['tinytag'] and 'error' not in result['audio_metadata']:
            comp = result['comparison']
            if comp['common_fields']:
                print(f"  Common fields: {', '.join(sorted(comp['common_fields']))}")
            if comp['tinytag_only']:
                print(f"  TinyTag only: {', '.join(sorted(comp['tinytag_only']))}")
            if comp['audio_metadata_only']:
                print(f"  audio_metadata only: {', '.join(sorted(comp['audio_metadata_only']))}")


def _print_sample_metadata(results: list[dict]) -> None:
    """Print sample metadata extraction."""
    print("\nSAMPLE METADATA EXTRACTION:")
    print("-" * 80)

    key_files = [
        '15_Ghosts_II_64kb_orig.mp3', '15_Ghosts_II_64kb_füllytâgged.mp3', 'multi.mp3',
        'multiimage.m4a'
    ]

    for filename in key_files:
        result = next((r for r in results if r['file'] == filename), None)
        if result and 'error' not in result['tinytag']:
            print(f"\n{filename} (TinyTag sample):")
            for key, value in sorted(result['tinytag'].items()):
                if not key.endswith('_info') and value is not None:
                    if isinstance(value, str) and len(value) > 50:
                        value = value[:47] + "..."
                    print(f"  {key}: {value}")


def generate_summary_report(results: list[dict]) -> None:
    """Generate a human-readable summary report."""
    print("\n" + "=" * 80)
    print("METADATA EXTRACTION COMPARISON REPORT")
    print("=" * 80)

    # Overall statistics
    successful_tinytag = sum(1 for r in results if 'error' not in r['tinytag'])
    successful_audio_metadata = sum(1 for r in results if 'error' not in r['audio_metadata'])

    print("\nOVERALL STATISTICS:")
    print(f"Total files analyzed: {len(results)}")
    print(f"TinyTag successful: {successful_tinytag}/{len(results)}")
    print(f"audio_metadata successful: {successful_audio_metadata}/{len(results)}")

    _print_format_analysis(results)
    _print_detailed_analysis(results)
    _print_sample_metadata(results)


if __name__ == '__main__':
    main()
