#!/usr/bin/env python3
"""test /wsstream blob serialization

/wsstream is the one consumer that is owed real PNG: its templates hardcode a
data:image/png prefix, and users customize copies WNP cannot update.  The metadata
pipeline keeps source bytes, so the transcode happens here at serialization time.
"""

import base64

import pytest

import nowplaying.db  # pylint: disable=import-error
import nowplaying.processes.webserver  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error
from tests.utils_images import jpeg_bytes

PNG_MAGIC = b"\211PNG\r\n\032\n"


def decoded(metadata: dict, key: str) -> bytes:
    """pull a base64 field back to bytes"""
    return base64.b64decode(metadata[key])


def test_every_blob_is_base64ed():
    """every blob is serialized, whether or not it needed converting"""
    metadata = {key: jpeg_bytes() for key in nowplaying.db.METADATABLOBLIST}

    result = nowplaying.processes.webserver.WebHandler._base64ifier(metadata)  # pylint: disable=protected-access

    for key in nowplaying.db.METADATABLOBLIST:
        newkey = key.replace("raw", "base64")
        assert key not in result, f"{key} should be replaced by {newkey}"
        assert decoded(result, newkey), newkey


def test_artist_images_are_not_transcoded_by_default():
    """genuine artist images ship as-is unless a caller opts them in

    websocket_artistfanart_streamer rebuilds a frame every fanartdelay seconds with a
    new random fanart, so converting these would put a large-JPEG re-encode on a timer
    per connection.  They were never transcoded before this release either.
    """
    fanart = jpeg_bytes(color=(200, 40, 120))
    metadata = {"coverimageraw": jpeg_bytes(), "artistfanartraw": fanart}

    result = nowplaying.processes.webserver.WebHandler._base64ifier(metadata)  # pylint: disable=protected-access

    assert decoded(result, "artistfanartbase64") == fanart
    assert decoded(result, "coverimagebase64").startswith(PNG_MAGIC)


def test_extra_convert_keys_transcodes_only_whats_opted_in():
    """_wss_do_update opts banner+thumbnail in for /wsstream; nothing else follows

    Several bundled templates hardcode data:image/png for artistbannerbase64 and
    artistthumbnailbase64 too, not just the cover, so /wsstream's genuinely
    event-driven rebuild (gated on the DB watcher's updatetime, not a fixed-interval
    poll) opts those two in.  Fanart stays out: it's the one field the fanart
    streamer's per-tick loop refreshes, and that loop reuses this same method.
    """
    banner = jpeg_bytes(color=(10, 10, 200))
    thumbnail = jpeg_bytes(color=(200, 10, 10))
    fanart = jpeg_bytes(color=(10, 200, 10))
    metadata = {
        "coverimageraw": jpeg_bytes(),
        "artistbannerraw": banner,
        "artistthumbnailraw": thumbnail,
        "artistfanartraw": fanart,
    }

    result = nowplaying.processes.webserver.WebHandler._base64ifier(  # pylint: disable=protected-access
        metadata, extra_convert_keys=frozenset({"artistbannerraw", "artistthumbnailraw"})
    )

    assert decoded(result, "artistbannerbase64").startswith(PNG_MAGIC)
    assert decoded(result, "artistthumbnailbase64").startswith(PNG_MAGIC)
    assert decoded(result, "artistfanartbase64") == fanart


def test_transparentifier_threads_extra_convert_keys():
    """the parameter has to survive _transparentifier, not just _base64ifier directly

    _wss_do_update calls _transparentifier, never _base64ifier itself.
    """
    thumbnail = jpeg_bytes(color=(200, 10, 10))
    metadata = {"coverimageraw": jpeg_bytes(), "artistthumbnailraw": thumbnail}

    # _transparentifier is an instance method whose only use of self is to call the
    # (static) _base64ifier -- passing the class itself as self resolves that call
    # correctly without needing a real WebHandler instance.
    result = nowplaying.processes.webserver.WebHandler._transparentifier(  # pylint: disable=protected-access
        nowplaying.processes.webserver.WebHandler,
        metadata,
        extra_convert_keys=frozenset({"artistthumbnailraw"}),
    )

    assert decoded(result, "artistthumbnailbase64").startswith(PNG_MAGIC)
    # untouched fields still get the placeholder, unaffected by the extra keys
    assert decoded(result, "artistfanartbase64") == nowplaying.utils.TRANSPARENT_PNG_BIN


def test_cover_copies_match_the_cover_itself():
    """the _artfallbacks shape: coverfornologos / coverfornothumbs copy the cover

    These share the cover's hardcoded data:image/png prefix, so they get the cover's
    conversion -- and reuse it rather than transcoding the same bytes again.
    """
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
