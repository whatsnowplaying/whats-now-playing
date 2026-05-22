#!/usr/bin/env python3
"""Generate signed TUF metadata for one or more platform bundles in the
prod tufup repo.

Called by .github/workflows/tufup-publish.yaml at release time to
register each platform's signed PyInstaller output as a TUF target,
then sign + publish updated metadata.  Can also be run manually for
one-off re-signs.

Bypasses ``tufup targets add`` because that CLI assumes one channel
per repo (its ``get_latest_archive()`` doesn't filter by app_name;
adding a second channel at the same version trips the version check).
We use the lower-level roles API instead.  See
``feedback_tufup_multichannel`` for the full context.

Usage:
    tufup_publish.py \\
        --version 5.3.0 \\
        --keystore /tmp/keystore \\
        --repo-dir /tmp/tufup-repo \\
        --bundle WhatsNowPlaying_macos15_arm:/tmp/extracted/mac-arm \\
        --bundle WhatsNowPlaying_macos15_intel:/tmp/extracted/mac-intel \\
        --bundle WhatsNowPlaying_windows_x86_64:/tmp/extracted/win \\
        --bundle WhatsNowPlaying_linux_x86_64:/tmp/extracted/linux

Inputs:
    --repo-dir: must contain a metadata/ subdir seeded from the current
                gh-pages state.  The script writes new tar.gz files to
                repo-dir/targets/ and refreshed metadata to
                repo-dir/metadata/.
    --keystore: directory containing wnp_prod_key and wnp_prod_key.pub.
    --bundle:   repeat per channel.  The dir is the unpacked, signed
                application bundle (PyInstaller output, already
                notarized + stapled on macOS, Authenticode-signed on
                Windows).
"""

import argparse
import json
import os
import pathlib
import sys

from tufup.repo import Repository, make_gztar_archive


KEY_NAME = "wnp_prod_key"


def _parse_bundle(value: str) -> tuple[str, pathlib.Path]:
    """Parse a --bundle CHANNEL:DIR argument."""
    channel, _, bundle_dir = value.partition(":")
    if not channel or not bundle_dir:
        raise argparse.ArgumentTypeError(f'invalid --bundle (expected "CHANNEL:DIR"): {value!r}')
    path = pathlib.Path(bundle_dir)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"bundle dir does not exist: {path}")
    return channel, path


def _write_config(repo_dir: pathlib.Path, keys_dir: pathlib.Path) -> pathlib.Path:
    """Write a .tufup-repo-config in repo_dir's parent.

    Returns the directory the config is in (the script chdirs there
    before invoking tufup's config loader).
    """
    config_cwd = repo_dir.parent
    config_cwd.mkdir(parents=True, exist_ok=True)
    roles = ("root", "snapshot", "targets", "timestamp")
    config = {
        "app_name": "WhatsNowPlaying",
        "app_version_attr": "nowplaying.version.__VERSION__",
        "binary_diff": None,
        "encrypted_keys": [],
        "expiration_days": {
            "root": 365,
            "snapshot": 7,
            "targets": 30,
            "timestamp": 1,
        },
        "key_map": {role: [KEY_NAME] for role in roles},
        "keys_dir": str(keys_dir),
        "repo_dir": str(repo_dir),
        "thresholds": {role: 1 for role in roles},
    }
    config_path = config_cwd / ".tufup-repo-config"
    config_path.write_text(json.dumps(config, indent=4))
    return config_cwd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register platform bundles as tufup targets and re-sign metadata.",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Release version (PEP440), e.g. 5.3.0 or 5.3.0-preview1",
    )
    parser.add_argument(
        "--keystore",
        required=True,
        type=pathlib.Path,
        help="Directory containing private + public key files",
    )
    parser.add_argument(
        "--repo-dir",
        required=True,
        type=pathlib.Path,
        help="Tufup repo dir; must contain a metadata/ subdir seeded from gh-pages",
    )
    parser.add_argument(
        "--bundle",
        action="append",
        required=True,
        type=_parse_bundle,
        metavar="CHANNEL:DIR",
        help="Channel + bundle dir pair, e.g. "
        "WhatsNowPlaying_macos15_arm:/tmp/extracted/mac-arm. "
        "Repeat once per channel.",
    )
    args = parser.parse_args(argv)

    repo_dir: pathlib.Path = args.repo_dir.resolve()
    keystore: pathlib.Path = args.keystore.resolve()

    targets_dir = repo_dir / "targets"
    metadata_dir = repo_dir / "metadata"
    targets_dir.mkdir(parents=True, exist_ok=True)
    if not metadata_dir.is_dir():
        print(
            f"error: metadata_dir {metadata_dir} not found.  "
            "Seed it from gh-pages:tufup/metadata/ before running this script.",
            file=sys.stderr,
        )
        return 1

    # Repository.from_config() reads the config from CWD only, so write a
    # fresh config and chdir to its parent before instantiating.
    config_cwd = _write_config(repo_dir=repo_dir, keys_dir=keystore)
    os.chdir(config_cwd)

    repo = Repository.from_config()
    # from_config() always populates repo.roles; the Optional is for the
    # pre-initialize state we don't hit here.
    assert repo.roles is not None
    for channel, bundle_dir in args.bundle:
        archive_filename = f"{channel}-{args.version}.tar.gz"
        archive_path = targets_dir / archive_filename
        if archive_path.exists():
            print(f"archive already exists, reusing: {archive_filename}")
        else:
            print(f"creating archive for {channel} from {bundle_dir}")
            make_gztar_archive(
                src_dir=bundle_dir,
                dst_dir=targets_dir,
                app_name=channel,
                version=args.version,
            )
        print(f"registering target: {archive_filename}")
        # custom typing in tufup is JsonDict-recursive; pyright is too
        # strict about the nested {"required": False} shape, but the
        # runtime accepts it (same pattern as backfill scripts).
        repo.roles.add_or_update_target(
            local_path=archive_path,
            custom=dict(user=None, tufup={"required": False}),  # type: ignore[arg-type]
        )

    print("publishing changes...")
    repo.publish_changes(private_key_dirs=[keystore])
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
