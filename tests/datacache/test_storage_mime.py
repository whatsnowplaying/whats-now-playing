#!/usr/bin/env python3
"""Tests for the image MIME predicates in nowplaying/datacache/storage.py.

Split from test_storage.py: these are pure functions with no storage fixtures, and
keeping them there pushed that module past pylint's line limit.
"""

import unittest.mock

import PIL.Image
import pytest

import nowplaying.datacache.storage  # pylint: disable=import-error
from tests.utils_images import encoded_image, unparseable_image_bytes


@pytest.mark.parametrize(
    "image_format,expected",
    [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("GIF", "image/gif"),
        ("WEBP", "image/webp"),
        # Windows Media hands over whatever the player registered, which is where a
        # BMP cover actually comes from now that inputs no longer transcode
        ("BMP", "image/bmp"),
        ("TIFF", "image/tiff"),
    ],
)
def test_detect_image_mime_real_images(image_format, expected):
    """every format Pillow can open reports a usable image/<subtype>"""
    image = encoded_image(image_format)
    assert nowplaying.datacache.storage.detect_image_mime(image) == expected


@pytest.mark.parametrize(
    "image,description",
    [
        (b"not an image at all", "no magic"),
        (b"<html><script>alert(1)</script></html>", "html"),
        # The case magic-byte detection cannot catch: puremagic calls this image/png,
        # so anything relying on magic alone would keep it and label it as an image.
        (unparseable_image_bytes(), "png magic, unparsable body"),
        (encoded_image("JPEG")[:40], "truncated jpeg"),
        (b"", "empty"),
        (None, "absent"),
    ],
)
def test_detect_image_mime_rejects_unparseable(image, description):
    """None means do not keep or serve these bytes -- there is no default"""
    assert nowplaying.datacache.storage.detect_image_mime(image) is None, description


@pytest.mark.parametrize(
    "value,acceptable",
    [
        ("image/png", True),
        ("image/jpeg", True),
        ("IMAGE/PNG", True),
        # not an image
        ("text/html", False),
        ("audio/x-sndr", False),
        ("application/json", False),
        # unusable as a Content-Type even where the bytes might be fine:
        # aiohttp raises on a charset parameter, and separators could split the header
        ("image/png; charset=utf-8", False),
        ("image/png,text/html", False),
        ("image/png\r\nX-Evil: 1", False),
        # degenerate
        ("image/", False),
        ("", False),
        (None, False),
    ],
)
def test_is_image_mime(value, acceptable):
    """the single definition of an acceptable image Content-Type"""
    assert nowplaying.datacache.storage.is_image_mime(value) is acceptable


def test_detect_image_mime_does_not_decode_pixels():
    """Image.open() parses the header only, which is what keeps this live-path cheap."""
    # Encode before patching: Image.save() calls load() itself, so building the
    # fixture inside the patch would count the fixture's own decode.
    image = encoded_image("PNG")

    with unittest.mock.patch.object(PIL.Image.Image, "load") as mock_load:
        assert nowplaying.datacache.storage.detect_image_mime(image) == "image/png"

    mock_load.assert_not_called()
