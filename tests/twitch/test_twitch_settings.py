#!/usr/bin/env python3
"""test twitch settings status text"""

import pytest

import nowplaying.twitch.settings  # pylint: disable=import-error
from nowplaying.twitch.constants import (  # pylint: disable=import-error
    OAUTH_STATUS_AUTHENTICATED,
    OAUTH_STATUS_EXPIRED,
)

BROADCASTER = nowplaying.twitch.settings.TwitchSettings._broadcaster_status_text  # pylint: disable=protected-access
CHAT = nowplaying.twitch.settings.TwitchSettings._chat_status_text  # pylint: disable=protected-access


@pytest.mark.parametrize(
    "status,username,has_token,expected",
    [
        # The username is written on every successful auth and cleared nowhere,
        # so an expired token has to outrank it or a DJ who has ever signed in
        # sees their name and no hint that redemptions are dead.
        (OAUTH_STATUS_EXPIRED, "djsomeone", True, "djsomeone: token expired, re-authenticate"),
        (OAUTH_STATUS_EXPIRED, "", True, "token expired, re-authenticate"),
        (OAUTH_STATUS_AUTHENTICATED, "djsomeone", True, "djsomeone"),
        (OAUTH_STATUS_AUTHENTICATED, "", True, "authenticated"),
        ("", "djsomeone", True, "djsomeone"),
        ("", "", True, "connecting..."),
        ("", "", False, "Not authenticated"),
    ],
)
def test_broadcaster_status_text(status, username, has_token, expected):
    """Expiry must be reported even when a stale username is stored."""
    assert BROADCASTER(status, username, has_token) == expected


@pytest.mark.parametrize(
    "status,username,has_token,expected",
    [
        (OAUTH_STATUS_EXPIRED, "djsomeone", True, "djsomeone: token expired, re-authenticate"),
        (OAUTH_STATUS_EXPIRED, "", True, "token expired, re-authenticate"),
        (OAUTH_STATUS_AUTHENTICATED, "djsomeone", True, "djsomeone"),
        ("", "", False, "Using broadcaster account"),
    ],
)
def test_chat_status_text(status, username, has_token, expected):
    """Chat follows the same ordering as the broadcaster label."""
    assert CHAT(status, username, has_token) == expected
