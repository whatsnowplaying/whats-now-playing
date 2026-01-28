#!/usr/bin/env python3
"""Guess game WebSocket handler"""

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web

import nowplaying.guessgame
import nowplaying.utils

if TYPE_CHECKING:
    import nowplaying.config


class GuessgameWebSocketHandler:
    """Handler for guess game WebSocket functionality"""

    def __init__(
        self,
        stopevent: asyncio.Event,
        config_key: web.AppKey["nowplaying.config.ConfigFile"],
    ):
        self.stopevent = stopevent
        self.config_key = config_key

    async def websocket_guessgame_streamer(self, request: web.Request):
        """Handle guess game WebSocket connection - just waits for broadcasts"""
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)

        # Get session ID from query parameters
        session_id = request.query.get("session_id", "unknown")
        logging.info(
            "Session %s: Guess game streamer connected from %s", session_id, request.remote
        )

        # Add to guessgame-specific WebSocket set for broadcasting
        if "guessgame_ws_set" not in request.app:
            request.app["guessgame_ws_set"] = set()
        request.app["guessgame_ws_set"].add(websocket)

        try:
            # Keep the connection alive - all updates come via broadcast
            while (
                not nowplaying.utils.safe_stopevent_check(self.stopevent) and not websocket.closed
            ):
                try:
                    # Wait for messages (mainly to detect disconnection)
                    msg = await asyncio.wait_for(websocket.receive(), timeout=30.0)
                    if msg.type == aiohttp.WSMsgType.CLOSE:
                        break

                    if msg.type == aiohttp.WSMsgType.ERROR:
                        logging.debug(
                            "Session %s: WebSocket error in message: %s",
                            session_id,
                            websocket.exception(),
                        )
                        break
                except TimeoutError:
                    # Timeout is normal - just means no messages received
                    continue
                except Exception as error:  # pylint: disable=broad-except
                    logging.debug(
                        "Session %s: Error receiving WebSocket message: %s", session_id, error
                    )
                    break

        except Exception as error:  # pylint: disable=broad-except
            logging.debug("Session %s: Guess game WebSocket error: %s", session_id, error)
        finally:
            request.app["guessgame_ws_set"].discard(websocket)
            if not websocket.closed:
                await websocket.close()
            logging.info("Session %s: Guess game streamer disconnected", session_id)

        return websocket

    @staticmethod
    async def _broadcast_to_guessgame_sessions(app: web.Application, broadcast_data: dict) -> None:
        """Broadcast data to all connected guess game WebSocket sessions"""
        guessgame_connections = app.get("guessgame_ws_set", set()).copy()

        if not guessgame_connections:
            return

        disconnected_sockets = set()
        for websocket in guessgame_connections:
            if websocket.closed:
                disconnected_sockets.add(websocket)
                continue

            try:
                await websocket.send_json(broadcast_data)
            except Exception as send_error:  # pylint: disable=broad-except
                logging.debug("Failed to send to WebSocket: %s", send_error)
                disconnected_sockets.add(websocket)

        # Clean up disconnected sockets
        for websocket in disconnected_sockets:
            app.get("guessgame_ws_set", set()).discard(websocket)

    async def guessgame_broadcast_task(self, app: web.Application):
        """Background task to poll guess game state and broadcast to all connected sessions"""
        logging.info("Starting guess game broadcast task")
        guessgame = nowplaying.guessgame.GuessGame(app[self.config_key])

        try:
            while not nowplaying.utils.safe_stopevent_check(self.stopevent):
                # Get current game state
                game_state = await guessgame.get_current_state()

                # Only broadcast if there's an active game or a recently ended game
                if game_state and game_state.get("status") != "waiting":
                    # Get leaderboard size from config
                    config = app[self.config_key]
                    leaderboard_size = config.cparser.value(
                        "guessgame/leaderboard_size", type=int, defaultValue=10
                    )

                    # Get leaderboards
                    session_leaderboard = await guessgame.get_leaderboard(
                        leaderboard_type="session", limit=leaderboard_size
                    )
                    all_time_leaderboard = await guessgame.get_leaderboard(
                        leaderboard_type="all_time", limit=leaderboard_size
                    )

                    # Build broadcast data
                    broadcast_data = {
                        **game_state,  # Include all game state fields
                        "session_leaderboard": session_leaderboard or [],
                        "all_time_leaderboard": all_time_leaderboard or [],
                    }

                    await self._broadcast_to_guessgame_sessions(app, broadcast_data)

                await asyncio.sleep(5)  # Check every 5 seconds

        except asyncio.CancelledError:
            logging.info("Guess game broadcast task cancelled")
            raise
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Guess game broadcast task error: %s", error)
