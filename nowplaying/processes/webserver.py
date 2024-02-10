#!/usr/bin/env python3
''' WebServer process '''

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
import traceback
import weakref

import requests
import aiohttp
from aiohttp import web, WSCloseCode
import aiosqlite

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

#
# quiet down our imports
#

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

# pylint: disable=wrong-import-position

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.hostmeta
import nowplaying.imagecache
import nowplaying.trackrequests
import nowplaying.utils

INDEXREFRESH = \
    '<!doctype html><html lang="en">' \
    '<head><meta http-equiv="refresh" content="5" ></head>' \
    '<body></body></html>\n'

CONFIG_KEY = web.AppKey('config', nowplaying.config.ConfigFile)
METADB_KEY = web.AppKey("metadb", nowplaying.db.MetadataDB)
WS_KEY = web.AppKey("websockets", weakref.WeakSet)
IC_KEY = web.AppKey("imagecache", nowplaying.imagecache.ImageCache)
WATCHER_KEY = web.AppKey("watcher", nowplaying.db.DBWatcher)


class WebHandler():  # pylint: disable=too-many-public-methods
    ''' aiohttp built server that does both http and websocket '''

    def __init__(self, bundledir=None, config=None, stopevent=None, testmode=False):
        threading.current_thread().name = 'WebServer'
        self.tasks = set()
        self.testmode = testmode
        if not config:
            config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=testmode)
        self.port = config.cparser.value('weboutput/httpport', type=int)
        enabled = config.cparser.value('weboutput/httpenabled', type=bool)
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]).joinpath(
                'webserver', 'web.db')
        self._init_webdb()
        self.stopevent = stopevent

        while not enabled and not self.stopevent.is_set():
            try:
                time.sleep(5)
                config.get()
                enabled = config.cparser.value('weboutput/httpenabled', type=bool)
            except KeyboardInterrupt:
                sys.exit(0)

        self.magicstopurl = ''.join(secrets.choice(string.ascii_letters) for _ in range(32))

        logging.info('Secret url to quit websever: %s', self.magicstopurl)

        signal.signal(signal.SIGINT, self.forced_stop)
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()

        self.loop.run_until_complete(self.start_server(host='0.0.0.0', port=self.port))
        self.loop.run_forever()

    def _init_webdb(self):
        if self.databasefile.exists():
            try:
                self.databasefile.unlink()
            except PermissionError as error:
                logging.error('WebServer process already running?')
                logging.error(error)
                sys.exit(1)

        self.databasefile.parent.mkdir(parents=True, exist_ok=True)

    async def stopeventtask(self):
        ''' task to wait for the stop event '''
        while not self.stopevent.is_set():
            await asyncio.sleep(.5)
        await self.forced_stop()

    @staticmethod
    def _base64ifier(metadata):
        ''' replace all the binary data with base64 data '''
        for key in nowplaying.db.METADATABLOBLIST:
            if metadata.get(key):
                newkey = key.replace('raw', 'base64')
                metadata[newkey] = base64.b64encode(metadata[key]).decode('utf-8')
                del metadata[key]
        if metadata.get('dbid'):
            del metadata['dbid']
        return metadata

    def _transparentifier(self, metadata):
        ''' base64 encoding + transparent missing '''
        for key in nowplaying.db.METADATABLOBLIST:
            if not metadata.get(key):
                metadata[key] = nowplaying.utils.TRANSPARENT_PNG_BIN
        return self._base64ifier(metadata)

    async def index_htm_handler(self, request):
        ''' handle web output '''
        return await self._metacheck_htm_handler(request, 'weboutput/htmltemplate')

    async def artistbanner_htm_handler(self, request):
        ''' handle web output '''
        return await self._metacheck_htm_handler(request, 'weboutput/artistbannertemplate')

    async def artistlogo_htm_handler(self, request):
        ''' handle web output '''
        return await self._metacheck_htm_handler(request, 'weboutput/artistlogotemplate')

    async def artistthumbnail_htm_handler(self, request):
        ''' handle web output '''
        return await self._metacheck_htm_handler(request, 'weboutput/artistthumbnailtemplate')

    async def artistfanartlaunch_htm_handler(self, request):
        ''' handle web output '''
        return await self._metacheck_htm_handler(request, 'weboutput/artistfanarttemplate')

    async def gifwords_launch_htm_handler(self, request):
        ''' handle gifwords output '''
        request.app[CONFIG_KEY].cparser.sync()
        htmloutput = await self._htm_handler(
            request, request.app[CONFIG_KEY].cparser.value('weboutput/gifwordstemplate'))
        return web.Response(content_type='text/html', text=htmloutput)

    async def requesterlaunch_htm_handler(self, request):
        ''' handle web output '''
        return await self._metacheck_htm_handler(request, 'weboutput/requestertemplate')

    @staticmethod
    async def _htm_handler(request, template, metadata=None):  # pylint: disable=unused-argument
        ''' handle static html files'''
        htmloutput = INDEXREFRESH
        try:
            if not metadata:
                metadata = await request.app[METADB_KEY].read_last_meta_async()
            if not metadata:
                metadata = nowplaying.hostmeta.gethostmeta()
                metadata['httpport'] = request.app[CONFIG_KEY].cparser.value('weboutput/httpport',
                                                                             type=int)
            templatehandler = nowplaying.utils.TemplateHandler(filename=template)
            htmloutput = templatehandler.generate(metadata)
        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
        return htmloutput

    async def _metacheck_htm_handler(self, request, cfgtemplate):  # pylint: disable=unused-argument
        ''' handle static html files after checking metadata'''
        request.app[CONFIG_KEY].cparser.sync()
        template = request.app[CONFIG_KEY].cparser.value(cfgtemplate)
        source = os.path.basename(template)
        htmloutput = ""
        request.app[CONFIG_KEY].get()
        metadata = await request.app[METADB_KEY].read_last_meta_async()
        lastid = await self.getlastid(request, source)
        once = request.app[CONFIG_KEY].cparser.value('weboutput/once', type=bool)
        #once = False

        # | dbid  |  lastid | once |
        # |   x   |   NA    |      |  -> update lastid, send template
        # |   x   |  diff   |   NA |  -> update lastid, send template
        # |   x   |  same   |      |  -> send template
        # |   x   |  same   |   x  |  -> send refresh
        # |       |   NA    |      |  -> send refresh because not ready or something broke

        if not metadata or not metadata.get('dbid') or not template:
            return web.Response(status=202, content_type='text/html', text=INDEXREFRESH)

        if lastid == 0 or lastid != metadata['dbid'] or not once:
            await self.setlastid(request, metadata['dbid'], source)
            htmloutput = await self._htm_handler(request, template, metadata=metadata)
            return web.Response(content_type='text/html', text=htmloutput)

        return web.Response(content_type='text/html', text=INDEXREFRESH)

    @staticmethod
    async def setlastid(request, lastid, source):
        ''' get the lastid sent by http/html '''
        await request.app['statedb'].execute(
            'INSERT OR REPLACE INTO lastprocessed(lastid, source) VALUES (?,?) ', [lastid, source])
        await request.app['statedb'].commit()

    @staticmethod
    async def getlastid(request, source):
        ''' get the lastid sent by http/html '''
        cursor = await request.app['statedb'].execute(
            f'SELECT lastid FROM lastprocessed WHERE source="{source}"')
        row = await cursor.fetchone()
        if not row:
            lastid = 0
        else:
            lastid = row[0]
        await cursor.close()
        return lastid

    @staticmethod
    async def indextxt_handler(request):
        ''' handle static index.txt '''
        metadata = await request.app[METADB_KEY].read_last_meta_async()
        txtoutput = ""
        if metadata:
            request.app[CONFIG_KEY].get()
            try:
                templatehandler = nowplaying.utils.TemplateHandler(
                    filename=request.app[CONFIG_KEY].cparser.value('textoutput/txttemplate'))
                txtoutput = templatehandler.generate(metadata)
            except Exception as error:  #pylint: disable=broad-except
                logging.error('indextxt_handler: %s', error)
                txtoutput = ''
        return web.Response(text=txtoutput)

    @staticmethod
    async def favicon_handler(request):
        ''' handle favicon.ico '''
        return web.FileResponse(path=request.app[CONFIG_KEY].iconfile)

    @staticmethod
    async def _image_handler(imgtype, request):
        ''' handle an image '''

        # rather than return an error, just send a transparent PNG
        # this makes the client code significantly easier
        image = nowplaying.utils.TRANSPARENT_PNG_BIN
        try:
            metadata = await request.app[METADB_KEY].read_last_meta_async()
            if metadata and metadata.get(imgtype):
                image = metadata[imgtype]
        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
        return web.Response(content_type='image/png', body=image)

    async def cover_handler(self, request):
        ''' handle cover image '''
        return await self._image_handler('coverimageraw', request)

    async def artistbanner_handler(self, request):
        ''' handle artist banner image '''
        return await self._image_handler('artistbannerraw', request)

    async def artistlogo_handler(self, request):
        ''' handle artist logo image '''
        return await self._image_handler('artistlogoraw', request)

    async def artistthumbnail_handler(self, request):
        ''' handle artist logo image '''
        return await self._image_handler('artistthumbnailraw', request)

    async def api_v1_last_handler(self, request):
        ''' v1/last just returns the metadata'''
        data = {}
        if metadata := await request.app[METADB_KEY].read_last_meta_async():
            try:
                del metadata['dbid']
                data = self._base64ifier(metadata)
            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.debug(line)
        return web.json_response(data)

    async def websocket_gifwords_streamer(self, request):
        ''' handle continually streamed updates '''
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app[WS_KEY].add(websocket)
        endloop = False

        trackrequest = nowplaying.trackrequests.Requests(request.app[CONFIG_KEY])

        try:
            while (not self.stopevent.is_set() and not endloop and not websocket.closed):
                metadata = await trackrequest.check_for_gifwords()
                if not metadata.get('image'):
                    await websocket.send_json({'noimage': True})
                    await asyncio.sleep(5)
                    continue

                metadata['imagebase64'] = base64.b64encode(metadata['image']).decode('utf-8')
                del metadata['image']
                try:
                    if websocket.closed:
                        break
                    await websocket.send_json(metadata)
                except ConnectionResetError:
                    logging.debug('Lost a client')
                    endloop = True
                await asyncio.sleep(20)
            if not websocket.closed:
                await websocket.send_json({'last': True})

        except Exception as error:  #pylint: disable=broad-except
            logging.error('websocket gifwords streamer exception: %s', error)
        finally:
            await websocket.close()
            request.app[WS_KEY].discard(websocket)
        return websocket

    async def websocket_artistfanart_streamer(self, request):
        ''' handle continually streamed updates '''
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app[WS_KEY].add(websocket)
        endloop = False

        try:
            while not self.stopevent.is_set() and not endloop and not websocket.closed:
                metadata = await request.app[METADB_KEY].read_last_meta_async()
                if not metadata or not metadata.get('artist'):
                    await asyncio.sleep(5)
                    continue

                imagedata = None

                with contextlib.suppress(KeyError):
                    imagedata = request.app[IC_KEY].random_image_fetch(
                        artist=metadata['imagecacheartist'], imagetype='artistfanart')

                if imagedata:
                    metadata['artistfanartraw'] = imagedata
                elif request.app[CONFIG_KEY].cparser.value('artistextras/coverfornofanart',
                                                           type=bool):
                    metadata['artistfanartraw'] = metadata.get('coverimageraw')
                else:
                    metadata['artistfanartraw'] = nowplaying.utils.TRANSPARENT_PNG_BIN

                try:
                    if websocket.closed:
                        break
                    await websocket.send_json(self._transparentifier(metadata))
                except ConnectionResetError:
                    logging.debug('Lost a client')
                    endloop = True
                delay = request.app[CONFIG_KEY].cparser.value('artistextras/fanartdelay', type=int)
                await asyncio.sleep(delay)
            if not websocket.closed:
                await websocket.send_json({'last': True})
        except Exception as error:  #pylint: disable=broad-except
            logging.error('websocket artistfanart streamer exception: %s', error)
        finally:
            await websocket.close()
            request.app[WS_KEY].discard(websocket)
        return websocket

    async def websocket_lastjson_handler(self, request, websocket):
        ''' handle singular websocket request '''
        metadata = await request.app[METADB_KEY].read_last_meta_async()
        del metadata['dbid']
        if not websocket.closed:
            await websocket.send_json(self._base64ifier(metadata))

    async def _wss_do_update(self, websocket, database):
        # early launch can be a bit weird so
        # pause a bit
        await asyncio.sleep(1)
        metadata = None
        while not metadata and not websocket.closed:
            if self.stopevent.is_set():
                return time.time()
            metadata = await database.read_last_meta_async()
            await asyncio.sleep(1)
        del metadata['dbid']
        if not websocket.closed:
            await websocket.send_json(self._transparentifier(metadata))
        return time.time()

    async def websocket_streamer(self, request):
        ''' handle continually streamed updates '''

        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app[WS_KEY].add(websocket)

        try:
            mytime = await self._wss_do_update(websocket, request.app[METADB_KEY])
            while not self.stopevent.is_set() and not websocket.closed:
                while mytime > request.app[WATCHER_KEY].updatetime and not self.stopevent.is_set():
                    await asyncio.sleep(1)

                mytime = await self._wss_do_update(websocket, request.app[METADB_KEY])
                await asyncio.sleep(1)
            if not websocket.closed:
                await websocket.send_json({'last': True})
        except Exception as error:  #pylint: disable=broad-except
            logging.error('websocket streamer exception: %s', error)
        finally:
            await websocket.close()
            request.app[WS_KEY].discard(websocket)
        return websocket

    async def websocket_handler(self, request):
        ''' handle inbound websockets '''
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app[WS_KEY].add(websocket)
        try:
            async for msg in websocket:
                if websocket.closed:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == 'close':
                        await websocket.close()
                    elif msg.data == 'last':
                        logging.debug('got last')
                        await self.websocket_lastjson_handler(request, websocket)
                    else:
                        await websocket.send_str('some websocket message payload')
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logging.error('ws connection closed with exception %s', websocket.exception())
        except Exception as error:  #pylint: disable=broad-except
            logging.error('Websocket handler error: %s', error)
        finally:
            request.app[WS_KEY].discard(websocket)

        return websocket

    @staticmethod
    async def internals(request):
        ''' internal data debugging '''
        data = {"dbfile": str(request.app[METADB_KEY].databasefile)}
        return web.json_response(data)

    def create_runner(self):
        ''' setup http routing '''
        threading.current_thread().name = 'WebServer-runner'
        app = web.Application()
        app[WS_KEY] = weakref.WeakSet()
        app.on_startup.append(self.on_startup)
        app.on_cleanup.append(self.on_cleanup)
        app.on_shutdown.append(self.on_shutdown)
        app.add_routes([
            web.get('/', self.index_htm_handler),
            web.get('/v1/last', self.api_v1_last_handler),
            web.get('/cover.png', self.cover_handler),
            web.get('/artistfanart.htm', self.artistfanartlaunch_htm_handler),
            web.get('/artistbanner.png', self.artistbanner_handler),
            web.get('/artistbanner.htm', self.artistbanner_htm_handler),
            web.get('/artistlogo.png', self.artistlogo_handler),
            web.get('/artistlogo.htm', self.artistlogo_htm_handler),
            web.get('/artistthumb.png', self.artistthumbnail_handler),
            web.get('/artistthumb.htm', self.artistthumbnail_htm_handler),
            web.get('/favicon.ico', self.favicon_handler),
            web.get('/gifwords.htm', self.gifwords_launch_htm_handler),
            web.get('/index.htm', self.index_htm_handler),
            web.get('/index.html', self.index_htm_handler),
            web.get('/index.txt', self.indextxt_handler),
            web.get('/request.htm', self.requesterlaunch_htm_handler),
            web.get('/internals', self.internals),
            web.get('/ws', self.websocket_handler),
            web.get('/wsstream', self.websocket_streamer),
            web.get('/wsartistfanartstream', self.websocket_artistfanart_streamer),
            web.get('/wsgifwordsstream', self.websocket_gifwords_streamer),
            web.get(f'/{self.magicstopurl}', self.stop_server),
        ])
        return web.AppRunner(app)

    async def start_server(self, host="127.0.0.1", port=8899):
        ''' start our server '''
        runner = self.create_runner()
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        task = asyncio.create_task(self.stopeventtask())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        await site.start()

    async def on_startup(self, app):
        ''' setup app connections '''
        app[CONFIG_KEY] = nowplaying.config.ConfigFile(testmode=self.testmode)
        staticdir = app[CONFIG_KEY].basedir.joinpath('httpstatic')
        logging.debug('Verifying %s', staticdir)
        staticdir.mkdir(parents=True, exist_ok=True)
        logging.debug('Verified %s', staticdir)
        app.router.add_static(
            '/httpstatic/',
            path=staticdir,
        )
        app[METADB_KEY] = nowplaying.db.MetadataDB()
        if not self.testmode:
            app[IC_KEY] = nowplaying.imagecache.ImageCache()
        app[WATCHER_KEY] = app[METADB_KEY].watcher()
        app[WATCHER_KEY].start()
        app['statedb'] = await aiosqlite.connect(self.databasefile)
        app['statedb'].row_factory = aiosqlite.Row
        cursor = await app['statedb'].cursor()
        await cursor.execute('CREATE TABLE IF NOT EXISTS lastprocessed ('
                             'source TEXT PRIMARY KEY, '
                             'lastid INTEGER '
                             ')')
        await app['statedb'].commit()

    @staticmethod
    async def on_shutdown(app):
        ''' handle shutdown '''
        for websocket in set(app[WS_KEY]):
            await websocket.close(code=WSCloseCode.GOING_AWAY, message='Server shutdown')

    @staticmethod
    async def on_cleanup(app):
        ''' cleanup the app '''
        await app['statedb'].close()
        app[WATCHER_KEY].stop()

    async def stop_server(self, request):
        ''' stop our server '''
        self.stopevent.set()
        for task in self.tasks:
            task.cancel()
        await request.app.shutdown()
        await request.app.cleanup()
        self.loop.stop()

    def forced_stop(self, signum=None, frame=None):  # pylint: disable=unused-argument
        ''' caught an int signal so tell the world to stop '''
        try:
            logging.debug('telling webserver to stop via http')
            requests.get(f'http://localhost:{self.port}/{self.magicstopurl}', timeout=5)
        except Exception as error:  # pylint: disable=broad-except
            logging.info(error)
        for task in self.tasks:
            task.cancel()


def stop(pid):
    ''' stop the web server -- called from Tray '''
    logging.info('sending INT to %s', pid)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGINT)


def start(stopevent=None, bundledir=None, testmode=False):
    ''' multiprocessing start hook '''
    threading.current_thread().name = 'WebServer'

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
        testmode = True
    else:
        testmode = False
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname='debug.log', rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir, logpath=logpath, testmode=testmode)

    logging.info('boot up')

    try:
        webserver = WebHandler(  # pylint: disable=unused-variable
            config=config,
            stopevent=stopevent,
            testmode=testmode)
    except Exception as error:  #pylint: disable=broad-except
        logging.error('Webserver crashed: %s', error, exc_info=True)
        sys.exit(1)
    logging.info('shutting down webserver v%s', config.version)
    sys.exit(0)
