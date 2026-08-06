#!/usr/bin/env python3
"""Real encoded images for tests.

Cover art now has to be parseable, not merely magic-byte plausible: processors
rejects bytes Pillow cannot open, because a signature followed by garbage passes
puremagic and still raises in Pillow.  Fixtures built by hand from a header plus
filler no longer exercise the paths they look like they exercise -- they take the
rejection branch instead -- so build them with Pillow.

Not a fixture module on purpose: these are plain functions so tests can call them
at module scope for parametrize() values.
"""

import io

import PIL.Image

DEFAULT_COLOR = (10, 200, 90)


def encoded_image(
    image_format: str = "PNG",
    color: tuple[int, int, int] = DEFAULT_COLOR,
    size: tuple[int, int] = (60, 60),
) -> bytes:
    """Return real encoded image bytes that Pillow can open and puremagic can name."""
    buffer = io.BytesIO()
    PIL.Image.new("RGB", size, color).save(buffer, format=image_format)
    return buffer.getvalue()


def png_bytes(color: tuple[int, int, int] = DEFAULT_COLOR) -> bytes:
    """A real PNG."""
    return encoded_image("PNG", color)


def jpeg_bytes(color: tuple[int, int, int] = DEFAULT_COLOR) -> bytes:
    """A real JPEG -- the shape most album art actually arrives in."""
    return encoded_image("JPEG", color)


def unparseable_image_bytes() -> bytes:
    """A PNG signature followed by garbage.

    Passes puremagic as image/png and still raises in Pillow, which is the case
    that separates "detectably an image" from "parseable as one".
    """
    return b"\x89PNG\r\n\x1a\n" + b"not really a png" * 4
