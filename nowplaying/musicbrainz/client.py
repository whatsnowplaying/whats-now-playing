#!/usr/bin/env python3
"""
MusicBrainz client for nowplaying — thin re-export of wnpmb.
"""

from wnpmb import (
    MusicBrainzClient,
    MusicBrainzError,
    NetworkError,
    RateLimitError,
    ResponseError,
)
from wnpmb.client._base import RetrySettings

__all__ = [
    "MusicBrainzClient",
    "MusicBrainzError",
    "NetworkError",
    "NetworkError",
    "RateLimitError",
    "ResponseError",
    "RetrySettings",
]
