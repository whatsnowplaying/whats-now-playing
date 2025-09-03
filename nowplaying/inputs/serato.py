#!/usr/bin/env python3
"""
Serato Input Plugin

This module provides the Serato input plugin for reading track data from
local Serato library files or Serato Live playlists.

The implementation has been refactored into a modular structure in the
nowplaying.serato package for better maintainability and separation of concerns.
"""

# Import all classes from the new modular structure for backwards compatibility
from nowplaying.serato import (
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
