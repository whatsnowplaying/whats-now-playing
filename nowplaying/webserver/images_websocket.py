#!/usr/bin/env python3
"""Images WebSocket API handler"""

import asyncio
import base64
import json
import logging
import secrets
import weakref
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web

import nowplaying.utils
import nowplaying.version  # pylint: disable=no-name-in-module, import-error

if TYPE_CHECKING:
    import nowplaying.config
    import nowplaying.db
    import nowplaying.imagecache
    import nowplaying.metadata


class ImagesWebSocketHandler:  # pylint: disable=too-few-public-methods
    """Handler for Images WebSocket API"""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        stopevent: asyncio.Event,
        ws_key: web.AppKey[weakref.WeakSet],
        ic_key: web.AppKey["nowplaying.imagecache.ImageCache"],
        metadb_key: web.AppKey["nowplaying.db.MetadataDB"],
        config_key: web.AppKey["nowplaying.config.ConfigFile"],
        metadata_key: web.AppKey["nowplaying.metadata.MetadataProcessors"],
    ):
        self.stopevent = stopevent
        self.ws_key = ws_key
        self.ic_key = ic_key
        self.metadb_key = metadb_key
        self.config_key = config_key
        self.metadata_key = metadata_key

    async def websocket_images_handler(self, request: web.Request):  # pylint: disable=too-many-branches
        """handle Images WebSocket API"""
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app[self.ws_key].add(websocket)

        try:
            async for msg in websocket:
                if websocket.closed:
                    break

                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if not isinstance(data, dict):
                        await self._send_images_error(
                            websocket, "BAD_STRUCTURE", "request was not understood"
                        )
                        raise ValueError

                    msg_type = data.get("type")
                    if not isinstance(msg_type, str):
                        await self._send_images_error(
                            websocket, "BAD_STRUCTURE", "request was not understood"
                        )
                        raise ValueError

                    if msg_type == "hello":
                        await self._handle_images_hello(websocket, data, request)
                    elif msg_type == "get_images":
                        await self._handle_images_get_images(websocket, data, request)
                    elif msg_type == "list_images":
                        await self._handle_images_list_images(websocket, data, request)
                    else:
                        await self._send_images_error(
                            websocket, "UNKNOWN_MESSAGE_TYPE", f"Unknown message type: {msg_type}"
                        )

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logging.error(
                        "Images WebSocket connection closed with exception %s",
                        websocket.exception(),
                    )

        except json.JSONDecodeError:
            await self._send_images_error(websocket, "INVALID_JSON", "Invalid JSON in message")
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Images WebSocket handler error: %s", error)
        finally:
            request.app[self.ws_key].discard(websocket)

        return websocket

    async def _handle_images_hello(
        self, websocket: web.WebSocketResponse, data: dict, request: web.Request
    ):
        """handle hello message"""

        # Refresh config to get latest settings (important for testing)
        request.app[self.config_key].get()
        if required_secret := request.app[self.config_key].cparser.value(
            "remote/remote_key", type=str, defaultValue=""
        ):
            provided_secret = data.get("secret", "")
            if not provided_secret:
                logging.warning("Remote metadata submission without secret from %s", request.remote)
                return web.json_response({"error": "Missing secret in request"}, status=403)

            # Use constant-time comparison to prevent timing attacks
            if not secrets.compare_digest(required_secret, provided_secret):
                logging.warning(
                    "Remote metadata submission with invalid secret from %s", request.remote
                )
                return web.json_response({"error": "Invalid secret"}, status=403)

        await websocket.send_json(
            {
                "type": "welcome",
                "server": "whats-now-playing",
                "version": nowplaying.version.__VERSION__,  # pylint: disable=no-member
                "status": "ready",
            }
        )

    async def _handle_images_get_images(
        self, websocket: web.WebSocketResponse, data: dict, request: web.Request
    ):
        """handle flexible get_images message"""
        data_type = data.get("data_type")
        category = data.get("category")
        parameters = data.get("parameters", {})

        if not await self._validate_required_string(
            websocket, category, "category", "MISSING_CATEGORY"
        ):
            return

        if not await self._validate_required_string(
            websocket, data_type, "datatype", "MISSING_DATATYPE"
        ):
            return

        if not isinstance(parameters, dict):
            await self._send_images_error(websocket, "MISSING_PARAMETERS", "parameters are required")
            return

        if data_type == "artist":
            await self._handle_artist_images(websocket, category, parameters, request)
        elif data_type == "album":
            await self._handle_album_images(websocket, category, parameters, request)
        else:
            await self._send_images_error(
                websocket, "UNSUPPORTED_DATA_TYPE", f'Data type "{data_type}" not supported'
            )

    async def _handle_artist_images(
        self,
        websocket: web.WebSocketResponse,
        category: str,
        parameters: dict,
        request: web.Request,
    ):
        """handle artist image requests"""
        artist = parameters.get("artist")
        if not await self._validate_required_string(websocket, artist, "artist", "MISSING_ARTIST"):
            return

        imagetype = self._get_imagetype_for_category(category)
        if not imagetype:
            await self._send_images_error(
                websocket,
                "UNSUPPORTED_CATEGORY",
                f'Category "{category}" not supported for artists',
            )
            return

        try:
            imagecache = request.app[self.ic_key]
            normalized_artist = self._get_normalized_artist(artist)

            if image_data := imagecache.random_image_fetch(
                identifier=normalized_artist, imagetype=imagetype
            ):
                image_b64 = base64.b64encode(image_data).decode("utf-8")
                await self._send_json_response(
                    websocket,
                    "image_data",
                    data_type="artist",
                    category=category,
                    artist=artist,
                    image_data=image_b64,
                )
            else:
                await self._send_json_response(
                    websocket,
                    "no_image",
                    data_type="artist",
                    category=category,
                    artist=artist,
                    message=f"No {category} images found for {artist}",
                )

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Error getting %s images for artist %s: %s", category, artist, error)
            await self._send_images_error(websocket, "SERVER_ERROR", "Failed to get images")

    async def _handle_album_images(
        self,
        websocket: web.WebSocketResponse,
        category: str,
        parameters: dict,
        request: web.Request,
    ):
        """handle album image requests"""
        artist = parameters.get("artist")
        album = parameters.get("album")

        if not await self._validate_required_string(websocket, artist, "artist", "MISSING_ARTIST"):
            return

        if not await self._validate_required_string(websocket, album, "album", "MISSING_ALBUM"):
            return

        try:
            if category != "cover":
                await self._send_images_error(
                    websocket,
                    "UNSUPPORTED_CATEGORY",
                    f'Category "{category}" not supported for albums',
                )
                return

            # Create identifier matching the format used in metadata.py
            identifier = f"{artist}_{album}"
            imagecache = request.app[self.ic_key]

            if image_data := imagecache.random_image_fetch(
                identifier=identifier, imagetype="front_cover"
            ):
                image_b64 = base64.b64encode(image_data).decode("utf-8")
                await self._send_json_response(
                    websocket,
                    "image_data",
                    data_type="album",
                    category=category,
                    artist=artist,
                    album=album,
                    image_data=image_b64,
                )
            else:
                await self._send_json_response(
                    websocket,
                    "no_image",
                    data_type="album",
                    category=category,
                    artist=artist,
                    album=album,
                    message=f'No cover images found for "{album}" by {artist}',
                )

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error(
                "Error getting %s images for album %s by %s: %s", category, album, artist, error
            )
            await self._send_images_error(websocket, "SERVER_ERROR", "Failed to get images")

    async def _handle_images_list_images(
        self, websocket: web.WebSocketResponse, data: dict, request: web.Request
    ):
        """handle list_images message to get available image cache keys"""
        # Validate common parameters
        if not await self._validate_common_params(websocket, data):
            return

        data_type = data["data_type"]
        category = data["category"]
        parameters = data["parameters"]

        if data_type == "artist":
            await self._list_artist_images(websocket, category, parameters, request)
        elif data_type == "album":
            await self._list_album_images(websocket, category, parameters, request)
        else:
            await self._send_images_error(
                websocket,
                "UNSUPPORTED_DATA_TYPE",
                f'Data type "{data_type}" not supported for listing',
            )

    async def _list_artist_images(
        self,
        websocket: web.WebSocketResponse,
        category: str,
        parameters: dict,
        request: web.Request,
    ):
        """handle listing artist images"""
        artist = parameters.get("artist")
        if not await self._validate_required_string(websocket, artist, "artist", "MISSING_ARTIST"):
            return

        imagetype = self._get_imagetype_for_category(category)
        if not imagetype:
            await self._send_images_error(
                websocket,
                "UNSUPPORTED_CATEGORY",
                f'Category "{category}" not supported for artists',
            )
            return

        try:
            imagecache = request.app[self.ic_key]
            normalized_artist = self._get_normalized_artist(artist)
            cache_keys = imagecache.get_cache_keys_for_identifier(normalized_artist, imagetype)

            await self._send_image_list_response(
                websocket, "artist", category, cache_keys, artist=artist
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Error listing %s images for artist %s: %s", category, artist, error)
            await self._send_images_error(websocket, "SERVER_ERROR", "Failed to list images")

    async def _list_album_images(
        self,
        websocket: web.WebSocketResponse,
        category: str,
        parameters: dict,
        request: web.Request,
    ):
        """handle listing album images"""
        artist = parameters.get("artist")
        album = parameters.get("album")

        if not await self._validate_required_string(websocket, artist, "artist", "MISSING_ARTIST"):
            return

        if not await self._validate_required_string(websocket, album, "album", "MISSING_ALBUM"):
            return

        if category != "cover":
            await self._send_images_error(
                websocket, "UNSUPPORTED_CATEGORY", f'Category "{category}" not supported for albums'
            )
            return

        try:
            imagecache = request.app[self.ic_key]
            identifier = f"{artist}_{album}"
            cache_keys = imagecache.get_cache_keys_for_identifier(identifier, "front_cover")

            await self._send_image_list_response(
                websocket, "album", category, cache_keys, artist=artist, album=album
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error(
                "Error listing %s images for album %s by %s: %s", category, album, artist, error
            )
            await self._send_images_error(websocket, "SERVER_ERROR", "Failed to list images")

    async def _validate_common_params(self, websocket: web.WebSocketResponse, data: dict) -> bool:
        """validate common parameters for list_images requests"""
        data_type = data.get("data_type")
        category = data.get("category")
        parameters = data.get("parameters", {})

        if not await self._validate_required_string(
            websocket, data_type, "datatype", "MISSING_DATATYPE"
        ):
            return False

        if not await self._validate_required_string(
            websocket, category, "category", "MISSING_CATEGORY"
        ):
            return False

        if not isinstance(parameters, dict):
            await self._send_images_error(websocket, "MISSING_PARAMTERS", "parameters are required")
            return False

        return True

    @staticmethod
    async def _send_image_list_response(
        websocket: web.WebSocketResponse,
        data_type: str,
        category: str,
        cache_keys: list[str],
        **kwargs,
    ):
        """send standardized image list response"""
        response = {
            "type": "image_list",
            "data_type": data_type,
            "category": category,
            "cache_keys": cache_keys,
            "total": len(cache_keys),
        } | kwargs
        await websocket.send_json(response)

    @staticmethod
    def _get_imagetype_for_category(category: str) -> str | None:
        """map category to imagetype"""
        imagetype_map = {
            "fanart": "artistfanart",
            "banner": "artistbanner",
            "logo": "artistlogo",
            "thumbnail": "artistthumbnail",
        }
        return imagetype_map.get(category)

    @staticmethod
    async def _send_images_error(websocket: web.WebSocketResponse, error_code: str, message: str):
        """send error message to images API client"""
        try:
            await websocket.send_json(
                {"type": "error", "error_code": error_code, "message": message}
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to send error message: %s", error)

    # Consolidated helper methods to reduce duplication

    async def _validate_required_string(
        self, websocket: web.WebSocketResponse, value, field_name: str, error_code: str
    ) -> bool:
        """validate that a required string parameter is present and valid"""
        if not value or not isinstance(value, str):
            await self._send_images_error(websocket, error_code, f"{field_name} is required")
            return False
        return True

    @staticmethod
    def _get_normalized_artist(artist: str) -> str:
        """get normalized artist name for cache lookup"""
        return nowplaying.utils.normalize(artist, sizecheck=0, nospaces=True) or artist

    @staticmethod
    async def _send_json_response(websocket: web.WebSocketResponse, response_type: str, **fields):
        """send standardized JSON response"""
        response = {"type": response_type} | fields
        await websocket.send_json(response)
