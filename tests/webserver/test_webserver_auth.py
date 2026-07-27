#!/usr/bin/env python3
"""tests for shared inbound client authentication"""

import aiohttp.test_utils
import pytest
from aiohttp import web

import nowplaying.webserver.auth

SECRET = "correct-horse-battery-staple"


def _request(headers: dict[str, str] | None = None) -> web.Request:
    """build a mocked GET request carrying the given headers"""
    return aiohttp.test_utils.make_mocked_request("GET", "/v1/requests", headers=headers or {})


@pytest.mark.parametrize(
    "configured,header,legacy,expected",
    [
        # No key configured: auth is disabled, everything passes
        ("", None, None, nowplaying.webserver.auth.AUTH_OK),
        ("", "anything", None, nowplaying.webserver.auth.AUTH_OK),
        ("", None, "anything", nowplaying.webserver.auth.AUTH_OK),
        # Header only
        (SECRET, SECRET, None, nowplaying.webserver.auth.AUTH_OK),
        (SECRET, "wrong", None, nowplaying.webserver.auth.AUTH_INVALID),
        # Legacy query/body field only (backwards compatibility)
        (SECRET, None, SECRET, nowplaying.webserver.auth.AUTH_OK),
        (SECRET, None, "wrong", nowplaying.webserver.auth.AUTH_INVALID),
        # Nothing supplied at all
        (SECRET, None, None, nowplaying.webserver.auth.AUTH_MISSING),
        (SECRET, "", "", nowplaying.webserver.auth.AUTH_MISSING),
        # Both supplied: the header decides, so a bad header fails even when
        # the legacy value would have passed (no silent downgrade)
        (SECRET, SECRET, "wrong", nowplaying.webserver.auth.AUTH_OK),
        (SECRET, "wrong", SECRET, nowplaying.webserver.auth.AUTH_INVALID),
    ],
)
def test_check_client_auth(bootstrap, configured, header, legacy, expected):
    """the configured key, header, and legacy field combine into one verdict"""
    config = bootstrap
    config.cparser.setValue("remote/remote_key", configured)
    headers = {} if header is None else {nowplaying.webserver.auth.CLIENT_AUTH_HEADER: header}

    result = nowplaying.webserver.auth.check_client_auth(
        _request(headers), config, legacy_secret="" if legacy is None else legacy
    )

    assert result == expected


@pytest.mark.parametrize(
    "header_name",
    [
        "X-WNP-Client-Auth",
        "x-wnp-client-auth",
        "X-WNP-CLIENT-AUTH",
    ],
)
def test_check_client_auth_header_name_is_case_insensitive(bootstrap, header_name):
    """HTTP header names are case-insensitive, so any casing must authenticate"""
    config = bootstrap
    config.cparser.setValue("remote/remote_key", SECRET)

    result = nowplaying.webserver.auth.check_client_auth(_request({header_name: SECRET}), config)

    assert result == nowplaying.webserver.auth.AUTH_OK


@pytest.mark.parametrize("secret", ["pässwörd-ünïcode", "密码キー", "emoji-🎧-key"])
def test_check_client_auth_accepts_non_ascii_secrets(bootstrap, secret):
    """non-ASCII secrets must compare cleanly rather than raising TypeError"""
    config = bootstrap
    config.cparser.setValue("remote/remote_key", secret)

    headers = {nowplaying.webserver.auth.CLIENT_AUTH_HEADER: secret}
    assert (
        nowplaying.webserver.auth.check_client_auth(_request(headers), config)
        == nowplaying.webserver.auth.AUTH_OK
    )

    wrong = {nowplaying.webserver.auth.CLIENT_AUTH_HEADER: "not-the-secret"}
    assert (
        nowplaying.webserver.auth.check_client_auth(_request(wrong), config)
        == nowplaying.webserver.auth.AUTH_INVALID
    )
