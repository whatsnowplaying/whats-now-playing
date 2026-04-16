#!/usr/bin/env python3
"""Sample metadata for template preview when no track is playing."""

import pathlib

import nowplaying.preview.imagedata
from nowplaying.types import TrackMetadata

# NOTE: "Sample Artist" is a sentinel value tied to preview behaviour in
# nowplaying/webserver/images_websocket.py — when that artist name is seen on
# a fanart request, the server returns pre-generated images from resources/preview/
# instead of looking in the image cache.  If you change this name, update
# _handle_artist_images in images_websocket.py to match.
_BASE_METADATA: TrackMetadata = {
    "artist": "Sample Artist",
    "title": "Sample Track Title",
    "album": "Sample Album",
    "albumartist": "Sample Artist",
    "genre": "Electronic",
    "date": "2024",
    "duration": 225,
    "duration_hhmmss": "0:03:45",
    "bpm": "128",
    "key": "Am",
    "label": "Sample Label",
    "track": "1",
    "track_total": "12",
    "disc": "1",
    "disc_total": "1",
    "bitrate": "320000",
    "cmdname": "command",
    "cmdtarget": ["SampleUser"],
    "previoustrack": [
        {"artist": "Sample Artist", "title": "Sample Track Title"},
        {"artist": "Previous Artist", "title": "Previous Track Title"},
        {"artist": "Earlier Artist", "title": "Earlier Track Title"},
    ],
    "comments": "Sample comment for preview",
    "composer": "Sample Composer",
    "isrc": ["USRC12345678"],
    "musicbrainzartistid": ["00000000-0000-0000-0000-000000000000"],
    "musicbrainzrecordingid": "00000000-0000-0000-0000-000000000001",
    "artistshortbio": (
        "Sample Artist is a fictional artist used for template preview. "
        "Their music spans multiple genres and has influenced countless DJs worldwide."
    ),
    "artistlongbio": (
        "Sample Artist is a fictional artist used for template preview. "
        "Their music spans multiple genres and has influenced countless DJs worldwide. "
        "Founded in 2024, they have released numerous albums and toured extensively. "
        "This biography is provided as sample data so you can preview how your template "
        "renders biographical text without needing a live track."
    ),
}


def get_preview_metadata(bundledir: pathlib.Path | None = None) -> TrackMetadata:
    """Return a complete sample TrackMetadata dict including images.

    Args:
        bundledir: The application bundle directory (config.getbundledir()).
                   Pass None only in tests without a full Qt bootstrap.
    """
    metadata: TrackMetadata = dict(_BASE_METADATA)  # type: ignore[arg-type]
    metadata.update(nowplaying.preview.imagedata.load_sample_images(bundledir))
    return metadata
