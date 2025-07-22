#!/usr/bin/env python3
"""TwitchAPI compatibility shim for unpickling old AuthScope enums from Qt config"""

import sys
import types
from enum import Enum


class AuthScope(Enum):
    """Legacy AuthScope enum for unpickling old Qt config entries"""

    # Only include the specific values that were actually stored in configs
    CHANNEL_READ_REDEMPTIONS = "channel:read:redemptions"
    CHAT_READ = "chat:read"
    CHAT_EDIT = "chat:edit"


class InvalidRefreshTokenException(Exception):
    """Legacy exception for unpickling old Qt config entries"""


def install_legacy_types():
    """Install legacy TwitchAPI types for Qt config unpickling compatibility"""
    # Only create fake modules if the real TwitchAPI package isn't available
    try:
        import twitchAPI  # pylint: disable=import-outside-toplevel,unused-import

        # Real TwitchAPI exists, just add our legacy types module
        if "twitchAPI.types" not in sys.modules:
            fake_types_module = _common_install_legacy_types()
    except ImportError:
        # Real TwitchAPI doesn't exist, create fake modules for compatibility
        if "twitchAPI.types" not in sys.modules:
            fake_types_module = _common_install_legacy_types()
            # Also create the parent twitchAPI module if it doesn't exist
            if "twitchAPI" not in sys.modules:
                fake_twitchapi_module = types.ModuleType("twitchAPI")
                fake_twitchapi_module.types = fake_types_module
                sys.modules["twitchAPI"] = fake_twitchapi_module


def _common_install_legacy_types():
    result = types.ModuleType("twitchAPI.types")
    result.AuthScope = AuthScope
    result.InvalidRefreshTokenException = InvalidRefreshTokenException
    sys.modules["twitchAPI.types"] = result
    return result


# Auto-install on import
install_legacy_types()
