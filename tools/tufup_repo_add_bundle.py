#!/usr/bin/env python3
"""Per-release tufup bundle script.

Takes a PyInstaller `dist/` directory containing the freshly built WNP app
for one platform, packages it as a tufup target, generates a binary patch
from the previous release if there is one, and signs the updated TUF
metadata (targets/snapshot/timestamp roles).

USAGE:
    python tools/tufup_repo_add_bundle.py path/to/dist <version> <platform>

Example:
    python tools/tufup_repo_add_bundle.py dist/ 5.2.1 mac

After running, REPO_DIR/{metadata,targets} is the publishable artifact set.
Upload its entire contents to whatever HTTPS endpoint TUFUP_METADATA_URL /
TUFUP_TARGET_URL point at on the client side.
"""

import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from tufup.repo import Repository  # noqa: E402

import tufup_repo_settings as repo_settings  # noqa: E402


def main(argv: list[str]) -> int:
    """Add one platform's release bundle to the repo and sign metadata."""
    logging.basicConfig(level=logging.INFO)

    if len(argv) != 4:
        print(__doc__)
        return 1

    dist_dir = pathlib.Path(argv[1]).resolve()
    version = argv[2]
    platform = argv[3]  # e.g. mac / win / linux

    if not dist_dir.is_dir():
        print(f"error: {dist_dir} is not a directory", file=sys.stderr)
        return 1

    # Encode the platform in the app_name slot of the target filename
    # (e.g. WhatsNowPlaying_macos_arm-5.2.1-preview1.tar.gz) rather than
    # using PEP 440's "+local" tag.  Reason: the "+" character triggers a
    # URL-encoding bug in tufup's download path, and underscores parse
    # cleanly through tufup's filename regex while staying inside what
    # plain HTTPS / CDNs treat as ASCII-safe.
    repo = Repository.from_config()
    repo.app_name = f"WhatsNowPlaying_{platform.replace('-', '_')}"
    repo.add_bundle(
        new_version=version,
        new_bundle_dir=dist_dir,
    )
    repo.publish_changes(private_key_dirs=[repo_settings.KEYS_DIR])

    print(f"\nBundle published: version={version} platform={platform}")
    print(f"Publishable artifacts: {repo_settings.REPO_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
