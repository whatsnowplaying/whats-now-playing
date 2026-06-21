#!/usr/bin/env python3
"""Populate nowplaying/templates/ with built assets from wnp_templates.

Copies .htm files from the installed wnp_templates package and downloads
vendor fonts/JS from their canonical CDN URLs.  Run by builder.sh before
PyInstaller so the bundled app includes current template assets.

Output directories are gitignored build artifacts:
  nowplaying/templates/*.htm
  nowplaying/templates/vendor/
"""

import pathlib
import shutil
import sys
import urllib.request

import truststore

truststore.inject_into_ssl()

import wnp_templates  # noqa: E402  (after truststore injection)

TEMPLATE_DIR = pathlib.Path(__file__).parent.parent / "nowplaying" / "templates"
VENDOR_DIR = TEMPLATE_DIR / "vendor"


def copy_templates() -> None:
    print("Copying .htm files from wnp_templates package...")
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in wnp_templates.BUNDLED_TEMPLATE_DIR.glob("*.htm"):
        dest = TEMPLATE_DIR / src.name
        shutil.copy2(src, dest)
        copied += 1
    print(f"  Copied {copied} template(s).")


def download_vendor() -> None:
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
    copy_templates()
    download_vendor()
    print("Done.")
