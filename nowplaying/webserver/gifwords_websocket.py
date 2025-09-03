#!/usr/bin/env python3
"""Gifwords WebSocket handler"""

import asyncio
import base64
import logging
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web

import nowplaying.trackrequests
import nowplaying.utils

if TYPE_CHECKING:
    import nowplaying.config


class GifwordsWebSocketHandler:
    """Handler for Gifwords WebSocket functionality"""

    def __init__(
        self,
        stopevent: asyncio.Event,
        config_key: web.AppKey["nowplaying.config.ConfigFile"],
    ):
        self.stopevent = stopevent
        self.config_key = config_key

    async def websocket_gifwords_streamer(self, request: web.Request):
        """Handle gifwords WebSocket connection - just waits for broadcasts"""
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)

        # Get session ID from query parameters
        session_id = request.query.get("session_id", "unknown")
        logging.info("Session %s: Gifwords streamer connected from %s", session_id, request.remote)

        # Add to gifwords-specific WebSocket set for broadcasting
        if "gifwords_ws_set" not in request.app:
            request.app["gifwords_ws_set"] = set()
        request.app["gifwords_ws_set"].add(websocket)

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
            logging.debug("Session %s: Gifwords WebSocket error: %s", session_id, error)
        finally:
            request.app["gifwords_ws_set"].discard(websocket)
            if not websocket.closed:
                await websocket.close()
            logging.info("Session %s: Gifwords streamer disconnected", session_id)

        return websocket

    @staticmethod
    async def _broadcast_to_gifwords_sessions(app: web.Application, broadcast_data: dict) -> None:
        """Broadcast data to all connected gifwords WebSocket sessions"""
        gifwords_connections = app.get("gifwords_ws_set", set()).copy()

        if not gifwords_connections:
            logging.debug("No gifwords sessions connected, discarding image")
            return

        logging.info("Broadcasting gifwords to %d sessions", len(gifwords_connections))

        disconnected_sockets = set()
        for websocket in gifwords_connections:
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
            app.get("gifwords_ws_set", set()).discard(websocket)

    async def gifwords_broadcast_task(self, app: web.Application):
        """Background task to poll for gifwords and broadcast to all connected sessions"""
        logging.info("Starting gifwords broadcast task")
        trackrequest = nowplaying.trackrequests.Requests(app[self.config_key])

        try:
            while not nowplaying.utils.safe_stopevent_check(self.stopevent):
                # Check for new gifwords
                metadata = await trackrequest.check_for_gifwords()

                if metadata.get("image"):
                    broadcast_data = {
                        "requester": metadata.get("requester"),
                        "keywords": metadata.get("keywords"),
                        "imagebase64": base64.b64encode(metadata["image"]).decode("utf-8"),
                    }
                    await self._broadcast_to_gifwords_sessions(app, broadcast_data)

                await asyncio.sleep(5)  # Check every 5 seconds

        except asyncio.CancelledError:
            logging.info("Gifwords broadcast task cancelled")
            raise
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Gifwords broadcast task error: %s", error)
