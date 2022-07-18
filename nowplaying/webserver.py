#!/usr/bin/env python3
''' WebServer process '''
import asyncio
import base64
import logging
import logging.config
import os
import sys
import time
import weakref

import aiohttp
from aiohttp import web, WSCloseCode
#import aiohttp_debugtoolbar
#from aiohttp_debugtoolbar import toolbar_middleware_factory
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
import nowplaying.utils

INDEXREFRESH = \
    '<!doctype html><html lang="en">' \
    '<head><meta http-equiv="refresh" content="5" ></head>' \
    '<body></body></html>\n'


TRANSPARENT_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC'\
                  '1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAA'\
                  'ASUVORK5CYII='
TRANSPARENT_PNG_BIN = base64.b64decode(TRANSPARENT_PNG)

MAGICSTOPURL = 'STOPSERVER'


class WebHandler():  # pylint: disable=too-many-instance-attributes
    ''' aiohttp built server that does both http and websocket '''

    def __init__(self, event, metadbfile=None, webdbfile=None, testmode=False):
        self.testmode = testmode
        self.webdbfile = webdbfile
        self.metadbfile = metadbfile
        config = nowplaying.config.ConfigFile(testmode=testmode)
        self.port = config.cparser.value('weboutput/httpport', type=int)
        self.runner = None
        self.app = self.create_app()
        self.tasks = set()
        self.event = event
        self.create_database()

        logging.info('Secret url to quit websever: %s', MAGICSTOPURL)

        if not testmode:
            task = asyncio.create_task(
                self.start_server(host='0.0.0.0', port=self.port))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.remove)
            task = asyncio.create_task(self.stopevent())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.remove)

    def create_database(self):
        ''' create the web db for tracking what has been sent '''
        if not self.webdbfile:
            self.webdbfile = os.path.join(
                QStandardPaths.standardLocations(
                    QStandardPaths.CacheLocation)[0], 'web.db')
        logging.debug('Using %s as web databasefile', self.webdbfile)
        if os.path.exists(self.webdbfile):
            try:
                os.unlink(self.webdbfile)
            except PermissionError as error:
                logging.error('WebServer process already running?')
                logging.error(error)
                sys.exit(1)

    async def stopevent(self):
        ''' task to wait for the stop event '''
        await self.event.wait()
        await self.forced_stop()

    async def indexhtm_handler(self, request):  # pylint: disable=unused-argument
        ''' handle static index.html '''
        htmloutput = ""
        request.app['config'].get()
        metadata = request.app['metadb'].read_last_meta()
        lastid = await self.getlastid(request)
        template = request.app['config'].cparser.value(
            'weboutput/htmltemplate')
        once = request.app['config'].cparser.value('weboutput/once', type=bool)

        # | dbid  |  lastid | once |
        # |   x   |   NA    |      |  -> update lastid, send template
        # |   x   |  diff   |   NA |  -> update lastid, send template
        # |   x   |  same   |      |  -> send template
        # |   x   |  same   |   x  |  -> send refresh
        # |       |   NA    |      |  -> send refresh because not ready or something broke

        if not metadata or 'dbid' not in metadata or not template:
            return web.Response(status=202,
                                content_type='text/html',
                                text=INDEXREFRESH)

        if lastid == 0 or lastid != metadata['dbid'] or not once:
            await self.setlastid(request, metadata['dbid'])
            try:
                templatehandler = nowplaying.utils.TemplateHandler(
                    filename=template)
                htmloutput = templatehandler.generate(metadata)
            except Exception as error:  #pylint: disable=broad-except
                logging.error('indexhtm_handler: %s', error)
                htmloutput = INDEXREFRESH
            return web.Response(content_type='text/html', text=htmloutput)

        return web.Response(content_type='text/html', text=INDEXREFRESH)

    async def setlastid(self, request, lastid):  # pylint: disable=no-self-use
        ''' get the lastid sent by http/html '''
        await request.app['statedb'].execute(
            'UPDATE lastprocessed SET lastid = ? WHERE id=1', [lastid])
        await request.app['statedb'].commit()

    async def getlastid(self, request):  # pylint: disable=no-self-use
        ''' get the lastid sent by http/html '''
        cursor = await request.app['statedb'].execute(
            'SELECT lastid FROM lastprocessed WHERE id=1')
        row = await cursor.fetchone()
        if not row:
            lastid = 0
        else:
            lastid = row[0]
        await cursor.close()
        return lastid

    async def indextxt_handler(self, request):  # pylint: disable=no-self-use
        ''' handle static index.txt '''
        logging.debug('Called /index.txt')
        metadata = request.app['metadb'].read_last_meta()
        txtoutput = ""
        if metadata:
            request.app['config'].get()
            try:
                templatehandler = nowplaying.utils.TemplateHandler(
                    filename=request.app['config'].cparser.value(
                        'textoutput/txttemplate'))
                txtoutput = templatehandler.generate(metadata)
            except Exception as error:  #pylint: disable=broad-except
                logging.error('indextxt_handler: %s', error)
                txtoutput = ''
        return web.Response(text=txtoutput)

    async def favicon_handler(self, request):  # pylint: disable=no-self-use
        ''' handle favicon.ico '''
        return web.FileResponse(path=request.app['config'].iconfile)

    async def cover_handler(self, request):  # pylint: disable=no-self-use
        ''' handle cover image '''
        metadata = request.app['metadb'].read_last_meta()
        if 'coverimageraw' in metadata:
            return web.Response(content_type='image/png',
                                body=metadata['coverimageraw'])
        # rather than return an error, just send a transparent PNG
        # this makes the client code significantly easier
        return web.Response(content_type='image/png', body=TRANSPARENT_PNG_BIN)

    async def api_v1_last_handler(self, request):  # pylint: disable=no-self-use
        ''' handle static index.txt '''
        metadata = request.app['metadb'].read_last_meta()
        # if there is an image, encode it as base64
        if 'coverimageraw' in metadata:
            metadata['coverimagebase64'] = base64.b64encode(
                metadata['coverimageraw']).decode('utf-8')
            del metadata['coverimageraw']
        del metadata['dbid']
        return web.json_response(metadata)

    async def websocket_lastjson_handler(self, request, websocket):  # pylint: disable=no-self-use
        ''' handle singular websocket request '''
        metadata = request.app['metadb'].read_last_meta()
        # if there is an image, encode it as base64
        if 'coverimageraw' in metadata:
            metadata['coverimagebase64'] = base64.b64encode(
                metadata['coverimageraw']).decode('utf-8')
            del metadata['coverimageraw']
        del metadata['dbid']
        await websocket.send_json(metadata)

    async def websocket_streamer(self, request):  # pylint: disable=no-self-use
        ''' handle continually streamed updates '''

        async def do_update(websocket, database):
            # early launch can be a bit weird so
            # pause a bit
            await asyncio.sleep(1)
            metadata = None
            while not metadata:
                metadata = database.read_last_meta()
                await asyncio.sleep(1)
            if 'coverimageraw' in metadata:
                metadata['coverimagebase64'] = base64.b64encode(
                    metadata['coverimageraw']).decode('utf-8')
                del metadata['coverimageraw']
            else:
                # for some reason, just sending the string doesn't always work :shrug:
                metadata['coverimagebase64'] = base64.b64encode(
                    TRANSPARENT_PNG_BIN).decode('utf-8')
            del metadata['dbid']
            await websocket.send_json(metadata)
            return time.time()

        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app['websockets'].add(websocket)

        try:
            mytime = await do_update(websocket, request.app['metadb'])
            while True:
                while mytime > request.app['watcher'].updatetime:
                    await asyncio.sleep(1)

                mytime = await do_update(websocket, request.app['metadb'])
                await asyncio.sleep(1)
        except Exception as error:  #pylint: disable=broad-except
            logging.error('websocket streamer exception: %s', error)
        finally:
            logging.debug('ws-streamer: ended in finally')
            await websocket.close()
            logging.debug('ws-streamer: discarding websocket')
            request.app['websockets'].discard(websocket)
            logging.debug('ws-streamer: ending finally block')
        logging.debug('ws-streamer: ending session')
        return websocket

    async def websocket_handler(self, request):
        ''' handle inbound websockets '''
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app['websockets'].add(websocket)
        try:
            async for msg in websocket:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == 'close':
                        await websocket.close()
                    elif msg.data == 'last':
                        logging.debug('got last')
                        await self.websocket_lastjson_handler(
                            request, websocket)
                    else:
                        await websocket.send_str(
                            'some websocket message payload')
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logging.error('ws connection closed with exception %s',
                                  websocket.exception())
        except Exception as error:  #pylint: disable=broad-except
            logging.error('Websocket handler error: %s', error)
        finally:
            logging.debug('ended in finally')
            await websocket.close()
            logging.debug('ws-handler closed; calling discard')
            request.app['websockets'].discard(websocket)
            logging.debug('ws-handler exited finally')
        logging.debug('ws-handler: ending session')
        return websocket

    def create_app(self):
        ''' setup http routing '''
        app = web.Application()
        #aiohttp_debugtoolbar.setup(app)
        app['websockets'] = weakref.WeakSet()
        app.on_startup.append(self.on_startup)
        app.on_shutdown.append(self.on_shutdown)
        app.add_routes([
            web.get('/', self.indexhtm_handler),
            web.get('/v1/last', self.api_v1_last_handler),
            web.get('/cover.png', self.cover_handler),
            web.get('/favicon.ico', self.favicon_handler),
            web.get('/index.htm', self.indexhtm_handler),
            web.get('/index.html', self.indexhtm_handler),
            web.get('/index.txt', self.indextxt_handler),
            web.get('/ws', self.websocket_handler),
            web.get('/wsstream', self.websocket_streamer),
            web.get(f'/{MAGICSTOPURL}', self.stop_server)
        ])
        return app

    async def start_server(self, host="127.0.0.1", port=8899):
        ''' start our server '''
        if not self.app:
            self.app = self.create_app()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host, port)
        await site.start()
        logging.debug('webserver here')
        await self.event.wait()
        await self.runner.cleanup()

    async def on_startup(self, app):
        ''' setup app connections '''
        app['config'] = nowplaying.config.ConfigFile(testmode=self.testmode)
        if self.testmode:
            logging.debug('TESTMODE: templatedir=%s, metadb=%s webdb=%s',
                          app['config'].templatedir, self.metadbfile,
                          self.webdbfile)
            app['config'].templatedir = os.path.join(
                os.path.dirname(self.metadbfile), 'templates')
            app['metadb'] = nowplaying.db.MetadataDB(
                databasefile=self.metadbfile)
        else:
            app['metadb'] = nowplaying.db.MetadataDB()
            logging.debug(' templatedir=%s, metadb=%s webdb=%s',
                          app['config'].templatedir,
                          app['metadb'].databasefile, self.webdbfile)
        app['watcher'] = app['metadb'].watcher()
        app['watcher'].start()
        app['statedb'] = await aiosqlite.connect(self.webdbfile)
        app['statedb'].row_factory = aiosqlite.Row
        cursor = await app['statedb'].cursor()
        await cursor.execute('CREATE TABLE IF NOT EXISTS lastprocessed ('
                             'id INTEGER, '
                             'lastid INTEGER '
                             ')')
        await cursor.execute(
            'INSERT INTO lastprocessed (id, lastid) VALUES (1,0)')
        await app['statedb'].commit()

    async def on_shutdown(self, app):  # pylint: disable=no-self-use
        ''' handle shutdown '''
        for websocket in set(app['websockets']):
            await websocket.close(code=WSCloseCode.GOING_AWAY,
                                  message='Server shutdown')
        await app['statedb'].close()
        app['watcher'].stop()
        logging.debug('finished on_shutdown')

    async def stop_server(self, request):  # pylint: disable=unused-argument, no-self-use
        ''' stop our server '''
        await request.app.shutdown()
        await request.app.cleanup()
        logging.debug('finished stop_server')

    async def forced_stop(self):
        ''' trigger a stop '''
        await self.runner.cleanup()
        logging.debug('finished forced_stop')
