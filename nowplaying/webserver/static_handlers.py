#!/usr/bin/env python3
"""Static content handlers for webserver"""

import asyncio
import base64
import logging
import os
import secrets
import uuid
from typing import TYPE_CHECKING

from aiohttp import web

import nowplaying.db
import nowplaying.hostmeta
import nowplaying.utils
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    import nowplaying.config
    import nowplaying.imagecache
    import nowplaying.metadata

# Import constants from main webserver module
INDEXREFRESH = (
    '<!doctype html><html lang="en">'
    '<head><meta http-equiv="refresh" content="5" ></head>'
    "<body></body></html>\n"
)
MAX_FIELD_LENGTH = 1000


def validate_field_lengths(
    metadata: dict, source_description: str = "unknown"
) -> tuple[dict, list[str]]:
    """
    Validate and truncate string fields that exceed MAX_FIELD_LENGTH.

    Args:
        metadata: Dictionary of metadata fields to validate
        source_description: Description of the source for logging purposes

    Returns:
        Tuple of (validated_metadata, list_of_truncation_warnings)
    """
    validated_metadata = metadata.copy()
    warnings = []

    for key, value in validated_metadata.items():
        if isinstance(value, str) and len(value) > MAX_FIELD_LENGTH:
            validated_metadata[key] = value[:MAX_FIELD_LENGTH]
            warning_msg = (
                f"Field '{key}' truncated from {len(value)} to {MAX_FIELD_LENGTH} characters"
            )
            warnings.append(warning_msg)
            logging.warning(
                "Truncated oversized field '%s' from %s (was %d chars, now %d)",
                key,
                source_description,
                len(value),
                MAX_FIELD_LENGTH,
            )

    return validated_metadata, warnings


class StaticContentHandler:
    """Handler for static content endpoints"""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        config_key: web.AppKey["nowplaying.config.ConfigFile"],
        ic_key: web.AppKey["nowplaying.imagecache.ImageCache"],
        metadb_key: web.AppKey[nowplaying.db.MetadataDB],
        remotedb_key: web.AppKey[nowplaying.db.MetadataDB],
        metadata_key: web.AppKey["nowplaying.metadata.MetadataProcessors"],
    ):
        self.config_key = config_key
        self.ic_key = ic_key
        self.metadb_key = metadb_key
        self.remotedb_key = remotedb_key
        self.metadata_key = metadata_key

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

    async def template_handler(self, request: web.Request):
        """handle direct template file requests"""
        template_name = request.match_info.get("template_name")
        if not template_name or not template_name.endswith(".htm"):
            return web.Response(status=404, text="Template not found")

        # Security: prevent directory traversal
        if "/" in template_name or "\\" in template_name or ".." in template_name:
            return web.Response(status=403, text="Invalid template name")

        config = request.app[self.config_key]
        template_path = config.templatedir.joinpath(template_name)

        if not template_path.exists():
            logging.debug("Cannot load %s as a template", template_path.absolute())
            return web.Response(status=404, text="Template not found")

        try:
            # Generate unique session ID for this template request
            session_id = str(uuid.uuid4())[:8]  # Short session ID
            logging.info(
                "Session %s: Template request for %s from %s",
                session_id,
                template_name,
                request.remote,
            )

            metadata = await request.app[self.metadb_key].read_last_meta_async()
            if not metadata:
                metadata = nowplaying.hostmeta.gethostmeta()
                metadata["httpport"] = config.cparser.value("weboutput/httpport", type=int)

            # Add session ID to metadata for template use
            metadata["session_id"] = session_id

            templatehandler = nowplaying.utils.TemplateHandler(filename=str(template_path))
            htmloutput = templatehandler.generate(metadata)
            return web.Response(content_type="text/html", text=htmloutput)
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.exception("template_handler error for %s: %s", template_name, err)
            return web.Response(status=500, text="Template error")

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
        source = os.path.basename(template) if template else "unknown"
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

        if not metadata or not metadata.get("dbid"):
            logging.debug("No metadata available or missing dbid, sending refresh")
            return web.Response(status=202, content_type="text/html", text=INDEXREFRESH)

        if not template:
            logging.warning(
                "Template path missing or invalid for config key '%s', sending refresh",
                cfgtemplate,
            )
            return web.Response(status=202, content_type="text/html", text=INDEXREFRESH)

        # Check if template file actually exists for better debugging
        if not os.path.exists(template):
            logging.error(
                "Template file does not exist: '%s' (from config key '%s'), sending refresh",
                template,
                cfgtemplate,
            )
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

    async def whatsnowplaying_js_handler(self, request: web.Request):
        """serve the What's Now Playing WebSocket JavaScript library"""
        config = request.app[self.config_key]
        js_path = config.getbundledir().joinpath("templates", "whatsnowplaying-websocket.js")

        if js_path.exists():
            with open(js_path, encoding="utf-8") as fhin:
                js_content = fhin.read()
            return web.Response(text=js_content, content_type="application/javascript")

        return web.Response(status=404, text="Library not found")

    async def vendor_handler(self, request: web.Request):
        """serve vendor files (JavaScript and fonts)"""
        vendor_file = request.match_info.get("vendor_file")
        if not vendor_file:
            return web.Response(status=404, text="Vendor file not found")

        # Allow specific file extensions (case-insensitive)
        allowed_extensions = (".js", ".woff", ".woff2", ".ttf", ".eot")
        if not vendor_file.lower().endswith(allowed_extensions):
            return web.Response(status=404, text="Vendor file type not supported")

        # Security: prevent directory traversal
        if "/" in vendor_file or "\\" in vendor_file or ".." in vendor_file:
            return web.Response(status=403, text="Invalid vendor file name")

        config = request.app[self.config_key]
        vendor_path = config.getbundledir().joinpath("templates", "vendor", vendor_file)

        if not vendor_path.exists():
            return web.Response(status=404, text="Vendor file not found")

        content_type: str | None = None
        content: str | bytes | None = None
        # Determine content type based on file extension
        if vendor_file.endswith(".js"):
            content_type = "application/javascript"
            with open(vendor_path, encoding="utf-8") as fhin:
                content = fhin.read()

        if vendor_file.endswith(".woff"):
            content_type = "font/woff"
            with open(vendor_path, "rb") as fhin:
                content = fhin.read()

        if vendor_file.endswith(".woff2"):
            content_type = "font/woff2"
            with open(vendor_path, "rb") as fhin:
                content = fhin.read()

        if vendor_file.endswith(".ttf"):
            content_type = "font/ttf"
            with open(vendor_path, "rb") as fhin:
                content = fhin.read()

        if vendor_file.endswith(".eot"):
            content_type = "application/vnd.ms-fontobject"
            with open(vendor_path, "rb") as fhin:
                content = fhin.read()

        return web.Response(body=content, content_type=content_type)

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
                image: bytes = metadata[imgtype]
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

    @staticmethod
    def _filter_excluded_fields(metadata: TrackMetadata) -> TrackMetadata:
        """filter out fields that should be excluded from remote submissions"""
        excluded_fields = set(nowplaying.db.METADATABLOBLIST) | {
            "httpport",
            "hostname",
            "hostfqdn",
            "hostip",
            "ipaddress",
            "previoustrack",
            "dbid",
            "cache_warmed",
            "secret",
            "filename",  # Security: Never accept filenames from remote sources
            "track_received",  # System-generated timestamp, not user-provided
            "version",  # System-generated version, not user-provided
        }
        return {k: v for k, v in metadata.items() if k not in excluded_fields}

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

    async def _process_remote_metadata(  # pylint: disable=too-many-locals
        self, request: web.Request, metadata: dict, source: str = "remote"
    ):
        """Common processing for remote metadata submissions"""
        # Refresh config to get latest settings (important for testing)
        request.app[self.config_key].get()
        if required_secret := request.app[self.config_key].cparser.value(
            "remote/remote_key", type=str, defaultValue=""
        ):
            provided_secret = metadata.get("secret", "")
            if not provided_secret:
                logging.warning(
                    "Remote metadata submission without secret from %s", request.remote
                )
                return web.json_response({"error": "Missing secret in request"}, status=403)

            # Use constant-time comparison to prevent timing attacks
            if not secrets.compare_digest(required_secret, provided_secret):
                logging.warning(
                    "Remote metadata submission with invalid secret from %s", request.remote
                )
                return web.json_response({"error": "Invalid secret"}, status=403)

        logging.info("Got %s raw metadata from %s: %s ", source, request.host, metadata)

        # Start with a copy of the metadata
        clean_metadata: TrackMetadata = metadata.copy()

        # Field length limits to prevent oversized fields
        clean_metadata, validation_warnings = validate_field_lengths(
            clean_metadata, str(request.remote)
        )

        # Field whitelist - based on what remote.py actually sends
        clean_metadata = self._filter_excluded_fields(clean_metadata)

        # Strip null bytes from all string fields (radiologik and other sources may send them)
        for key, value in clean_metadata.items():
            if isinstance(value, str) and "\x00" in value:
                clean_metadata[key] = value.rstrip("\x00")

        logging.info("Got %s metadata from %s ", source, request.host)
        # Store metadata in remote database
        try:
            # Processing timeout to prevent hanging on network calls
            processed_metadata = await asyncio.wait_for(
                request.app[self.metadata_key].getmoremetadata(
                    metadata=clean_metadata, imagecache=request.app[self.ic_key]
                ),
                timeout=30.0,
            )
            await request.app[self.remotedb_key].write_to_metadb(metadata=processed_metadata)
            # Re-read to get the dbid
            last_meta = await request.app[self.remotedb_key].read_last_meta_async()
            dbid = last_meta.get("dbid") if last_meta else None

            # Filter out excluded fields from response to ensure JSON serialization works
            response_metadata = self._filter_excluded_fields(processed_metadata)

            # Let aiohttp handle JSON serialization automatically

            # Build response with optional warnings
            response = {"dbid": dbid, "processed_metadata": response_metadata}
            if validation_warnings:
                response["warnings"] = validation_warnings

            return web.json_response(response)
        except TimeoutError:
            logging.error("Metadata processing timeout for request from %s", request.remote)
            return web.json_response({"error": "Processing timeout"}, status=408)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.error("Failed to store metadata in remote database: %s", exc)
            return web.json_response({"error": "Failed to store metadata"}, status=500)

    async def api_v1_remoteinput_handler(self, request: web.Request):
        """POST: receive metadata from remote source and store in remote database"""
        if request.method == "POST":
            try:
                request_data = await request.json()
            except Exception:  # pylint: disable=broad-exception-caught
                return web.json_response({"error": "Invalid JSON in request body"}, status=400)
        if request.method == "GET":
            try:
                request_data = dict(request.query)
            except Exception:  # pylint: disable=broad-exception-caught
                return web.json_response({"error": "Invalid query params"}, status=400)

        return await self._process_remote_metadata(request, request_data, "remoteinput")
