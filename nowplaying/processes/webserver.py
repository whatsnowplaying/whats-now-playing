#!/usr/bin/env python3
"""WebServer process"""

import asyncio
import base64
import contextlib
import logging
import logging.config
import os
import pathlib
import secrets
import signal
import string
import sys
import threading
import time
import weakref

import requests
import aiohttp
from aiohttp import web, WSCloseCode
import aiosqlite
import jinja2

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

from nowplaying.webserver.images_websocket import ImagesWebSocketHandler
from nowplaying.webserver.gifwords_websocket import GifwordsWebSocketHandler
from nowplaying.webserver.static_handlers import StaticContentHandler

#
# quiet down our imports
#

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": True,
    }
)

# pylint: disable=wrong-import-position

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.imagecache
import nowplaying.kick.oauth2
import nowplaying.metadata
import nowplaying.oauth2
import nowplaying.twitch.oauth2
import nowplaying.utils
from nowplaying.types import TrackMetadata


INDEXREFRESH = (
    '<!doctype html><html lang="en">'
    '<head><meta http-equiv="refresh" content="5" ></head>'
    "<body></body></html>\n"
)

CONFIG_KEY = web.AppKey("config", nowplaying.config.ConfigFile)
METADB_KEY = web.AppKey("metadb", nowplaying.db.MetadataDB)
REMOTEDB_KEY = web.AppKey("remotedb", nowplaying.db.MetadataDB)
WS_KEY = web.AppKey("websockets", weakref.WeakSet)
IC_KEY = web.AppKey("imagecache", nowplaying.imagecache.ImageCache)
WATCHER_KEY = web.AppKey("watcher", nowplaying.db.DBWatcher)
JINJA2_KEY = web.AppKey("jinja2_env", jinja2.Environment)
METADATA_KEY = web.AppKey("metadata", nowplaying.metadata.MetadataProcessors)


class WebHandler:  # pylint: disable=too-many-public-methods,too-many-instance-attributes
    """aiohttp built server that does both http and websocket"""

    def __init__(
        self,
        bundledir: pathlib.Path | str | None = None,
        config: nowplaying.config.ConfigFile | None = None,
        stopevent: asyncio.Event | None = None,
        testmode: bool = False,
    ):
        threading.current_thread().name = "WebServer"
        self.tasks = set()
        self.testmode = testmode
        if not config:
            config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=testmode)
        self.port: int = config.cparser.value("weboutput/httpport", type=int)
        enabled: bool = config.cparser.value("weboutput/httpenabled", type=bool)
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
        ).joinpath("webserver", "web.db")
        self._init_webdb()
        self.stopevent = stopevent

        # Initialize WebSocket handlers
        self.images_ws_handler = ImagesWebSocketHandler(
            stopevent=self.stopevent,
            ws_key=WS_KEY,
            ic_key=IC_KEY,
            metadb_key=METADB_KEY,
            config_key=CONFIG_KEY,
            metadata_key=METADATA_KEY,
        )

        self.gifwords_ws_handler = GifwordsWebSocketHandler(
            stopevent=self.stopevent,
            config_key=CONFIG_KEY,
        )

        # Initialize static content handler
        self.static_handler = StaticContentHandler(
            config_key=CONFIG_KEY, metadb_key=METADB_KEY, remotedb_key=REMOTEDB_KEY
        )

        while not enabled and not nowplaying.utils.safe_stopevent_check(self.stopevent):
            try:
                time.sleep(5)
                config.get()
                enabled = config.cparser.value("weboutput/httpenabled", type=bool)
            except KeyboardInterrupt:
                sys.exit(0)

        self.magicstopurl = "".join(secrets.choice(string.ascii_letters) for _ in range(32))

        logging.info("Secret url to quit websever: %s", self.magicstopurl)

        signal.signal(signal.SIGINT, self.forced_stop)
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()

        self.loop.run_until_complete(self.start_server(host="0.0.0.0", port=self.port))
        self.loop.run_forever()

    def _init_webdb(self):
        if self.databasefile.exists():
            try:
                self.databasefile.unlink()
            except PermissionError as error:
                logging.error("WebServer process already running?")
                logging.error(error)
                sys.exit(1)

        self.databasefile.parent.mkdir(parents=True, exist_ok=True)

    async def stopeventtask(self):
        """task to wait for the stop event"""
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(0.5)
        await self.forced_stop()

    async def config_refresh_task(self, app: web.Application):
        """Background task to periodically refresh config from main process"""
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            try:
                await asyncio.sleep(30)  # Refresh every 30 seconds
                if not nowplaying.utils.safe_stopevent_check(self.stopevent):
                    app[CONFIG_KEY].get()
            except Exception as error:  # pylint: disable=broad-except
                logging.error("Config refresh task error: %s", error)

    @staticmethod
    def _base64ifier(metadata: TrackMetadata):
        """replace all the binary data with base64 data"""
        for key in nowplaying.db.METADATABLOBLIST:
            if metadata.get(key):
                newkey = key.replace("raw", "base64")
                metadata[newkey] = base64.b64encode(metadata[key]).decode("utf-8")
                del metadata[key]
        if metadata.get("dbid"):
            del metadata["dbid"]
        return metadata

    def _transparentifier(self, metadata: TrackMetadata):
        """base64 encoding + transparent missing"""
        for key in nowplaying.db.METADATABLOBLIST:
            if not metadata.get(key):
                metadata[key] = nowplaying.utils.TRANSPARENT_PNG_BIN
        return self._base64ifier(metadata)

    async def websocket_artistfanart_streamer(self, request: web.Request):
        """handle continually streamed updates"""
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app[WS_KEY].add(websocket)
        endloop = False
        config_refresh_counter = 0

        # Get session ID from query parameters
        session_id = request.query.get("session_id", "unknown")
        logging.info(
            "Session %s: Artistfanart streamer connected from %s", session_id, request.remote
        )

        try:
            while (
                not nowplaying.utils.safe_stopevent_check(self.stopevent)
                and not endloop
                and not websocket.closed
            ):
                metadata = await request.app[METADB_KEY].read_last_meta_async()
                if not metadata or not metadata.get("artist"):
                    await asyncio.sleep(5)
                    continue

                imagedata = None

                with contextlib.suppress(KeyError):
                    imagedata = request.app[IC_KEY].random_image_fetch(
                        identifier=metadata["imagecacheartist"], imagetype="artistfanart"
                    )

                if imagedata:
                    metadata["artistfanartraw"] = imagedata
                elif request.app[CONFIG_KEY].cparser.value(
                    "artistextras/coverfornofanart", type=bool
                ):
                    metadata["artistfanartraw"] = metadata.get("coverimageraw")
                else:
                    metadata["artistfanartraw"] = nowplaying.utils.TRANSPARENT_PNG_BIN

                try:
                    if websocket.closed:
                        break
                    await websocket.send_json(self._transparentifier(metadata))
                except ConnectionResetError:
                    logging.debug("Lost a client")
                    endloop = True

                # Refresh config every 10 iterations to pick up setting changes
                config_refresh_counter += 1
                if config_refresh_counter >= 10:
                    request.app[CONFIG_KEY].get()
                    config_refresh_counter = 0

                delay = request.app[CONFIG_KEY].cparser.value("artistextras/fanartdelay", type=int)
                await asyncio.sleep(delay)
            if not websocket.closed:
                await websocket.send_json({"last": True})
        except Exception as error:  # pylint: disable=broad-except
            logging.error(
                "Session %s: websocket artistfanart streamer exception: %s", session_id, error
            )
        finally:
            logging.info("Session %s: Artistfanart streamer disconnected", session_id)
            await websocket.close()
            request.app[WS_KEY].discard(websocket)
        return websocket

    async def websocket_lastjson_handler(
        self, request: web.Request, websocket: web.WebSocketResponse
    ):
        """handle singular websocket request"""
        metadata = await request.app[METADB_KEY].read_last_meta_async()
        if metadata:
            del metadata["dbid"]
            if not websocket.closed:
                await websocket.send_json(self._base64ifier(metadata))

    async def _wss_do_update(
        self, websocket: web.WebSocketResponse, database: nowplaying.db.MetadataDB
    ):
        # early launch can be a bit weird so
        # pause a bit
        await asyncio.sleep(1)
        metadata = None
        while not metadata and not websocket.closed:
            if nowplaying.utils.safe_stopevent_check(self.stopevent):
                return time.time()
            metadata = await database.read_last_meta_async()
            await asyncio.sleep(1)
        if metadata:
            del metadata["dbid"]
            if not websocket.closed:
                await websocket.send_json(self._transparentifier(metadata))
        return time.time()

    async def websocket_streamer(self, request: web.Request):
        """handle continually streamed updates"""

        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app[WS_KEY].add(websocket)

        # Get session ID from query parameters
        session_id = request.query.get("session_id", "unknown")
        logging.info(
            "Session %s: WebSocket streamer connected from %s", session_id, request.remote
        )

        try:
            mytime = await self._wss_do_update(websocket, request.app[METADB_KEY])
            while (
                not nowplaying.utils.safe_stopevent_check(self.stopevent) and not websocket.closed
            ):
                while mytime > request.app[
                    WATCHER_KEY
                ].updatetime and not nowplaying.utils.safe_stopevent_check(self.stopevent):
                    await asyncio.sleep(1)

                mytime = await self._wss_do_update(websocket, request.app[METADB_KEY])
                await asyncio.sleep(1)
            if not websocket.closed:
                await websocket.send_json({"last": True})
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Session %s: websocket streamer exception: %s", session_id, error)
        finally:
            logging.info("Session %s: WebSocket streamer disconnected", session_id)
            await websocket.close()
            request.app[WS_KEY].discard(websocket)
        return websocket

    async def websocket_handler(self, request: web.Request):
        """handle inbound websockets"""
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app[WS_KEY].add(websocket)
        try:
            async for msg in websocket:
                if websocket.closed:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == "close":
                        await websocket.close()
                    elif msg.data == "last":
                        logging.debug("got last")
                        await self.websocket_lastjson_handler(request, websocket)
                    else:
                        await websocket.send_str("some websocket message payload")
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logging.error("ws connection closed with exception %s", websocket.exception())
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Websocket handler error: %s", error)
        finally:
            request.app[WS_KEY].discard(websocket)

        return websocket

    @staticmethod
    async def internals(request: web.Request):
        """internal data debugging"""
        data = {"dbfile": str(request.app[METADB_KEY].databasefile)}
        return web.json_response(data)

    @staticmethod
    async def _handle_oauth_redirect(request: web.Request, oauth_config: dict) -> web.Response:
        """Generic OAuth2 redirect handler - delegates to base OAuth2 class."""
        # Pass config and jinja2 environment from app context using correct keys
        config = request.app[CONFIG_KEY]
        jinja2_env = request.app[JINJA2_KEY]
        return await nowplaying.oauth2.OAuth2Client.handle_oauth_redirect(
            request, oauth_config, config, jinja2_env
        )

    async def kickredirect_handler(self, request: web.Request):  # pylint: disable=no-self-use
        """handle oauth2 redirect callbacks for Kick"""
        return await self._handle_oauth_redirect(
            request,
            {
                "service_name": "Kick OAuth2",
                "oauth_class": nowplaying.kick.oauth2.KickOAuth2,
                "config_prefix": "kick",
                "template_prefix": "kick_oauth",
                "redirect_path": "kickredirect",
                "token_keys": {"access": "kick/accesstoken", "refresh": "kick/refreshtoken"},
            },
        )

    async def twitchredirect_handler(self, request: web.Request):  # pylint: disable=no-self-use
        """handle oauth2 redirect callbacks for Twitch broadcaster tokens"""
        return await self._handle_oauth_redirect(
            request,
            {
                "service_name": "Twitch OAuth2",
                "oauth_class": nowplaying.twitch.oauth2.TwitchOAuth2,
                "config_prefix": "twitchbot",
                "template_prefix": "twitch_oauth",
                "redirect_path": "twitchredirect",
                "token_keys": {
                    "access": "twitchbot/accesstoken",
                    "refresh": "twitchbot/refreshtoken",
                },
            },
        )

    async def twitchchatredirect_handler(self, request: web.Request):  # pylint: disable=no-self-use
        """handle oauth2 redirect callbacks for Twitch chat tokens"""
        return await self._handle_oauth_redirect(
            request,
            {
                "service_name": "Twitch Chat OAuth2",
                "oauth_class": nowplaying.twitch.oauth2.TwitchOAuth2,
                "config_prefix": "twitchbot",
                "template_prefix": "twitch_oauth",
                "redirect_path": "twitchchatredirect",
                "token_keys": {
                    "access": "twitchbot/chattoken",
                    "refresh": "twitchbot/chatrefreshtoken",
                },
                "success_template": "twitch_chat_oauth_success.htm",
            },
        )

    def create_runner(self):
        """setup http routing"""
        threading.current_thread().name = "WebServer-runner"
        app = web.Application()
        app[WS_KEY] = weakref.WeakSet()
        app.on_startup.append(self.on_startup)
        app.on_cleanup.append(self.on_cleanup)
        app.on_shutdown.append(self.on_shutdown)
        _ = app.add_routes(
            [
                web.get("/", self.static_handler.index_htm_handler),
                web.get("/v1/last", self.static_handler.api_v1_last_handler),
                web.post("/v1/remoteinput", self.static_handler.api_v1_remoteinput_handler),
                web.get("/cover.png", self.static_handler.cover_handler),
                web.get("/artistfanart.htm", self.static_handler.artistfanartlaunch_htm_handler),
                web.get("/artistbanner.png", self.static_handler.artistbanner_handler),
                web.get("/artistbanner.htm", self.static_handler.artistbanner_htm_handler),
                web.get("/artistlogo.png", self.static_handler.artistlogo_handler),
                web.get("/artistlogo.htm", self.static_handler.artistlogo_htm_handler),
                web.get("/artistthumb.png", self.static_handler.artistthumbnail_handler),
                web.get("/artistthumb.htm", self.static_handler.artistthumbnail_htm_handler),
                web.get("/favicon.ico", self.static_handler.favicon_handler),
                web.get("/gifwords.htm", self.static_handler.gifwords_launch_htm_handler),
                web.get("/index.htm", self.static_handler.index_htm_handler),
                web.get("/index.html", self.static_handler.index_htm_handler),
                web.get("/index.txt", self.static_handler.indextxt_handler),
                web.get("/kickredirect", self.kickredirect_handler),
                web.get("/twitchredirect", self.twitchredirect_handler),
                web.get("/twitchchatredirect", self.twitchchatredirect_handler),
                web.get("/request.htm", self.static_handler.requesterlaunch_htm_handler),
                web.get("/internals", self.internals),
                web.get("/ws", self.websocket_handler),
                web.get("/wsstream", self.websocket_streamer),
                web.get("/wsartistfanartstream", self.websocket_artistfanart_streamer),
                web.get("/wsgifwordsstream", self.gifwords_ws_handler.websocket_gifwords_streamer),
                web.get("/v1/images/ws", self.images_ws_handler.websocket_images_handler),
                web.get("/nowplaying-websocket.js", self.static_handler.nowplaying_js_handler),
                web.get(r"/{template_name:.+\.htm}", self.static_handler.template_handler),
                web.get(f"/{self.magicstopurl}", self.stop_server),
            ]
        )
        return web.AppRunner(app)

    async def start_server(self, host: str = "127.0.0.1", port: int = 8899):
        """start our server"""
        runner = self.create_runner()
        await runner.setup()
        site = web.TCPSite(runner, host, port)

        # Start background tasks
        stop_task = asyncio.create_task(self.stopeventtask())
        self.tasks.add(stop_task)
        stop_task.add_done_callback(self.tasks.discard)

        config_task = asyncio.create_task(self.config_refresh_task(runner.app))
        self.tasks.add(config_task)
        config_task.add_done_callback(self.tasks.discard)

        gifwords_task = asyncio.create_task(
            self.gifwords_ws_handler.gifwords_broadcast_task(runner.app)
        )
        self.tasks.add(gifwords_task)
        gifwords_task.add_done_callback(self.tasks.discard)

        await site.start()

    async def on_startup(self, app: web.Application):
        """setup app connections"""
        app[CONFIG_KEY] = nowplaying.config.ConfigFile(testmode=self.testmode)
        staticdir = app[CONFIG_KEY].basedir.joinpath("httpstatic")
        logging.debug("Verifying %s", staticdir)
        staticdir.mkdir(parents=True, exist_ok=True)
        logging.debug("Verified %s", staticdir)
        app.router.add_static(
            "/httpstatic/",
            path=staticdir,
        )

        # Add static file serving for vendor files only
        template_dir = app[CONFIG_KEY].getbundledir().joinpath("templates")
        app.router.add_static("/vendor/", path=template_dir / "vendor", name="vendor")
        app[METADB_KEY] = nowplaying.db.MetadataDB()
        app[IC_KEY] = nowplaying.imagecache.ImageCache()
        app[WATCHER_KEY] = app[METADB_KEY].watcher()
        app[WATCHER_KEY].start()
        remotedb: str = app[CONFIG_KEY].cparser.value("remote/remotedb", type=str)
        app[REMOTEDB_KEY] = nowplaying.db.MetadataDB(databasefile=remotedb)
        app[METADATA_KEY] = nowplaying.metadata.MetadataProcessors(config=app[CONFIG_KEY])
        app["statedb"] = await aiosqlite.connect(self.databasefile)
        app["statedb"].row_factory = aiosqlite.Row
        cursor = await app["statedb"].cursor()
        await cursor.execute(
            "CREATE TABLE IF NOT EXISTS lastprocessed (source TEXT PRIMARY KEY, lastid INTEGER )"
        )
        await app["statedb"].commit()

        # Set up Jinja2 environment for templates with proper autoescape (initialized once)
        template_dir = app[CONFIG_KEY].getbundledir().joinpath("templates")
        app[JINJA2_KEY] = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=jinja2.select_autoescape(["htm", "html", "xml"]),
            trim_blocks=True,
            undefined=jinja2.StrictUndefined,
        )

    @staticmethod
    async def on_shutdown(app: web.Application):
        """handle shutdown"""
        for websocket in set(app[WS_KEY]):
            await websocket.close(code=WSCloseCode.GOING_AWAY, message="Server shutdown")

    @staticmethod
    async def on_cleanup(app: web.Application):
        """cleanup the app"""
        await app["statedb"].close()
        app[WATCHER_KEY].stop()

    async def stop_server(self, request: web.Request):
        """stop our server"""
        self.stopevent.set()
        for task in self.tasks:
            task.cancel()
        await request.app.shutdown()
        await request.app.cleanup()
        self.loop.stop()

    def forced_stop(self, signum=None, frame=None):  # pylint: disable=unused-argument
        """caught an int signal so tell the world to stop"""
        try:
            logging.debug("telling webserver to stop via http")
            requests.get(f"http://localhost:{self.port}/{self.magicstopurl}", timeout=5)
        except Exception as error:  # pylint: disable=broad-except
            logging.info(error)
        for task in self.tasks:
            task.cancel()


def stop(pid: int):
    """stop the web server -- called from Tray"""
    logging.info("sending INT to %s", pid)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGINT)


def start(stopevent=None, bundledir: str | pathlib.Path | None = None, testmode: bool = False):
    """multiprocessing start hook"""
    threading.current_thread().name = "WebServer"

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
        testmode = True
    else:
        testmode = False
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname="debug.log", rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir, logpath=logpath, testmode=testmode)

    logging.info("boot up")

    try:
        webserver = WebHandler(  # pylint: disable=unused-variable
            config=config, stopevent=stopevent, testmode=testmode
        )
    except Exception as error:  # pylint: disable=broad-except
        logging.error("Webserver crashed: %s", error, exc_info=True)
        sys.exit(1)
    logging.info("shutting down webserver v%s", config.version)
    sys.exit(0)
