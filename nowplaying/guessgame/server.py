#!/usr/bin/env python3
"""Guess game server communication mixin"""

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp

import nowplaying.utils.charts_api

if TYPE_CHECKING:
    import nowplaying.config


class GuessGameServerMixin:
    """Mixin providing server communication methods for GuessGame."""

    config: "nowplaying.config.ConfigFile | None"
    stopevent: asyncio.Event
    _http_session: aiohttp.ClientSession | None

    def is_enabled(self) -> bool:  # pylint: disable=no-self-use
        """Provided by GuessGame."""
        return False

    async def get_leaderboard(  # pylint: disable=no-self-use,unused-argument
        self, leaderboard_type: str = "session", limit: int = 10
    ) -> list | None:
        """Provided by GuessGame."""
        return None

    async def get_current_state(self) -> dict | None:  # pylint: disable=no-self-use
        """Provided by GuessGame."""
        return None

    async def _serialize_leaderboards(self) -> dict[str, list[dict[str, int | str]]]:
        """
        Fetch and serialize leaderboards for server transmission.

        Returns:
            Dictionary with session_leaderboard and all_time_leaderboard keys
        """
        result: dict[str, list[dict[str, int | str]]] = {}

        session_leaderboard = await self.get_leaderboard("session", limit=10)
        all_time_leaderboard = await self.get_leaderboard("all_time", limit=10)

        if session_leaderboard:
            result["session_leaderboard"] = [
                {
                    "username": entry["username"],
                    "score": entry["score"],
                    "solves": entry["solves"],
                }
                for entry in session_leaderboard
            ]

        if all_time_leaderboard:
            result["all_time_leaderboard"] = [
                {
                    "username": entry["username"],
                    "score": entry["score"],
                    "solves": entry["solves"],
                }
                for entry in all_time_leaderboard
            ]

        return result

    async def _build_server_payload(self, state: dict, charts_key: str) -> dict[str, str | dict]:
        """
        Build payload for server transmission based on game state.

        Args:
            state: Current game state from get_current_state()
            charts_key: Charts API key

        Returns:
            Payload dictionary ready for JSON transmission
        """
        payload: dict[str, str | dict] = {
            "secret": charts_key,
            "game_status": state["status"],
        }

        if state["status"] == "active":
            # For active games, include masked info
            game_state = {
                "masked_track": state.get("masked_track", ""),
                "masked_artist": state.get("masked_artist", ""),
                "time_remaining": state.get("time_remaining", 0),
                "time_elapsed": state.get("time_elapsed", 0),
            }

            # Add leaderboards
            leaderboards = await self._serialize_leaderboards()
            game_state.update(leaderboards)

            payload["game_state"] = game_state

        elif state["status"] in ("solved", "timeout"):
            # For ended games, include revealed answers and final leaderboards
            payload["current_track"] = state.get("revealed_track", "")
            payload["current_artist"] = state.get("revealed_artist", "")

            # Add final leaderboards
            game_state = await self._serialize_leaderboards()
            payload["game_state"] = game_state

        return payload

    async def _send_single_update(  # pylint: disable=too-many-return-statements
        self,
    ) -> tuple[bool, int]:
        """
        Send a single game state update to the server.

        Returns:
            Tuple of (success, sleep_duration):
            - success: True if update was sent, False if skipped
            - sleep_duration: Recommended sleep time in seconds before next update
        """
        # Check if game is enabled
        if not self.is_enabled():
            return (False, 5)

        # Check if sending to server is enabled
        if not self.config:
            logging.debug("Game state sender: no config, sleeping")
            return (False, 5)

        send_to_server = self.config.cparser.value(
            "guessgame/send_to_server", defaultValue=True, type=bool
        )
        if not send_to_server:
            logging.debug("Game state sender: send_to_server disabled, sleeping")
            return (False, 5)

        # Check if charts is configured (need valid API key)
        charts_key = self.config.cparser.value("charts/charts_key", defaultValue="")
        if not nowplaying.utils.charts_api.is_valid_api_key(charts_key):
            # No valid API key configured, skip sending
            logging.debug(
                "Game state sender: no valid charts API key (length=%d), sleeping",
                len(charts_key) if charts_key else 0,
            )
            return (False, 10)

        # Get current game state
        state = await self.get_current_state()
        if not state:
            return (False, 5)

        # Nothing to report while waiting for a game to start
        if state["status"] == "waiting":
            return (False, 10)

        # Build payload using helper
        payload = await self._build_server_payload(state, charts_key)

        base_url = nowplaying.utils.charts_api.get_charts_base_url(self.config)
        url = f"{base_url}/api/guessgame/update"

        # Reuse HTTP session for efficiency
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()

        # Send to server
        # pylint: disable=not-async-context-manager
        async with self._http_session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            # Use shared HTTP response handler
            try:
                response_text = await response.text()
            except Exception:  # pylint: disable=broad-exception-caught
                response_text = ""
            action = nowplaying.utils.charts_api.handle_http_response(
                response.status, response_text
            )

            # Use action to determine sleep duration
            # For auth errors (401/403), pause longer since user needs to fix API key
            if response.status in (401, 403):
                logging.warning(
                    "Authentication failed (status %d). Pausing for 60s. "
                    "Check your Charts API key configuration.",
                    response.status,
                )
                return (False, 60)

            # Log action for other cases
            if action == "drop":
                logging.warning(
                    "Server indicated to drop game state update (status %d)",
                    response.status,
                )
            elif action == "retry":
                logging.debug("Server indicated retry for game state update")

        # Return success and sleep duration based on game state
        # Send more frequently during active games
        sleep_duration = 2 if state["status"] == "active" else 10
        return (True, sleep_duration)

    async def send_game_state_to_server(self):
        """
        Periodically send game state to charts server for live display.

        This task runs continuously while the guess game is enabled and sends:
        - Game status (active/waiting)
        - Current track and artist info
        - Masked strings and revealed letters
        - Time remaining/elapsed
        - Leaderboards (session and all-time)

        Respects the guessgame/send_to_server config option.
        """
        while not self.stopevent.is_set():
            try:
                _, sleep_duration = await self._send_single_update()
                await asyncio.sleep(sleep_duration)
            except asyncio.CancelledError:
                logging.debug("Game state sender task cancelled")
                break
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.error("Failed to send game state to server: %s", error)
                await asyncio.sleep(5)

        # Clean up HTTP session when loop exits
        if self._http_session is not None and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
