#!/usr/bin/env python3
"""
Serato 3 Input Plugin

This module provides the legacy Serato input plugin for reading track data from
local Serato library files or Serato Live playlists (Serato DJ ≤3).

The implementation has been refactored into a modular structure in the
nowplaying.serato3 package for better maintainability and separation of concerns.
"""

# Import all classes from the legacy modular structure for backwards compatibility
from nowplaying.serato3 import (
    Plugin,
    SeratoBaseReader,
    SeratoCrateReader,
    SeratoDatabaseV2Reader,
    SeratoHandler,
    SeratoRuleMatchingMixin,
    SeratoSessionReader,
    SeratoSmartCrateReader,
)

# Export all classes to maintain full backwards compatibility
__all__ = [
    "Plugin",
    "SeratoHandler",
    "SeratoBaseReader",
    "SeratoRuleMatchingMixin",
    "SeratoDatabaseV2Reader",
    "SeratoCrateReader",
    "SeratoSmartCrateReader",
    "SeratoSessionReader",
]
