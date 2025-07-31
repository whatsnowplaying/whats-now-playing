#!/usr/bin/env python3
"""Type definitions for nowplaying structures."""

from typing import TypedDict, TYPE_CHECKING

if TYPE_CHECKING:
    import nowplaying.inputs
    import nowplaying.artistextras
    import nowplaying.notifications
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
    lyricist: str
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
    twitchchannel: str
    kickchannel: str
    discordguild: str

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

    # Control metadata
    cache_warmed: bool
    secret: str


class PluginObjs(TypedDict):
    """Dictionary structure for plugin instances organized by type."""

    inputs: dict[str, "nowplaying.inputs.InputPlugin"]
    artistextras: dict[str, "nowplaying.artistextras.ArtistExtrasPlugin"]
    notifications: dict[str, "nowplaying.notifications.NotificationPlugin"]
    recognition: dict[str, "nowplaying.recognition.RecognitionPlugin"]


class BaseTrackRequest(TypedDict, total=False):
    """all DB answers have these fields"""

    reqid: int
    timestamp: str
    type: str


class UserTrackRequest(BaseTrackRequest, total=False):
    """TypedDict for userrequest database records"""

    # Text fields
    artist: str | None
    title: str | None
    displayname: str | None
    playlist: str | None
    username: str
    filename: str | None
    user_input: str
    normalizedartist: str
    normalizedtitle: str

    # Blob fields
    userimage: bytes | None


class GifWordsTrackRequest(BaseTrackRequest, total=False):
    """TypedDict for gifwords database records"""

    # Text fields
    keywords: str
    requester: str
    requestdisplayname: str | None
    imageurl: str | None

    # Blob fields
    image: bytes | None


class TrackRequestResult(TypedDict, total=False):
    """TypedDict for request lookup results returned to caller"""

    requester: str
    requestdisplayname: str | None
    requesterimageraw: bytes | None
    requestartist: str | None
    requesttitle: str | None


class TrackRequestSetting(TypedDict, total=False):
    """TypedDict for request settings/configuration"""

    displayname: str
    playlist: str
    userimage: bytes
