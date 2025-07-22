#!/usr/bin/env python3
"""
MusicBrainz integration for nowplaying.

This module provides MusicBrainz API integration including:
- Async HTTP client for MusicBrainz API
- XML response parser optimized for nowplaying usage
- High-level helper class for metadata lookup and recognition
"""

from .helper import MusicBrainzHelper
from .client import MusicBrainzClient

__all__ = ["MusicBrainzHelper", "MusicBrainzClient"]
