#!/usr/bin/env python3
"""test /wsstream blob serialization

/wsstream is the one consumer that is owed real PNG: its templates hardcode a
data:image/png prefix, and users customize copies WNP cannot update.  The metadata
pipeline keeps source bytes, so the transcode happens here at serialization time.
"""

import base64
import io

import PIL.Image
import pytest

import nowplaying.db  # pylint: disable=import-error
import nowplaying.processes.webserver  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error

PNG_MAGIC = b"\211PNG\r\n\032\n"


def jpeg_bytes(color: tuple[int, int, int] = (10, 200, 90)) -> bytes:
    """a real encoded JPEG -- a bare header does not decode, so image2png would
    fall through to returning the original and hide whether conversion ran"""
    buffer = io.BytesIO()
    PIL.Image.new("RGB", (120, 120), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def decoded(metadata: dict, key: str) -> bytes:
    """pull a base64 field back to bytes"""
    return base64.b64decode(metadata[key])


def test_every_blob_is_converted_to_png():
    """all blobs, not just the cover

    _artfallbacks copies coverimageraw into artistlogoraw and artistthumbnailraw, and
    the cover is source bytes now rather than a pre-transcoded PNG.  Converting only
    the cover would ship its own copies as JPEG under the same data:image/png prefix.
    """
    source = jpeg_bytes()
    metadata = dict.fromkeys(nowplaying.db.METADATABLOBLIST, source)

    result = nowplaying.processes.webserver.WebHandler._base64ifier(metadata)  # pylint: disable=protected-access

    for key in nowplaying.db.METADATABLOBLIST:
        newkey = key.replace("raw", "base64")
        assert key not in result, f"{key} should be replaced by {newkey}"
        assert decoded(result, newkey).startswith(PNG_MAGIC), f"{newkey} must be PNG"


def test_cover_copies_match_the_cover_itself():
    """the _artfallbacks shape: coverfornologos / coverfornothumbs copy the cover"""
    source = jpeg_bytes()
    metadata = {
        "coverimageraw": source,
        "artistlogoraw": source,
        "artistthumbnailraw": source,
        "coverimagetype": "image/jpeg",
    }

    result = nowplaying.processes.webserver.WebHandler._base64ifier(metadata)  # pylint: disable=protected-access

    cover = decoded(result, "coverimagebase64")
    assert cover.startswith(PNG_MAGIC)
    assert decoded(result, "artistlogobase64") == cover
    assert decoded(result, "artistthumbnailbase64") == cover
    # the type field travels in this same frame, so it cannot still say jpeg
    assert result["coverimagetype"] == "image/png"


def test_already_png_passes_through_untouched():
    """the transparent placeholder _transparentifier fills in must not be re-encoded"""
    placeholder = nowplaying.utils.TRANSPARENT_PNG_BIN
    metadata = {"artistbannerraw": placeholder}

    result = nowplaying.processes.webserver.WebHandler._base64ifier(metadata)  # pylint: disable=protected-access

    assert decoded(result, "artistbannerbase64") == placeholder


@pytest.mark.parametrize("blob_key", nowplaying.db.METADATABLOBLIST)
def test_undecodable_blob_keeps_original_bytes(blob_key):
    """conversion failure must still produce a frame rather than dropping the field"""
    garbage = b"this is not an image at all"
    metadata = {blob_key: garbage}

    result = nowplaying.processes.webserver.WebHandler._base64ifier(metadata)  # pylint: disable=protected-access

    assert decoded(result, blob_key.replace("raw", "base64")) == garbage


def test_coverimagetype_untouched_when_conversion_fails():
    """the recorded type stays true to the bytes actually sent"""
    metadata = {"coverimageraw": b"not an image", "coverimagetype": "image/jpeg"}

    result = nowplaying.processes.webserver.WebHandler._base64ifier(metadata)  # pylint: disable=protected-access

    assert result["coverimagetype"] == "image/jpeg"


def test_dbid_is_stripped():
    """dbid is internal and should never reach a template"""
    result = nowplaying.processes.webserver.WebHandler._base64ifier({"dbid": 42, "artist": "x"})  # pylint: disable=protected-access

    assert "dbid" not in result
    assert result["artist"] == "x"
