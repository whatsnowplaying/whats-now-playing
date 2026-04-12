#!/usr/bin/env python3
"""Sample image data for template preview.

Images live in nowplaying/resources/preview/ and are loaded on demand via
load_sample_images().  The generation script (generate_preview_images.py in
the repo root) can recreate them if needed.

In the frozen (PyInstaller) build the files are extracted to
  _MEIPASS/resources/preview/
which matches the bundledir layout used elsewhere in the app.
"""

import logging
import pathlib


def _resource_dir(bundledir: pathlib.Path | None) -> pathlib.Path:
    if bundledir:
        return bundledir / "resources" / "preview"
    # Fallback for tests that run without a full Qt bootstrap
    return pathlib.Path(__file__).parent.parent / "resources" / "preview"


def _load(resource_dir: pathlib.Path, filename: str) -> bytes:
    path = resource_dir / filename
    try:
        return path.read_bytes()
    except OSError:
        logging.warning("Preview image not found: %s", path)
        return b""


def load_sample_images(bundledir: pathlib.Path | None) -> dict[str, bytes]:
    """Load all sample images and return as a dict of field-name → bytes."""
    resource_dir = _resource_dir(bundledir)
    return {
        "coverimageraw": _load(resource_dir, "sample_cover.png"),
        "artistthumbnailraw": _load(resource_dir, "sample_artistthumb.png"),
        "artistbannerraw": _load(resource_dir, "sample_artistbanner.png"),
        "artistlogoraw": _load(resource_dir, "sample_artistlogo.png"),
        "artistfanartraw": _load(resource_dir, "sample_artistfanart.png"),
    }


# Number of fanart variants available for slideshow preview.
# images_websocket.py detects artist == "Sample Artist" and serves these
# at random so the slideshow has enough distinct images to cycle through.
FANART_VARIANT_COUNT = 6


def load_sample_fanart_variants(bundledir: pathlib.Path | None) -> list[bytes]:
    """Load the fanart slideshow variants for preview mode."""
    resource_dir = _resource_dir(bundledir)
    return [
        _load(resource_dir, f"sample_artistfanart_{i}.png") for i in range(FANART_VARIANT_COUNT)
    ]
