#!/usr/bin/env python3
"""Twitch-related constants"""

import twitchAPI.helper
from twitchAPI.type import AuthScope

import nowplaying.oauth2

# Public OAuth2 client identifier for the bundled WNP Twitch application.
# This is NOT a secret — Twitch client IDs are public by design (analogous to
# an app's bundle ID). The implicit grant flow used here has no client secret;
# security comes from CSRF state validation and Twitch's redirect-URI allowlist.
TWITCH_BUNDLED_CLIENT_ID = "l89y18ioij2pk7zgk7tzbenc39z2xn"

# OAuth and API endpoints
OAUTH_HOST = "https://id.twitch.tv"
API_HOST = "https://api.twitch.tv/helix"

# OAuth scopes - AuthScope enums for TwitchAPI library

# Common chat scopes needed by both broadcaster and bot accounts
_CHAT_BASE_SCOPES: list[AuthScope] = [
    AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT,
]

# Chat bot scopes — USER_BOT allows a channel to designate this account as a trusted bot
CHAT_BOT_AUTH_SCOPES: list[AuthScope] = _CHAT_BASE_SCOPES + [
    AuthScope.USER_BOT,
]

# Broadcaster scopes — chat read/send + broadcast management; no USER_BOT (wrong for own account)
BROADCASTER_AUTH_SCOPES: list[AuthScope] = _CHAT_BASE_SCOPES + [
    AuthScope.CHANNEL_READ_REDEMPTIONS,
    AuthScope.CHANNEL_MANAGE_BROADCAST,
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

# OAuth status values
OAUTH_STATUS_AUTHENTICATED = "authenticated"
OAUTH_STATUS_EXPIRED = "expired"

# cparser keys for OAuth status and usernames
BROADCASTER_OAUTH_STATUS_KEY = "twitchbot/broadcaster_oauth_status"
BROADCASTER_USERNAME_KEY = "twitchbot/broadcaster_username"
CHAT_OAUTH_STATUS_KEY = "twitchbot/chat_oauth_status"
CHAT_USERNAME_KEY = "twitchbot/chat_username"

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
