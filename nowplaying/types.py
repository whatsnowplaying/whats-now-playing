#!/usr/bin/env python3
"""Type definitions for nowplaying structures."""

from typing import TypedDict, TYPE_CHECKING

if TYPE_CHECKING:
    import nowplaying.inputs
    import nowplaying.artistextras
    import nowplaying.recognition


class TrackMetadata(TypedDict, total=False):
    """Structured metadata for a music track. All fields are optional."""
    # Basic track information
    title: str
    artist: str
    album: str
    albumartist: str
    date: str
    year: str
    originalyear: str
    duration: int

    # Track/disc numbers
    track: str
    track_total: str
    disc: str
    disc_total: str
    discsubtitle: str

    # Musical metadata
    genre: str
    composer: str
    bpm: str
    key: str
    lang: str
    label: str
    publisher: str

    # Technical metadata
    filename: str
    bitrate: str
    coverimagetype: str
    coverurl: str
    coverimageraw: bytes

    # Identifiers and codes
    isrc: list[str]
    musicbrainzartistid: list[str]
    musicbrainzalbumid: str
    musicbrainzrecordingid: str
    acoustidid: str

    # Artist extras
    artistlongbio: str
    artistshortbio: str
    artistwebsites: list[str]
    artistfanarturls: list[str]
    artistfanartraw: bytes
    artistbannerraw: bytes
    artistlogoraw: bytes
    artistthumbnailraw: bytes
    imagecacheartist: str
    imagecachealbum: str

    # Comments and descriptions
    comments: str
    comment: str

    # Host and streaming metadata
    httpport: int
    hostname: str
    hostfqdn: str
    hostip: str
    ipaddress: str

    # Request system
    requester: str
    requestdisplayname: str
    requesterimageraw: bytes

    # Processing metadata
    previoustrack: list[dict[str, str]]
    dbid: int
    deck: str
    duration_hhmmss: str
    fpcalcduration: int
    fpcalcfingerprint: str
    genres: list[str]


class PluginObjs(TypedDict):
    """Dictionary structure for plugin instances organized by type."""
    inputs: dict[str, "nowplaying.inputs.InputPlugin"]
    artistextras: dict[str, "nowplaying.artistextras.ArtistExtrasPlugin"]
    recognition: dict[str, "nowplaying.recognition.RecognitionPlugin"]
