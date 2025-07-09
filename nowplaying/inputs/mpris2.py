#!/usr/bin/env python3
''' Process MPRIS2 exposed metadata

    * Mixxx: This is based upon https://github.com/mixxxdj/mixxx/pull/3483 +
             a custom patch to add url support
    * VLC: out of the box

 '''

import asyncio
import collections
import contextlib
import logging
import pathlib
import sys
import urllib
import urllib.parse

try:
    from dbus_fast.aio import MessageBus
    from dbus_fast import BusType
    from dbus_fast.unpack import unpack_variants
    DBUS_STATUS = True
except ImportError:
    DBUS_STATUS = False

from multidict import CIMultiDict

from PySide6.QtCore import Qt  # pylint: disable=no-name-in-module
from nowplaying.inputs import InputPlugin

MPRIS2_BASE = 'org.mpris.MediaPlayer2'


class MPRIS2Handler:
    ''' Read metadata from MPRIS2 '''

    def __init__(self, service=None):
        self.service = None
        self.bus = None
        self.introspection = None
        self.meta = None
        self.metadata = {}

        if not DBUS_STATUS:
            self.dbus_status = False
            return

        self.dbus_status = True

        if service:
            self.service = service

    async def resetservice(self, service=None):
        ''' reset the service name '''
        self.service = service

        if '.' not in service and not await self.find_service():
            logging.error('%s is not a known MPRIS2 service.', service)
            return

        try:
            if not self.bus:
                self.bus = await MessageBus(bus_type=BusType.SESSION).connect()

            self.introspection = await self.bus.introspect(f'{MPRIS2_BASE}.{self.service}',
                                                           '/org/mpris/MediaPlayer2')
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error('D-Bus connection error: %s', error)
            self.introspection = None

        self.meta = None
        self.metadata = {}

    async def getplayingtrack(self):  # pylint: disable=too-many-branches
        ''' get the currently playing song '''

        # start with a blank slate to prevent
        # data bleeding
        builddata = {'artist': None, 'title': None, 'filename': None}
        if not DBUS_STATUS or not self.bus:
            return builddata

        artist = None

        # if NowPlaying is launched before our service...
        if not self.introspection:
            await self.resetservice(self.service)
        if not self.introspection:
            logging.error('Unknown service: %s', self.service)
            return builddata

        try:
            # Get the Properties interface
            props_obj = self.bus.get_proxy_object(f'{MPRIS2_BASE}.{self.service}',
                                                  '/org/mpris/MediaPlayer2', self.introspection)
            properties = props_obj.get_interface('org.freedesktop.DBus.Properties')

            # Get all Player properties
            result = await properties.call_get_all(f'{MPRIS2_BASE}.Player')
            unpacked_result = unpack_variants(result)
            # Convert to case-insensitive dict for robust field lookups
            self.meta = CIMultiDict(unpacked_result.get('Metadata', {}))
        except Exception as error:  # pylint: disable=broad-exception-caught
            # likely had a service and but now it is gone
            logging.error('D-Bus error: %s', error)
            self.metadata = {}
            self.introspection = None
            if self.bus:
                self.bus.disconnect()
                self.bus = None
            return builddata

        if artists := self.meta.get('xesam:artist'):
            artists = collections.deque(artists)
            artist = str(artists.popleft())
            while len(artists) > 0:
                artist = f'{artist}/{str(artists.popleft())}'
            if artist:
                builddata['artist'] = artist

        title = self.meta.get('xesam:title')
        if title:
            title = str(title)
            builddata['title'] = title

        if self.meta.get('xesam:album'):
            builddata['album'] = str(self.meta.get('xesam:album'))

        if length := self.meta.get('mpris:length'):
            with contextlib.suppress(ValueError, TypeError):
                # Convert from microseconds to seconds
                builddata['duration'] = int(length) // 1000000
        if tracknumber := self.meta.get('xesam:trackNumber'):
            with contextlib.suppress(ValueError, TypeError):
                builddata['track'] = int(tracknumber)
        filename = self.meta.get('xesam:url')
        if filename and 'file://' in filename:
            filename = urllib.parse.unquote(filename)
            builddata['filename'] = filename.replace('file://', '')

        # some MPRIS2 implementations will give the filename as the title
        # if it doesn't have one. We need to avoid that.
        if title == filename or title and pathlib.Path(title).exists():
            builddata['title'] = None
            title = None

        # it looks like there is a race condition in mixxx
        # probably should make this an option in the MPRIS2
        # handler but for now just comment it out
        # arturl = self.meta.get('mpris:artUrl')
        # if arturl:
        #     with urllib.request.urlopen(arturl) as coverart:
        #         builddata['coverimageraw'] = coverart.read()
        self.metadata = builddata
        return self.metadata

    async def get_mpris2_services(self):
        ''' list of all MPRIS2 services '''

        if not self.dbus_status:
            return []

        try:
            if not self.bus:
                self.bus = await MessageBus(bus_type=BusType.SESSION).connect()

            # Get the DBus interface to list names
            introspection = await self.bus.introspect('org.freedesktop.DBus',
                                                      '/org/freedesktop/DBus')
            dbus_obj = self.bus.get_proxy_object('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                                 introspection)
            dbus_interface = dbus_obj.get_interface('org.freedesktop.DBus')

            names = await dbus_interface.call_list_names()

            services = []
            for name in names:
                if name.startswith(MPRIS2_BASE):
                    stripped = name.replace(f'{MPRIS2_BASE}.', '')
                    services.append(stripped)
            return services
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error('Error listing MPRIS2 services: %s', error)
            return []

    async def find_service(self):
        ''' try to find our service '''

        if not self.dbus_status:
            return False

        services = await self.get_mpris2_services()
        for reglist in services:
            if self.service in reglist:
                self.service = reglist
                return True
        return False


class Plugin(InputPlugin):
    ''' handler for NowPlaying '''

    def __init__(self, config=None, qsettings=None):

        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "MPRIS2"
        self.mpris2 = None
        self.service = None

        if not DBUS_STATUS:
            self.dbus_status = False
            self.available = False
            return

        self.mpris2 = MPRIS2Handler()
        self.dbus_status = True

    def install(self):
        ''' Auto-install for MPRIS2 '''
        return False

    async def gethandler(self):
        ''' setup the MPRIS2Handler for this session '''

        if not self.mpris2 or not self.dbus_status:
            return

        sameservice = self.config.cparser.value('mpris2/service')

        if not sameservice:
            self.service = None
            self.mpris2 = None
            return

        if self.service and self.service == sameservice:
            return

        logging.debug('new service = %s', sameservice)
        self.service = sameservice
        await self.mpris2.resetservice(service=sameservice)

    async def start(self):
        ''' configure MPRIS2 client '''
        await self.gethandler()

    async def getplayingtrack(self):
        ''' wrapper to call getplayingtrack '''
        await self.gethandler()

        if self.mpris2:
            await asyncio.sleep(.5)
            return await self.mpris2.getplayingtrack()
        return {}

    async def getrandomtrack(self, playlist):
        ''' not supported '''
        return None

    def load_settingsui(self, qwidget):
        ''' populate the combobox '''
        if not self.dbus_status or not self.mpris2:
            return

        services = asyncio.run(MPRIS2Handler().get_mpris2_services())
        currentservice = self.config.cparser.value('mpris2/service')
        qwidget.list_widget.clear()
        qwidget.list_widget.addItems(services)
        if curbutton := qwidget.list_widget.findItems(currentservice, Qt.MatchContains):
            curbutton[0].setSelected(True)

    def save_settingsui(self, qwidget):
        ''' save the combobox '''
        if not self.dbus_status:
            return
        if curitem := qwidget.list_widget.currentItem():
            curtext = curitem.text()
            self.config.cparser.setValue('mpris2/service', curtext)

    def desc_settingsui(self, qwidget):
        ''' description '''
        if not self.dbus_status:
            qwidget.setText('Not available - dbus-fast package required.')
            return

        qwidget.setText('This plugin provides support for MPRIS2 '
                        'compatible software on Linux and other DBus systems. '
                        'Now using dbus-fast for better performance.')

    async def cleanup(self):
        ''' Clean up resources '''
        if self.mpris2 and self.mpris2.bus:
            self.mpris2.bus.disconnect()


async def main():
    ''' entry point as a standalone app'''
    logging.basicConfig(level=logging.DEBUG)
    if not DBUS_STATUS:
        print('No dbus-fast - install with: pip install dbus-fast')
        sys.exit(1)

    mpris2 = MPRIS2Handler()

    if len(sys.argv) == 2:
        await mpris2.resetservice(sys.argv[1])
        data = await mpris2.getplayingtrack()

        if data.get('artist') or data.get('title'):
            print(f'Artist: {data.get("artist")} | Title: {data.get("title")} | '
                  f'Filename: {data.get("filename")}')

        if 'coverimageraw' in data:
            print('Got coverart')
            del data['coverimageraw']
        print(data)
    else:
        services = await mpris2.get_mpris2_services()
        print('Available MPRIS2 services:')
        for service in services:
            print(f'  {service}')

    # Clean up
    if mpris2.bus:
        mpris2.bus.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
