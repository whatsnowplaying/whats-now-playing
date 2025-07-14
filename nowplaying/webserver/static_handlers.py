#!/usr/bin/env python3
"""Static content handlers for webserver"""

import base64
import logging
import os
import secrets
from typing import TYPE_CHECKING

from aiohttp import web

import nowplaying.db
import nowplaying.hostmeta
import nowplaying.utils
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    import nowplaying.config

# Import constants from main webserver module
INDEXREFRESH = (
    '<!doctype html><html lang="en">'
    '<head><meta http-equiv="refresh" content="5" ></head>'
    "<body></body></html>\n"
)


class StaticContentHandler:
    """Handler for static content endpoints"""

    def __init__(
        self,
        config_key: web.AppKey["nowplaying.config.ConfigFile"],
        metadb_key: web.AppKey["nowplaying.db.MetadataDB"],
        remotedb_key: web.AppKey[nowplaying.db.MetadataDB],
    ):
        self.config_key = config_key
        self.metadb_key = metadb_key
        self.remotedb_key = remotedb_key

    async def index_htm_handler(self, request: web.Request):
        """handle web output"""
        return await self._metacheck_htm_handler(request, "weboutput/htmltemplate")

    async def artistbanner_htm_handler(self, request: web.Request):
        """handle web output"""
        return await self._metacheck_htm_handler(request, "weboutput/artistbannertemplate")

    async def artistlogo_htm_handler(self, request: web.Request):
        """handle web output"""
        return await self._metacheck_htm_handler(request, "weboutput/artistlogotemplate")

    async def artistthumbnail_htm_handler(self, request: web.Request):
        """handle web output"""
        return await self._metacheck_htm_handler(request, "weboutput/artistthumbnailtemplate")

    async def artistfanartlaunch_htm_handler(self, request: web.Request):
        """handle web output"""
        return await self._metacheck_htm_handler(request, "weboutput/artistfanarttemplate")

    async def gifwords_launch_htm_handler(self, request: web.Request):
        """handle gifwords output"""
        request.app[self.config_key].cparser.sync()
        htmloutput = await self._htm_handler(
            request, request.app[self.config_key].cparser.value("weboutput/gifwordstemplate")
        )
        return web.Response(content_type="text/html", text=htmloutput)

    async def requesterlaunch_htm_handler(self, request: web.Request):
        """handle web output"""
        return await self._metacheck_htm_handler(request, "weboutput/requestertemplate")

    async def _htm_handler(
        self, request: web.Request, template: str, metadata: TrackMetadata | None = None
    ):
        """handle static html files"""
        htmloutput = INDEXREFRESH
        try:
            if not metadata:
                metadata = await request.app[self.metadb_key].read_last_meta_async()
            if not metadata:
                metadata = nowplaying.hostmeta.gethostmeta()
                metadata["httpport"] = request.app[self.config_key].cparser.value(
                    "weboutput/httpport", type=int
                )
            templatehandler = nowplaying.utils.TemplateHandler(filename=template)
            htmloutput = templatehandler.generate(metadata)
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.exception("_htm_handler: %s", err)
        return htmloutput

    async def _metacheck_htm_handler(self, request: web.Request, cfgtemplate: str):
        """handle static html files after checking metadata"""
        request.app[self.config_key].cparser.sync()
        template = request.app[self.config_key].cparser.value(cfgtemplate)
        source = os.path.basename(template)
        htmloutput = ""
        request.app[self.config_key].get()
        metadata = await request.app[self.metadb_key].read_last_meta_async()
        lastid = await self.getlastid(request, source)
        once = request.app[self.config_key].cparser.value("weboutput/once", type=bool)

        # | dbid  |  lastid | once |
        # |   x   |   NA    |      |  -> update lastid, send template
        # |   x   |  diff   |   NA |  -> update lastid, send template
        # |   x   |  same   |      |  -> send template
        # |   x   |  same   |   x  |  -> send refresh
        # |       |   NA    |      |  -> send refresh because not ready or something broke

        if not metadata or not metadata.get("dbid") or not template:
            return web.Response(status=202, content_type="text/html", text=INDEXREFRESH)

        if lastid == 0 or lastid != metadata["dbid"] or not once:
            await self.setlastid(request, metadata["dbid"], source)
            htmloutput = await self._htm_handler(request, template, metadata=metadata)
            return web.Response(content_type="text/html", text=htmloutput)

        return web.Response(content_type="text/html", text=INDEXREFRESH)

    @staticmethod
    async def setlastid(request: web.Request, lastid: int, source: str):
        """get the lastid sent by http/html"""
        await request.app["statedb"].execute(
            "INSERT OR REPLACE INTO lastprocessed(lastid, source) VALUES (?,?) ", [lastid, source]
        )
        await request.app["statedb"].commit()

    @staticmethod
    async def getlastid(request: web.Request, source: str):
        """get the lastid sent by http/html"""
        cursor = await request.app["statedb"].execute(
            f'SELECT lastid FROM lastprocessed WHERE source="{source}"'
        )
        row = await cursor.fetchone()
        if not row:
            lastid = 0
        else:
            lastid = row[0]
        await cursor.close()
        return lastid

    async def indextxt_handler(self, request: web.Request):
        """handle static index.txt"""
        metadata = await request.app[self.metadb_key].read_last_meta_async()
        txtoutput = ""
        if metadata:
            request.app[self.config_key].get()
            try:
                templatehandler = nowplaying.utils.TemplateHandler(
                    filename=request.app[self.config_key].cparser.value("textoutput/txttemplate")
                )
                txtoutput = templatehandler.generate(metadata)
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.error("indextxt_handler: %s", error)
                txtoutput = ""
        return web.Response(text=txtoutput)

    async def favicon_handler(self, request: web.Request):
        """handle favicon.ico"""
        return web.FileResponse(path=request.app[self.config_key].iconfile)

    async def _image_handler(self, imgtype: str, request: web.Request):
        """handle an image"""

        # rather than return an error, just send a transparent PNG
        # this makes the client code significantly easier
        image = nowplaying.utils.TRANSPARENT_PNG_BIN
        try:
            metadata = await request.app[self.metadb_key].read_last_meta_async()
            if metadata and metadata.get(imgtype):
                image = metadata[imgtype]
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.exception("_image_handler: %s", err)
        return web.Response(content_type="image/png", body=image)

    async def cover_handler(self, request: web.Request):
        """handle cover image"""
        return await self._image_handler("coverimageraw", request)

    async def artistbanner_handler(self, request: web.Request):
        """handle artist banner image"""
        return await self._image_handler("artistbannerraw", request)

    async def artistlogo_handler(self, request: web.Request):
        """handle artist logo image"""
        return await self._image_handler("artistlogoraw", request)

    async def artistthumbnail_handler(self, request: web.Request):
        """handle artist logo image"""
        return await self._image_handler("artistthumbnailraw", request)

    @staticmethod
    def _base64ifier(metadata: TrackMetadata) -> TrackMetadata:
        """convert blob data to base64"""
        for key in nowplaying.db.METADATABLOBLIST:
            if key in metadata and metadata[key]:
                metadata[key] = base64.b64encode(metadata[key]).decode("utf-8")
        return metadata

    async def api_v1_last_handler(self, request: web.Request):
        """v1/last just returns the metadata"""
        data = {}
        if metadata := await request.app[self.metadb_key].read_last_meta_async():
            try:
                del metadata["dbid"]
                data = self._base64ifier(metadata)
            except Exception as err:  # pylint: disable=broad-exception-caught
                logging.exception("api_v1_last_handler: %s", err)
        return web.json_response(data)

    async def api_v1_remoteinput_handler(self, request: web.Request):
        """POST: receive metadata from remote source and store in remote database"""
        # Only allow POST requests
        if request.method != "POST":
            return web.json_response({"error": "Method not allowed"}, status=405)

        try:
            # Parse JSON request body
            request_data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "Invalid JSON in request body"}, status=400)

        # Refresh config to get latest settings (important for testing)
        request.app[self.config_key].get()
        if required_secret := request.app[self.config_key].cparser.value(
            "remote/remote_key", type=str, defaultValue=""
        ):
            provided_secret = request_data.get("secret", "")
            if not provided_secret:
                logging.warning("Remote metadata submission without secret from %s", request.remote)
                return web.json_response({"error": "Missing secret in request"}, status=403)

            # Use constant-time comparison to prevent timing attacks
            if not secrets.compare_digest(required_secret, provided_secret):
                logging.warning(
                    "Remote metadata submission with invalid secret from %s", request.remote
                )
                return web.json_response({"error": "Invalid secret"}, status=403)

        # Remove secret from metadata before storing
        metadata = request_data.copy()
        metadata.pop("secret", "")

        logging.info("Got metadata from %s", request.host)
        # Store metadata in remote database
        try:
            await request.app[self.remotedb_key].write_to_metadb(metadata=metadata)
            # Re-read to get the dbid
            last_meta = await request.app[self.remotedb_key].read_last_meta_async()
            dbid = last_meta.get("dbid") if last_meta else None
            return web.json_response({"dbid": dbid})
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.error("Failed to store metadata in remote database: %s", exc)
            return web.json_response({"error": "Failed to store metadata"}, status=500)
