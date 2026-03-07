#!/usr/bin/env python3
"""nowplaying.metadata package — audio metadata processing"""

# Re-export the public API so existing callers continue to work unchanged:
#   import nowplaying.metadata
#   nowplaying.metadata.MetadataProcessors(...)
#   nowplaying.metadata.TinyTagRunner(...)
#   nowplaying.metadata.AUDIO_EXTENSIONS
from nowplaying.metadata.processors import MetadataProcessors, main, recognition_replacement
from nowplaying.metadata.tinytag_runner import (
    AUDIO_CONTAINER_EXCLUSIONS,
    AUDIO_EXTENSIONS,
    TinyTagRunner,
    VIDEO_EXTENSIONS,
)

__all__ = [
    "AUDIO_CONTAINER_EXCLUSIONS",
    "AUDIO_EXTENSIONS",
    "MetadataProcessors",
    "TinyTagRunner",
    "VIDEO_EXTENSIONS",
    "main",
    "recognition_replacement",
]
