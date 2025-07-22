#!/usr/bin/env python3
"""kick utils"""

import logging
from typing import Any

import nowplaying.config
import nowplaying.kick.oauth2


async def attempt_token_refresh(config: nowplaying.config.ConfigFile) -> bool:
    """Try to refresh existing tokens"""
    oauth = nowplaying.kick.oauth2.KickOAuth2(config)

    try:
        # Check if we have stored tokens
        access_token, refresh_token = oauth.get_stored_tokens()
        logging.debug(
            "Retrieved stored tokens: access_token=%s, refresh_token=%s",
            "present" if access_token else "missing",
            "present" if refresh_token else "missing",
        )

        if access_token:
            # Validate current token
            logging.debug("Validating stored access token")
            validation = await oauth.validate_token_async(access_token)
            if validation:
                oauth.access_token = access_token
                oauth.refresh_token = refresh_token
                logging.debug("Existing Kick token is valid")
                return True
            logging.debug("Stored access token is invalid")

        if refresh_token:
            # Try to refresh the token
            logging.debug("Attempting to refresh token using refresh_token")
            try:
                token_response = await oauth.refresh_access_token_async(refresh_token)

                # Save the refreshed tokens
                new_access_token = token_response.get("access_token")
                new_refresh_token = token_response.get("refresh_token")
                if new_access_token:
                    config.cparser.setValue("kick/accesstoken", new_access_token)
                    if new_refresh_token:
                        config.cparser.setValue("kick/refreshtoken", new_refresh_token)
                    config.save()
                logging.info("Successfully refreshed Kick OAuth2 tokens")
                return True
            except ValueError as error:
                # Check if it's an invalid_grant error (expired/revoked refresh token)
                if "401" in str(error) and "invalid_grant" in str(error):
                    logging.warning("Kick refresh token is invalid/expired, clearing stored tokens")
                    oauth.clear_stored_tokens()
                    return False
                # Re-raise other ValueError types
                raise
        logging.debug("No refresh_token available")

    except Exception as error:  # pylint: disable=broad-except
        logging.exception("Token refresh failed: %s", error)

    return False


# Token Validation - Dual Implementation for Different Use Cases:
# 1. async version for chat/launch components (non-blocking)
# 2. sync version for UI components (Qt-safe, immediate feedback)
# Both use the same Kick introspect endpoint for consistency


async def validate_kick_token_async(
    config: nowplaying.config.ConfigFile, access_token: str | None = None
) -> dict[str, Any] | None:
    """Async wrapper for token validation (for non-UI components)"""
    oauth = nowplaying.kick.oauth2.KickOAuth2(config)
    return await oauth.validate_token_async(access_token)
