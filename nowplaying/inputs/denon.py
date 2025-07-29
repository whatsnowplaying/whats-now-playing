#!/usr/bin/env python3
"""
Denon DJ StagelinQ Input Plugin Wrapper

This is a simple wrapper that exposes the main Denon plugin from the
nowplaying.denon package. This allows the plugin discovery system to
find the plugin while keeping the actual implementation organized
in a separate package structure.
"""

# Import the main plugin class from the denon package
from nowplaying.denon import DenonPlugin

# Expose it as Plugin for the plugin discovery system
Plugin = DenonPlugin
