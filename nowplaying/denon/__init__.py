#!/usr/bin/env python3
"""
Denon DJ StagelinQ Package

This package contains all the components for Denon DJ StagelinQ protocol support,
organized into focused modules for better maintainability.
"""

# Re-export main components for easy importing
from .plugin import DenonPlugin
from .types import DenonDevice, DenonService, DenonState, StagelinqError

__all__ = ["DenonPlugin", "DenonDevice", "DenonService", "DenonState", "StagelinqError"]
