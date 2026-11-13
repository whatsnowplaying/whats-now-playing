#!/usr/bin/env python3
"""Check a tufup archive against its entry in signed targets.json.

Used by .github/workflows/tufup-publish.yaml before reusing a tarball
already on a release, so re-publishing never signs bytes the existing
metadata didn't already vouch for.

Usage:
    tufup_verify_target.py path/to/targets.json path/to/archive.tar.gz

Exit status: 0 match, 1 mismatch, 2 no entry for this archive.
"""

import hashlib
import json
import pathlib
import sys

EXIT_MATCH = 0
EXIT_MISMATCH = 1
EXIT_NO_ENTRY = 2


def verify(targets_json: pathlib.Path, archive: pathlib.Path) -> int:
    """Compare archive length and sha256 with its targets.json entry."""
    targets = json.loads(targets_json.read_text())["signed"]["targets"]
    entry = targets.get(archive.name)
    if entry is None:
        print(f"no targets.json entry for {archive.name}")
        return EXIT_NO_ENTRY
    data = archive.read_bytes()
    expected_sha = entry.get("hashes", {}).get("sha256")
    actual_sha = hashlib.sha256(data).hexdigest()
    if entry.get("length") != len(data) or expected_sha != actual_sha:
        print(
            f"{archive.name} does not match targets.json: "
            f"length {len(data)} vs {entry.get('length')}, "
            f"sha256 {actual_sha} vs {expected_sha}",
            file=sys.stderr,
        )
        return EXIT_MISMATCH
    print(f"{archive.name} matches targets.json")
    return EXIT_MATCH


def main(argv: list[str] | None = None) -> int:
    """Parse args and verify."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return EXIT_MISMATCH
    return verify(pathlib.Path(args[0]), pathlib.Path(args[1]))


if __name__ == "__main__":
    sys.exit(main())
