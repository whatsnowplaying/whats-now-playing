#!/usr/bin/env python3
"""
djay Pro Input Plugin

This module provides the djay Pro input plugin for reading track data from
the Algoriddim djay Pro MediaLibrary database on macOS and Windows.

The implementation uses a modular structure in the nowplaying.djaypro package
for better maintainability and separation of concerns.
"""

from nowplaying.djaypro import Plugin

__all__ = [
    "Plugin",
]
