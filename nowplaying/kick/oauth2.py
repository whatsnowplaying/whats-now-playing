#!/usr/bin/env python3
"""Kick OAuth2 authentication handler"""

import asyncio
import logging
from typing import Any

import aiohttp
import requests

import nowplaying.config
import nowplaying.kick.constants
import nowplaying.oauth2
import nowplaying.utils


class KickOAuth2(nowplaying.oauth2.OAuth2Client):
    """Handle Kick.com OAuth 2.1 authentication flow with PKCE"""

    def __init__(self, config: nowplaying.config.ConfigFile | None = None) -> None:
        super().__init__(config, nowplaying.kick.constants.KICK_SERVICE_CONFIG)

    async def validate_token_async(self, token: str | None = None) -> dict[str, Any] | None:
        """Async validate Kick OAuth token using Kick's introspection endpoint"""
        if not token:
            token = self.access_token or self.config.cparser.value("kick/accesstoken")

        if not token:
            return None

        # Use Kick's token introspect endpoint (different from generic OAuth2)
        url = nowplaying.kick.constants.TOKEN_INTROSPECT_ENDPOINT
        headers = {"Authorization": f"Bearer {token}"}

        connector = nowplaying.utils.create_http_connector()
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status == 200:
                    validation_response = await response.json()
                    data = validation_response.get("data", {})

                    # Check if token is active
                    if data.get("active"):
                        logging.debug(
                            "Kick token valid - client: %s, type: %s, scopes: %s",
                            data.get("client_id", "Unknown"),
                            data.get("token_type", "Unknown"),
                            data.get("scope", "Unknown"),
                        )
                        return data
                    logging.debug("Kick token is inactive")
                else:
                    logging.warning("Kick token validation returned status %s", response.status)

                return None

    @staticmethod
    def validate_token_sync(token: str | None) -> bool:
        """Synchronously validate Kick OAuth token"""
        if not token:
            return False

        # Use Kick's token introspect endpoint
        url = nowplaying.kick.constants.TOKEN_INTROSPECT_ENDPOINT
        headers = {"Authorization": f"Bearer {token}"}

        try:
            req = requests.post(url, headers=headers, timeout=10)
        except (requests.ConnectionError, requests.Timeout) as error:
            logging.warning(
                "Kick token validation network error (token status unknown): %s", error
            )
            return False
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Kick token validation unexpected error: %s", error)
            return False

        if req.status_code != 200:
            if req.status_code == 401:
                logging.debug("Kick token is invalid/expired")
            else:
                logging.warning("Kick token validation returned status %s", req.status_code)
            return False

        try:
            response_data = req.json()
            data = response_data.get("data", {})

            # Check if token is active
            if data.get("active"):
                client_id = data.get("client_id", "Unknown")
                scopes = data.get("scope", "Unknown")
                token_type = data.get("token_type", "Unknown")
                logging.debug(
                    "Kick token valid - client: %s, type: %s, scopes: %s",
                    client_id,
                    token_type,
                    scopes,
                )
                return True

            logging.debug("Kick token is inactive")
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Kick token validation/bad json: %s", error)
        return False

    async def revoke_token(self, token: str | None = None) -> None:
        """Revoke an access or refresh token using Kick's endpoint"""
        if not token:
            token = self.access_token or self.config.cparser.value(
                f"{self.config_prefix}/accesstoken"
            )

        if not token:
            logging.warning("No token to revoke")
            return

        # Use Kick's revoke endpoint with query parameters
        revoke_url = f"{self.oauth_host}/oauth/revoke"
        params = {"token": token, "token_hint_type": "access_token"}

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        connector = nowplaying.utils.create_http_connector()
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                revoke_url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    logging.info("Successfully revoked %s OAuth2 token", self.config_prefix)

                    # Clear tokens from config
                    if self.config:
                        self.config.cparser.remove(f"{self.config_prefix}/accesstoken")
                        self.config.cparser.remove(f"{self.config_prefix}/refreshtoken")
                        self.config.save()

                    self.access_token = None
                    self.refresh_token = None
                else:
                    error_text = await response.text()
                    logging.error("Failed to revoke token: %s - %s", response.status, error_text)


async def main() -> None:
    """Example usage of KickOAuth2"""
    # Initialize with config (will read kick/clientid, kick/secret from config)
    oauth = KickOAuth2()

    # Check if configuration is present
    if not oauth.client_id:
        print("Error: kick/clientid not configured")
        return
    if not oauth.client_secret:
        print("Error: kick/secret not configured")
        return

    # Set redirect URI dynamically (required for authorization)
    oauth.redirect_uri = "http://localhost:8899/kickredirect"

    # Step 1: Open browser for authorization
    if oauth.open_browser_for_auth():
        print(
            "Please authorize the application and check the redirect URI "
            "for the authorization code."
        )
        print("The redirect URI should be:", oauth.redirect_uri)

        # In a real application, you would capture the authorization code from the redirect
        # For this example, we'll just print the auth URL
        auth_url = oauth.get_authorization_url()
        print(f"Authorization URL: {auth_url}")
    else:
        print("Failed to open browser for authorization")


if __name__ == "__main__":
    asyncio.run(main())
