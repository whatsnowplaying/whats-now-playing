"""Shared configuration for the tufup release pipeline.

This file declares the TUF role layout, key storage, and expirations used by
both `repo_init.py` (one-time setup) and `repo_add_bundle.py` (per-release).

For the spike we use a single key for all four roles, unencrypted, stored
locally.  That's the simplest viable setup and matches the tufup-example
disclaimer: not safe for production releases.  A production setup would
use separate keys per role (especially `root`), encrypt them, and keep the
root key offline / on a hardware token.
"""

import pathlib

from tufup.repo import DEFAULT_KEY_MAP, DEFAULT_KEYS_DIR_NAME, DEFAULT_REPO_DIR_NAME

# All tufup repo state lives under this directory.  Outside the WNP source
# tree because it contains private keys and release artifacts that should
# never be checked in.
DEV_DIR: pathlib.Path = pathlib.Path.home() / ".wnp-tufup-spike"

# Where PyInstaller output lands for each platform.  Per-release scripts
# point at the matching platform's dist/ directory.
DIST_DIR: pathlib.Path = DEV_DIR / "dist"

# Local copies of repo state.  In production these would live on a release
# machine and be rsync'd up to the public CDN/host that serves them.
KEYS_DIR: pathlib.Path = DEV_DIR / DEFAULT_KEYS_DIR_NAME
REPO_DIR: pathlib.Path = DEV_DIR / DEFAULT_REPO_DIR_NAME

# Single key for all roles in the spike.  Production: per-role keys.
KEY_NAME: str = "wnp_spike_key"
KEY_MAP: dict[str, list[str]] = {role: [KEY_NAME] for role in DEFAULT_KEY_MAP}

# Which roles use passphrase-encrypted private keys.  Empty for the spike.
ENCRYPTED_KEYS: list[str] = []

# Signature thresholds (how many distinct keys must sign each role's metadata).
# Single-key setup → all thresholds = 1.
THRESHOLDS: dict[str, int] = dict(root=1, targets=1, snapshot=1, timestamp=1)

# Metadata expiration windows.  Shorter expirations on snapshot/timestamp
# limit the rollback window an attacker has if a non-root key is stolen.
# Root expires last because re-signing it requires manual ceremony.
EXPIRATION_DAYS: dict[str, int] = dict(root=365, targets=30, snapshot=7, timestamp=1)
