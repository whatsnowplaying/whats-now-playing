#!/usr/bin/env python3
"""
Serato Input Plugin

This module provides the Serato input plugin for reading track data from
Serato DJ 4.0+ SQLite database architecture.

The implementation uses a modular structure in the nowplaying.serato package
for better maintainability and separation of concerns.
"""

# Import the main plugin class from the modular structure
from nowplaying.serato import Plugin

# Export for backwards compatibility
__all__ = [
    "Plugin",
]
