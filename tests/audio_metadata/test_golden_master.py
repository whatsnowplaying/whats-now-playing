#!/usr/bin/env python3
"""Golden master tests to detect library upgrade changes."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
import tinytag


class GoldenMasterManager:
    """Manages golden master files for regression testing."""

    def __init__(self, golden_dir: Path):
        self.golden_dir = golden_dir
        self.golden_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_for_json(self, data: Any) -> Any:
        """Sanitize data for JSON serialization."""
        if isinstance(data, dict):
            return {k: self._sanitize_for_json(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._sanitize_for_json(item) for item in data]
        if isinstance(data, (str, int, float, bool)) or data is None:
            return data
        # Convert complex objects to string representation
        return str(data)

    def save_golden_master(self, library: str, test_file: str, data: dict[str, Any]):
        """Save golden master data for a library and test file."""
        sanitized_data = self._sanitize_for_json(data)

        golden_file = self.golden_dir / f"{library}_{Path(test_file).stem}.json"

        with open(golden_file, "w", encoding="utf-8") as json_file:
            json.dump(sanitized_data, json_file, indent=2, sort_keys=True)

    def load_golden_master(self, library: str, test_file: str) -> dict[str, Any] | None:
        """Load golden master data for a library and test file."""
        golden_file = self.golden_dir / f"{library}_{Path(test_file).stem}.json"

        if not golden_file.exists():
            return None

        with open(golden_file, "r", encoding="utf-8") as json_file:
            return json.load(json_file)

    def compare_with_golden_master(
        self, library: str, test_file: str, current_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Compare current data with golden master and return differences."""
        golden_data = self.load_golden_master(library, test_file)

        if golden_data is None:
            return {"status": "no_golden_master", "current_data": current_data}

        sanitized_current = self._sanitize_for_json(current_data)

        differences = self._find_differences(golden_data, sanitized_current)

        return {
            "status": "match" if not differences else "differences_found",
            "differences": differences,
            "golden_data": golden_data,
            "current_data": sanitized_current,
        }

    def _find_differences(self, golden: Any, current: Any, path: str = "") -> dict[str, Any]:
        """Find differences between golden and current data."""
        differences = {}

        # Handle different types
        if not isinstance(current, type(golden)):
            differences[f"{path}_type_change"] = {
                "golden_type": type(golden).__name__,
                "current_type": type(current).__name__,
                "golden_value": golden,
                "current_value": current,
            }
            return differences

        if isinstance(golden, dict):
            # Check for added/removed keys
            golden_keys = set(golden.keys())
            current_keys = set(current.keys())

            added_keys = current_keys - golden_keys
            removed_keys = golden_keys - current_keys

            if added_keys:
                differences[f"{path}_added_keys"] = list(added_keys)
            if removed_keys:
                differences[f"{path}_removed_keys"] = list(removed_keys)

            # Check common keys for value changes
            for key in golden_keys & current_keys:
                sub_path = f"{path}.{key}" if path else key
                sub_diffs = self._find_differences(golden[key], current[key], sub_path)
                differences.update(sub_diffs)

        elif isinstance(golden, list):
            if len(golden) != len(current):
                differences[f"{path}_length_change"] = {
                    "golden_length": len(golden),
                    "current_length": len(current),
                }

            # Compare list elements
            for i, (g_item, c_item) in enumerate(zip(golden, current)):
                sub_path = f"{path}[{i}]" if path else f"[{i}]"
                sub_diffs = self._find_differences(g_item, c_item, sub_path)
                differences.update(sub_diffs)

        else:
            # Direct value comparison
            if golden != current:
                differences[f"{path}_value_change"] = {
                    "golden_value": golden,
                    "current_value": current,
                }

        return differences


def extract_tinytag_data(filepath: str) -> dict[str, Any]:
    """Extract tinytag data in a stable format."""
    try:
        tag = tinytag.TinyTag.get(filepath, image=False)  # Skip images for stability

        result = {}

        # Basic fields
        basic_fields = [
            "album",
            "albumartist",
            "artist",
            "bitrate",
            "bpm",
            "comment",
            "disc",
            "disc_total",
            "duration",
            "genre",
            "samplerate",
            "title",
            "track",
            "track_total",
            "year",
        ]

        for field in basic_fields:
            if hasattr(tag, field):
                value = getattr(tag, field)
                if value is not None:
                    # Round floating point values for stability
                    if isinstance(value, float):
                        result[field] = round(value, 3)
                    else:
                        result[field] = value

        # Other fields (sorted for stability) - tinytag 2.1.1+ API
        if hasattr(tag, "other") and tag.other:
            result["other"] = dict(sorted(tag.other.items()))

        return result

    except (FileNotFoundError, tinytag.TinyTagException) as exc:
        return {"error": str(exc)}


def extract_audio_metadata_data(filepath: str) -> dict[str, Any]:  # pylint: disable=unused-argument
    """Placeholder for audio_metadata data extraction (no longer available)."""
    return {"error": "audio_metadata library not available"}


@pytest.fixture
def golden_manager() -> GoldenMasterManager:
    """Create golden master manager with test directory."""
    # In real use, you'd want this to be a permanent directory
    golden_dir = Path(__file__).parent / "golden_masters"
    return GoldenMasterManager(golden_dir)


@pytest.fixture
def stable_test_files(getroot) -> list[str]:
    """Get stable test files for golden master testing."""
    audio_dir = Path(getroot) / "tests" / "audio"
    return [
        str(audio_dir / "15_Ghosts_II_64kb_orig.mp3"),
        str(audio_dir / "15_Ghosts_II_64kb_orig.flac"),
        str(audio_dir / "15_Ghosts_II_64kb_füllytâgged.mp3"),
        str(audio_dir / "15_Ghosts_II_64kb_füllytâgged.flac"),
    ]


@pytest.mark.parametrize("library", ["tinytag"])
def test_create_golden_masters(golden_manager, stable_test_files, library):  # pylint: disable=redefined-outer-name
    """Create golden master files (run this once to establish baseline)."""
    # This test is typically skipped in normal runs
    pytest.skip("Golden master creation - only run manually when establishing baseline")

    for test_file in stable_test_files:
        if not os.path.exists(test_file):
            continue

        if library == "tinytag":
            data = extract_tinytag_data(test_file)
        else:
            data = extract_audio_metadata_data(test_file)

        golden_manager.save_golden_master(library, test_file, data)


@pytest.mark.parametrize("library", ["tinytag"])
def test_golden_master_regression(golden_manager, stable_test_files, library):  # pylint: disable=redefined-outer-name,too-many-branches
    """Test for regressions against golden master data."""
    for test_file in stable_test_files:
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")

        if library == "tinytag":
            current_data = extract_tinytag_data(test_file)
        else:
            current_data = extract_audio_metadata_data(test_file)

        # Skip if library can't process the file
        if "error" in current_data:
            if library == "audio_metadata" and test_file.endswith(".aiff"):
                pytest.skip(f"Known limitation: {library} doesn't support .aiff")
            else:
                pytest.fail(f"{library} failed to process {test_file}: {current_data['error']}")

        comparison = golden_manager.compare_with_golden_master(library, test_file, current_data)

        if comparison["status"] == "no_golden_master":
            pytest.skip(f"No golden master for {library} + {os.path.basename(test_file)}")

        elif comparison["status"] == "differences_found":
            differences = comparison["differences"]

            # Format difference report
            diff_report = []
            for key, diff in differences.items():
                if key.endswith("_added_keys"):
                    diff_report.append(f"Added keys: {diff}")
                elif key.endswith("_removed_keys"):
                    diff_report.append(f"Removed keys: {diff}")
                elif key.endswith("_value_change"):
                    diff_report.append(
                        f"Changed {key[:-13]}: {diff['golden_value']} -> {diff['current_value']}"
                    )
                elif key.endswith("_type_change"):
                    diff_report.append(
                        f"Type changed {key[:-12]}: {diff['golden_type']} -> {diff['current_type']}"
                    )

            pytest.fail(
                f"Golden master differences for {library} + {os.path.basename(test_file)}:\n"
                + "\n".join(diff_report)
            )


def test_library_upgrade_impact_analysis(golden_manager, stable_test_files):  # pylint: disable=redefined-outer-name
    """Analyze the impact of library upgrades across all files."""
    impact_report = {"tinytag": {}}

    for library in ["tinytag"]:
        total_files = 0
        files_with_differences = 0
        total_differences = 0

        for test_file in stable_test_files:
            if not os.path.exists(test_file):
                continue

            total_files += 1

            if library == "tinytag":
                current_data = extract_tinytag_data(test_file)
            else:
                current_data = extract_audio_metadata_data(test_file)

            if "error" in current_data:
                continue

            comparison = golden_manager.compare_with_golden_master(
                library, test_file, current_data
            )

            if comparison["status"] == "differences_found":
                files_with_differences += 1
                total_differences += len(comparison["differences"])

        impact_report[library] = {
            "total_files_tested": total_files,
            "files_with_differences": files_with_differences,
            "total_differences": total_differences,
            "stability_percentage": ((total_files - files_with_differences) / total_files * 100)
            if total_files > 0
            else 0,
        }

    print("\\nLibrary Upgrade Impact Analysis:")
    for library, stats in impact_report.items():
        print(f"{library}:")
        print(f"  Files tested: {stats['total_files_tested']}")
        print(f"  Files with changes: {stats['files_with_differences']}")
        print(f"  Total differences: {stats['total_differences']}")
        print(f"  Stability: {stats['stability_percentage']:.1f}%")

    # This test is informational - it documents changes but doesn't fail
    # You might want to add thresholds if needed
