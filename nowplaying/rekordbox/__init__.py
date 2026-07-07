#!/usr/bin/env python3
"""
Rekordbox Package

This package contains all the components for Rekordbox database access,
organized into focused modules for better maintainability.
"""

# Re-export main components for easy importing
from .plugin import RekordboxPlugin
from .types import RekordboxTrack, RekordboxError

__all__ = ["RekordboxPlugin", "RekordboxTrack", "RekordboxError"]
