#!/usr/bin/env python3
"""Prepare nowplaying/templates/ for a build.

Downloads vendor fonts/JS from their canonical CDN URLs into
nowplaying/templates/vendor/ (they are deliberately not shipped in the
wnp_templates wheel).  Run by builder.sh before PyInstaller.

The ws-*.htm templates are NOT copied here: the frozen app gets them from
the wnp_templates package data (collected in WhatsNowPlaying.spec) and the
webserver resolves them through the template chain.  Any ws-*.htm left in
nowplaying/templates/ from older build systems is removed so a local
build cannot bundle stale copies.

Output directories are gitignored build artifacts:
  nowplaying/templates/vendor/
"""

import pathlib
import sys
import urllib.request

import truststore

truststore.inject_into_ssl()

import wnp_templates  # noqa: E402  pylint: disable=wrong-import-position

TEMPLATE_DIR = pathlib.Path(__file__).parent.parent / "nowplaying" / "templates"
VENDOR_DIR = TEMPLATE_DIR / "vendor"


def remove_stale_templates() -> None:
    """Remove ws-*.htm leftovers from older build systems."""
    removed = 0
    for stale in TEMPLATE_DIR.glob("ws-*.htm"):
        stale.unlink()
        removed += 1
    if removed:
        print(f"Removed {removed} stale ws-*.htm file(s) from {TEMPLATE_DIR}")


def download_vendor() -> None:
    """Download vendor fonts/JS from their canonical CDN URLs."""
    print("Downloading vendor files...")
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in wnp_templates.VENDOR_FILES.items():
        dest = VENDOR_DIR / filename
        if dest.exists():
            print(f"  Skipping {filename} (already present)")
            continue
        print(f"  Downloading {filename}...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as resp:
                dest.write_bytes(resp.read())
        except (OSError, ValueError) as err:
            print(f"  ERROR: failed to download {filename}: {err}", file=sys.stderr)
            sys.exit(1)
    print(f"  {len(wnp_templates.VENDOR_FILES)} vendor file(s) ready.")


if __name__ == "__main__":
    remove_stale_templates()
    download_vendor()
    print("Done.")
