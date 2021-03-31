#!/usr/bin/env python3
''' web server code '''

# pylint: disable=no-name-in-module

from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import os
import pathlib
from socketserver import ThreadingMixIn
import tempfile
import threading
import time
import urllib.parse

from PySide2.QtCore import \
                            Signal, \
                            QThread

CONFIG = None


class WebHandler(BaseHTTPRequestHandler):
    ''' Custom handler for built-in webserver '''

    counter = 0

    def do_GET(self):  # pylint: disable=invalid-name
        '''
            HTTP GET
                - if there is an index.htm file to read, give it out
                  then delete it
                - if not, have our reader check back in 5 seconds

            Note that there is very specific path information
            handling here.  So any chdir() that happens MUST
            be this directory.

            Also, doing it this way means the webserver can only ever
            share specific content.
        '''

        global CONFIG  # pylint: disable=global-statement

        # see what was asked for
        parsedrequest = urllib.parse.urlparse(self.path)

        WebHandler.counter += 1
        threading.current_thread().name = f'WebHandler-{WebHandler.counter}'

        if parsedrequest.path in ['/favicon.ico']:
            self.send_response(200)
            self.send_header('Content-type', 'image/x-icon')
            self.end_headers()
            with open(CONFIG.iconfile, 'rb') as iconfh:
                self.wfile.write(iconfh.read())
            return

        if parsedrequest.path in ['/', 'index.html', 'index.htm']:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            if os.path.isfile('index.htm'):
                with open('index.htm', 'rb') as indexfh:
                    self.wfile.write(indexfh.read())
                os.unlink('index.htm')
                return

            self.wfile.write(b'<!doctype html><html lang="en">')
            self.wfile.write(
                b'<head><meta http-equiv="refresh" content="5" ></head>')
            self.wfile.write(b'<body></body></html>\n')
            return

        if parsedrequest.path in ['/index.txt']:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            with open(CONFIG.file, 'rb') as textfh:
                self.wfile.write(textfh.read())
            return

        if parsedrequest.path in ['/cover.jpg'
                                  ] and os.path.isfile('cover.jpg'):
            self.send_response(200, 'OK')
            self.send_header('Content-type', 'image/jpeg')
            self.end_headers()
            with open('cover.jpg', 'rb') as indexfh:
                self.wfile.write(indexfh.read())
            return

        if parsedrequest.path in ['/cover.png'
                                  ] and os.path.isfile('cover.png'):
            self.send_response(200, 'OK')
            self.send_header('Content-type', 'image/png')
            self.end_headers()
            with open('cover.png', 'rb') as indexfh:
                self.wfile.write(indexfh.read())
            return

        self.send_error(404)

    def log_message(self, format, *args):  ## pylint: disable=redefined-builtin
        logging.info("%s - - [%s] %s\n", self.address_string(),
                     self.log_date_time_string(), format % args)


class ThreadingWebServer(ThreadingMixIn, HTTPServer):
    ''' threaded webserver object '''
    daemon_threads = True
    allow_reuse_address = True


class WebServer(QThread):
    ''' Now Playing built-in web server using custom handler '''

    webenable = Signal(bool)

    def __init__(self, parent=None, config=None):
        global CONFIG  # pylint: disable=global-statement

        CONFIG = config

        QThread.__init__(self, parent)
        self.server = None
        self.endthread = False

    def run(self):  # pylint: disable=too-many-branches, too-many-statements
        '''
            Configure a webserver.

            The sleeps are here to make sure we don't
            tie up a CPU constantly checking on
            status.  If we cannot open the port or
            some other situation, we bring everything
            to a halt by triggering pause.

            But in general:

                - web server thread starts
                - check if web serving is running
                - if so, open ANOTHER thread (MixIn) that will
                  serve connections concurrently
                - if the settings change, then another thread
                  will call into this one via stop() to
                  shutdown the (blocking) serve_forever()
                - after serve_forever, effectively restart
                  the loop, checking what values changed, and
                  doing whatever is necessary
                - land back into serve_forever
                - rinse/repeat

        '''
        global CONFIG  # pylint: disable=global-statement

        threading.current_thread().name = 'WebServerControl'

        while not self.endthread:
            logging.debug('Starting main loop')
            CONFIG.get()

            while CONFIG.paused or not CONFIG.httpenabled:
                time.sleep(5)
                CONFIG.get()
                if self.endthread:
                    break

            if self.endthread:
                self.stop()
                break

            if not CONFIG.usinghttpdir:
                logging.debug('No web server dir?!?')
                CONFIG.setusinghttpdir(tempfile.gettempdir())
            logging.info('Using web server dir %s', CONFIG.usinghttpdir)
            if not os.path.exists(CONFIG.usinghttpdir):
                try:
                    logging.debug('Making %s as it does not exist',
                                  CONFIG.usinghttpdir)
                    pathlib.Path(CONFIG.usinghttpdir).mkdir(parents=True,
                                                            exist_ok=True)
                except Exception as error:  # pylint: disable=broad-except
                    logging.error('Web server threw exception! %s', error)
                    self.webenable.emit(False)

            os.chdir(CONFIG.usinghttpdir)

            try:
                self.server = ThreadingWebServer(('0.0.0.0', CONFIG.httpport),
                                                 WebHandler)
            except Exception as error:  # pylint: disable=broad-except
                logging.error(
                    'Web server threw exception on thread create: %s', error)
                self.webenable.emit(False)

            try:
                if self.server:
                    self.server.serve_forever()
            except KeyboardInterrupt:
                pass
            except Exception as error:  # pylint: disable=broad-except
                logging.error('Web server threw exception after forever: %s',
                              error)
            finally:
                if self.server:
                    self.server.shutdown()

    def stop(self):
        ''' method to stop the thread '''
        logging.debug('WebServer asked to stop or reconfigure')
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def __del__(self):
        logging.debug('Web server thread is being killed!')
        self.endthread = True
        self.stop()
        self.wait()
