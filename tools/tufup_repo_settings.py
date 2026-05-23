"""Shared configuration for the tufup release pipeline.

This file declares the TUF role layout, key storage, and expirations used by
both `tufup_repo_init.py` (one-time setup) and `tufup_repo_add_bundle.py`
(per-release).

Key material lives in ~/.wnp-tufup-prod/keystore/ (outside the source tree,
never checked in).  The production key name is wnp_prod_key.  Back it up in
Bitwarden alongside the passphrase.

All four TUF roles share one key with threshold 1.  See
docs/dev/tufup-release-tooling.md for the accepted-risk note on this.
"""

import pathlib

from tufup.repo import DEFAULT_KEY_MAP, DEFAULT_KEYS_DIR_NAME, DEFAULT_REPO_DIR_NAME

# All tufup repo state lives under this directory.  Outside the WNP source
# tree because it contains private keys and release artifacts that should
# never be checked in.
DEV_DIR: pathlib.Path = pathlib.Path.home() / ".wnp-tufup-prod"

# Local copies of repo state.  CI rsyncs these up to gh-pages (metadata)
# and GH Releases (targets) after each publish run.
KEYS_DIR: pathlib.Path = DEV_DIR / DEFAULT_KEYS_DIR_NAME
REPO_DIR: pathlib.Path = DEV_DIR / DEFAULT_REPO_DIR_NAME

KEY_NAME: str = "wnp_prod_key"
KEY_MAP: dict[str, list[str]] = {role: [KEY_NAME] for role in DEFAULT_KEY_MAP}

ENCRYPTED_KEYS: list[str] = []

THRESHOLDS: dict[str, int] = dict(root=1, targets=1, snapshot=1, timestamp=1)

EXPIRATION_DAYS: dict[str, int] = dict(root=365, targets=30, snapshot=7, timestamp=1)
