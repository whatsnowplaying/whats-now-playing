#!/usr/bin/env python3
"""test twitch redemptions"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

import nowplaying.twitch.redemptions  # pylint: disable=import-error


@pytest.mark.asyncio
async def test_failed_login_keeps_the_stored_tokens(bootstrap):
    """api_login() returning None is not evidence the stored token is bad.

    run_redemptions() retries this every 10 seconds while unauthenticated, so
    clearing the tokens here deleted the user's credentials six times a minute
    and raced the browser OAuth flow that was writing new ones.
    """
    bootstrap.cparser.setValue("twitchbot/accesstoken", "access_token")
    bootstrap.cparser.setValue("twitchbot/refreshtoken", "refresh_token")

    redemptions = nowplaying.twitch.redemptions.TwitchRedemptions(config=bootstrap)

    with patch.object(redemptions.redemption_login, "api_login", AsyncMock(return_value=None)):
        connected = await redemptions._setup_eventsub_connection()  # pylint: disable=protected-access

    assert connected is False
    assert bootstrap.cparser.value("twitchbot/accesstoken") == "access_token"
    assert bootstrap.cparser.value("twitchbot/refreshtoken") == "refresh_token"


@pytest.mark.asyncio
async def test_failed_get_users_keeps_the_stored_tokens(bootstrap):
    """A get_users() call that did not come back is not a verdict on the token."""
    bootstrap.cparser.setValue("twitchbot/accesstoken", "access_token")
    bootstrap.cparser.setValue("twitchbot/refreshtoken", "refresh_token")

    redemptions = nowplaying.twitch.redemptions.TwitchRedemptions(config=bootstrap)
    # get_users() is a sync call returning an async generator, so a plain Mock
    # that raises on call is the faithful shape here.
    redemptions.twitch = Mock(get_users=Mock(side_effect=OSError("network is down")))

    user = await redemptions._get_authenticated_user()  # pylint: disable=protected-access

    assert user is None
    assert bootstrap.cparser.value("twitchbot/accesstoken") == "access_token"
    assert bootstrap.cparser.value("twitchbot/refreshtoken") == "refresh_token"


@pytest.mark.asyncio
async def test_retry_closes_the_previous_twitch_client(bootstrap):
    """Each api_login() builds a client with its own aiohttp session.

    The retry loop calls this repeatedly, so without closing the old one a
    long unauthenticated stretch accumulates sessions.
    """
    redemptions = nowplaying.twitch.redemptions.TwitchRedemptions(config=bootstrap)
    first_client = Mock(close=AsyncMock())

    with patch.object(
        redemptions.redemption_login, "api_login", AsyncMock(return_value=first_client)
    ):
        # get_users() fails, so the connection attempt aborts after api_login()
        # and the loop would come back around.
        first_client.get_users = Mock(side_effect=OSError("network is down"))
        assert await redemptions._setup_eventsub_connection() is False  # pylint: disable=protected-access
        first_client.close.assert_not_called()

        # Second pass: the client from the first pass has to be released.
        with patch.object(redemptions.redemption_login, "api_login", AsyncMock(return_value=None)):
            assert await redemptions._setup_eventsub_connection() is False  # pylint: disable=protected-access

    first_client.close.assert_awaited_once()
