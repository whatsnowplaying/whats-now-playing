#!/usr/bin/env python3
"""Twitch-related constants"""

from twitchAPI.type import AuthScope
import twitchAPI.helper

import nowplaying.oauth2

# OAuth and API endpoints
OAUTH_HOST = "https://id.twitch.tv"
API_HOST = "https://api.twitch.tv/helix"

# OAuth scopes - AuthScope enums for TwitchAPI library

# Chat bot scopes (minimal permissions for dedicated bot accounts)
CHAT_BOT_AUTH_SCOPES: list[AuthScope] = [
    AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT,
    AuthScope.USER_BOT,
]

# Broadcaster scopes (chat scopes + additional broadcaster permissions)
BROADCASTER_AUTH_SCOPES: list[AuthScope] = CHAT_BOT_AUTH_SCOPES + [
    AuthScope.CHANNEL_READ_REDEMPTIONS,
]

# Build scope strings from enums using TwitchAPI helper
BROADCASTER_SCOPE_STRINGS: list[str] = twitchAPI.helper.build_scope(
    BROADCASTER_AUTH_SCOPES
).split()
CHAT_BOT_SCOPE_STRINGS: list[str] = twitchAPI.helper.build_scope(CHAT_BOT_AUTH_SCOPES).split()

# Chat constants
TWITCH_MESSAGE_LIMIT = 500  # Character limit for Twitch messages

# UI constants - needs to match ui file
# missing premium, hype-train, artist-badge
TWITCHBOT_CHECKBOXES = [
    "anyone",
    "broadcaster",
    "moderator",
    "subscriber",
    "founder",
    "conductor",
    "vip",
    "bits",
]

# Special message marker for template splitting
SPLITMESSAGETEXT = "****SPLITMESSAGEHERE****"

# OAuth2 service configuration
TWITCH_SERVICE_CONFIG: nowplaying.oauth2.ServiceConfig = {
    "oauth_host": OAUTH_HOST,
    "api_host": API_HOST,
    "config_prefix": "twitchbot",
    "default_scopes": BROADCASTER_SCOPE_STRINGS,
    "token_endpoint": "/oauth2/token",
    "authorize_endpoint": "/oauth2/authorize",
    "revoke_endpoint": "/oauth2/revoke",
    "validate_endpoint": "/oauth2/validate",
}
