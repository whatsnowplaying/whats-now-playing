#!/bin/bash
# Extract the 4 platform zips downloaded from a GH Release into
# channel-named bundle directories.
#
# Used by .github/workflows/tufup-publish.yaml to prepare unpacked
# binaries for tufup_publish.py to archive.
#
# Usage:
#   extract_release_zips.sh <zip_source_dir> <dest_dir> [<channel_suffix>]
#
# Each zip contains a single top-level wrapper dir; this script
# flattens that so the per-channel dest dirs contain the bundle
# contents directly (matching what tufup's make_gztar_archive
# expects).
#
# Channel naming follows the spec in docs/dev/charts-server-spec.md:
#   WhatsNowPlaying_<os><version>_<arch>[_<channel_suffix>]
# The optional suffix is "_prerelease" for prerelease channels.

set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "usage: $0 <zip_source_dir> <dest_dir> [<channel_suffix>]" >&2
    exit 64  # EX_USAGE
fi

ZIP_SRC="$1"
DEST="$2"
SUFFIX="${3:-}"

if [[ ! -d "$ZIP_SRC" ]]; then
    echo "error: zip source dir does not exist: $ZIP_SRC" >&2
    exit 1
fi

mkdir -p "$DEST"

# Filename-pattern -> channel-name mapping.  The pattern is matched
# against the zip filename suffix (with a wildcard prefix).
declare -A channel_for
channel_for[Linux-x86_64]="WhatsNowPlaying_linux_x86_64${SUFFIX}"
channel_for[macOS15-AppleSilicon]="WhatsNowPlaying_macos15_arm${SUFFIX}"
channel_for[macOS15-Intel]="WhatsNowPlaying_macos15_intel${SUFFIX}"
channel_for[Windows]="WhatsNowPlaying_windows_x86_64${SUFFIX}"

for key in "${!channel_for[@]}"; do
    channel="${channel_for[$key]}"
    zip=$(find "$ZIP_SRC" -maxdepth 1 -name "*${key}.zip" | head -n 1)
    if [[ -z "$zip" ]]; then
        echo "::error::No zip found matching *${key}.zip in ${ZIP_SRC}"
        exit 1
    fi
    out="${DEST}/${channel}"
    mkdir -p "$out"
    unzip -q "$zip" -d "$out"
    # Each zip contains a single top-level wrapper directory; tufup
    # wants the directory contents, not the wrapper.  Flatten one
    # level if present.
    inner=$(find "$out" -mindepth 1 -maxdepth 1 -type d)
    if [[ -n "$inner" ]]; then
        # shellcheck disable=SC2086  # globbing intentional
        mv "$inner"/* "$inner"/.[!.]* "$out"/ 2>/dev/null || true
        rmdir "$inner" 2>/dev/null || true
    fi
    echo "extracted $(basename "$zip") -> $out (channel: $channel)"
done
