#!/usr/bin/env python3
"""One-time tufup repository setup.

Run this exactly once to bootstrap the production repo.  It generates keys for
every TUF role and creates the initial `root.json`, `targets.json`,
`snapshot.json`, and `timestamp.json` metadata files in REPO_DIR.

After running this, copy REPO_DIR/metadata/1.root.json into the WNP
source tree so it gets bundled with the application as the trust anchor.

USAGE:
    python tools/tufup_repo_init.py
"""

import logging

from tufup.repo import Repository

from nowplaying.upgrades import tufup_repo_settings as repo_settings


def main() -> None:
    """Initialize the tufup repository.  Idempotent: safe to re-run."""
    logging.basicConfig(level=logging.INFO)

    repo = Repository(
        app_name="WhatsNowPlaying",
        # tufup reads the app version from this importable attribute when
        # building bundles.  For the spike we point at WNP's existing
        # version module.
        app_version_attr="nowplaying.version.__VERSION__",
        repo_dir=repo_settings.REPO_DIR,
        keys_dir=repo_settings.KEYS_DIR,
        key_map=repo_settings.KEY_MAP,
        expiration_days=repo_settings.EXPIRATION_DAYS,
        encrypted_keys=repo_settings.ENCRYPTED_KEYS,
        thresholds=repo_settings.THRESHOLDS,
    )

    repo.save_config()
    repo.initialize()

    print(f"\nKeys written to:     {repo_settings.KEYS_DIR}")
    print(f"Metadata written to: {repo_settings.REPO_DIR / 'metadata'}")
    print(f"Targets dir:         {repo_settings.REPO_DIR / 'targets'}")
    print(
        "\nNext step: copy the initial root.json into the app bundle so"
        " WNP can use it as its trust anchor on first run."
    )


if __name__ == "__main__":
    main()
