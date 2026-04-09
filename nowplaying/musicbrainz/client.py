#!/usr/bin/env python3
"""
MusicBrainz client for nowplaying — thin re-export of wnpmb.
"""

from nowplaying.vendor.wnpmb import (  # pylint: disable=no-name-in-module,import-error
    MusicBrainzClient,
    MusicBrainzError,
    NetworkError,
    RateLimitError,
    ResponseError,
)
from nowplaying.vendor.wnpmb.client._base import RetrySettings  # pylint: disable=no-name-in-module,import-error

__all__ = [
    "MusicBrainzClient",
    "MusicBrainzError",
    "NetworkError",
    "RateLimitError",
    "ResponseError",
    "RetrySettings",
]
