#!/usr/bin/env python3
"""
Rekordbox Input Plugin Wrapper

This is a simple wrapper that exposes the main Rekordbox plugin from the
nowplaying.rekordbox package. This allows the plugin discovery system to
find the plugin while keeping the actual implementation organized
in a separate package structure.
"""

# Import the main plugin class from the rekordbox package
from nowplaying.rekordbox import RekordboxPlugin

# Expose it as Plugin for the plugin discovery system
Plugin = RekordboxPlugin
