#!/usr/bin/env python3
"""aiohttp handlers for the Lumia song-request queue API"""

import asyncio
import secrets
from typing import TYPE_CHECKING

from aiohttp import web

import nowplaying.trackrequests

if TYPE_CHECKING:
    import nowplaying.config


class RequestsHandler:
    """REST handlers exposing the request queue to external song-request sources (Lumia)"""

    def __init__(self, config_key: "web.AppKey[nowplaying.config.ConfigFile]"):
        self.config_key = config_key

    def _requests(self, request: web.Request) -> "nowplaying.trackrequests.Requests":
        return nowplaying.trackrequests.Requests(request.app[self.config_key])

    def _authorized(self, request: web.Request, provided_secret: str) -> bool:
        """reuse the webserver's shared secret (empty key disables auth)"""
        request.app[self.config_key].get()
        required = request.app[self.config_key].cparser.value(
            "remote/remote_key", type=str, defaultValue=""
        )
        if not required:
            return True
        return bool(provided_secret) and secrets.compare_digest(required, provided_secret)

    def _requests_enabled(self, request: web.Request) -> bool:
        return request.app[self.config_key].cparser.value("settings/requests", type=bool)

    async def post_requests_handler(self, request: web.Request) -> web.Response:
        """POST /v1/requests — enqueue a request handed off from Lumia"""
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "Invalid JSON in request body"}, status=400)
        if not self._authorized(request, str(body.get("secret", ""))):
            return web.json_response({"error": "Invalid or missing secret"}, status=403)
        if not self._requests_enabled(request):
            return web.json_response({"error": "Requests are disabled"}, status=403)
        requester = body.get("requester")
        if not requester:
            return web.json_response({"error": "requester is required"}, status=400)
        result = await self._requests(request).enqueue_request(
            requester=requester,
            request_origin="lumia",
            user_platform=body.get("user_platform"),
            query=body.get("query"),
            artist=body.get("artist"),
            title=body.get("title"),
        )
        if not result.get("accepted"):
            return web.json_response(result, status=400)
        return web.json_response(result)

    async def get_requests_handler(self, request: web.Request) -> web.Response:
        """GET /v1/requests — the current queue snapshot for Lumia to mirror"""
        if not self._authorized(request, request.query.get("secret", "")):
            return web.json_response({"error": "Invalid or missing secret"}, status=403)
        if not self._requests_enabled(request):
            return web.json_response({"requests": []})
        reqs = self._requests(request)
        items = []
        async for row in reqs.get_all_generator():
            items.append(
                {
                    "request_id": row.get("reqid"),
                    "track_id": nowplaying.trackrequests.Requests.track_id(
                        row.get("artist"), row.get("title")
                    ),
                    "artist": row.get("artist"),
                    "title": row.get("title"),
                    "requester": row.get("username"),
                    "user_platform": row.get("user_platform"),
                    "request_origin": row.get("request_origin"),
                    "timestamp": row.get("timestamp"),
                }
            )
        return web.json_response({"requests": items})

    async def delete_request_handler(self, request: web.Request) -> web.Response:
        """DELETE /v1/requests/{reqid} — remove a single queue entry"""
        if not self._authorized(request, request.query.get("secret", "")):
            return web.json_response({"error": "Invalid or missing secret"}, status=403)
        if not self._requests_enabled(request):
            return web.json_response({"error": "Requests are disabled"}, status=403)
        try:
            reqid = int(request.match_info.get("reqid", ""))
        except ValueError:
            return web.json_response({"error": "invalid request id"}, status=400)
        await asyncio.to_thread(self._requests(request).erase_id, reqid)
        return web.json_response({"deleted": reqid})

    async def clear_requests_handler(self, request: web.Request) -> web.Response:
        """DELETE /v1/requests — clear the queue, or one request when artist/title given"""
        if not self._authorized(request, request.query.get("secret", "")):
            return web.json_response({"error": "Invalid or missing secret"}, status=403)
        if not self._requests_enabled(request):
            return web.json_response({"error": "Requests are disabled"}, status=403)
        artist = request.query.get("artist", "")
        title = request.query.get("title", "")
        requester = request.query.get("requester", "")
        if artist and title:
            deleted = await self._requests(request).erase_by_identity(artist, title, requester)
            return web.json_response({"deleted": deleted})
        if artist or title or requester:
            # partial identity is ambiguous — don't guess, and don't fall through to clear-all
            return web.json_response(
                {"error": "artist and title are both required to delete a single request"},
                status=400,
            )
        await self._requests(request).erase_all()
        return web.json_response({"cleared": True})
