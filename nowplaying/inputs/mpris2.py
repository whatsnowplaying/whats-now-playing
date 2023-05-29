#!/usr/bin/env python3
''' Process MPRIS2 exposed metadata

    * Mixxx: This is based upon https://github.com/mixxxdj/mixxx/pull/3483 +
             a custom patch to add url support
    * VLC: out of the box

 '''

import collections
import logging
import pathlib
import sys
import urllib
import urllib.request

try:
    import dbus
    DBUS_STATUS = True
except ImportError:
    DBUS_STATUS = False

from PySide6.QtCore import Qt  # pylint: disable=no-name-in-module
from nowplaying.inputs import InputPlugin

MPRIS2_BASE = 'org.mpris.MediaPlayer2'


class MPRIS2Handler():
    ''' Read metadata from MPRIS2 '''

    def __init__(self, service=None):
        self.service = None
        self.bus = None
        self.proxy = None
        self.meta = None
        self.metadata = None

        if not DBUS_STATUS:
            self.dbus_status = False
            return

        self.dbus_status = True

        if service:
            self.resetservice(service)

    def resetservice(self, service=None):
        ''' reset the service name '''
        self.service = service

        if '.' not in service and not self.find_service():
            logging.error('%s is not a known MPRIS2 service.', service)
            return

        self.bus = dbus.SessionBus()
        try:
            self.proxy = self.bus.get_object(f'{MPRIS2_BASE}.{self.service}',
                                             '/org/mpris/MediaPlayer2')
        except dbus.exceptions.DBusException as error:
            logging.error(error)

        self.meta = None
        self.metadata = {}

    def getplayingtrack(self):  # pylint: disable=too-many-branches
        ''' get the currently playing song '''

        # start with a blank slate to prevent
        # data bleeding
        builddata = {'artist': None, 'title': None, 'filename': None}
        if not DBUS_STATUS:
            return builddata

        artist = None

        # if NowPlaying is launched before our service...
        if not self.proxy:
            self.resetservice(self.service)
        if not self.proxy:
            logging.error('Unknown service: %s', self.service)
            return builddata

        properties = dbus.Interface(self.proxy, dbus_interface='org.freedesktop.DBus.Properties')
        if not properties:
            logging.error('Unknown service: %s', self.service)
            return builddata

        try:
            self.meta = properties.GetAll(f'{MPRIS2_BASE}.Player')['Metadata']
        except dbus.exceptions.DBusException as error:
            # likely had a service and but now it is gone
            logging.error(error)
            self.metadata = {}
            self.proxy = None
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
            builddata['duration'] = int(length)

        if tracknumber := self.meta.get('xesam:tracknumber'):
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

    def get_mpris2_services(self):
        ''' list of all MPRIS2 services '''

        if not self.dbus_status:
            return []

        services = []
        bus = dbus.SessionBus()
        for reglist in bus.list_names():
            if reglist.startswith(MPRIS2_BASE):
                stripped = reglist.replace(f'{MPRIS2_BASE}.', '')
                services.append(stripped)
        return services

    def find_service(self):
        ''' try to find our service '''

        if not self.dbus_status:
            return False

        services = self.get_mpris2_services()
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

    def gethandler(self):
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
        self.mpris2.resetservice(service=sameservice)
        return

    async def start(self):
        ''' configure MPRIS2 client '''
        self.gethandler()

    async def getplayingtrack(self):
        ''' wrapper to call getplayingtrack '''
        self.gethandler()

        if self.mpris2:
            return self.mpris2.getplayingtrack()
        return {}

    async def getrandomtrack(self, playlist):
        ''' not supported '''
        return None

    def load_settingsui(self, qwidget):
        ''' populate the combobox '''
        if not self.dbus_status or not self.mpris2:
            return
        currentservice = self.config.cparser.value('mpris2/service')
        servicelist = self.mpris2.get_mpris2_services()
        qwidget.list_widget.clear()
        qwidget.list_widget.addItems(servicelist)
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
            qwidget.setText('Not available.')
            return

        qwidget.setText('This plugin provides support for MPRIS2 '
                        'compatible software on Linux and other DBus systems.')


def main():
    ''' entry point as a standalone app'''
    logging.basicConfig(level=logging.DEBUG)
    if not DBUS_STATUS:
        print('No dbus')
        sys.exit(1)
    mpris2 = MPRIS2Handler()

    if len(sys.argv) == 2:
        mpris2.resetservice(sys.argv[1])
        (artist, title, filename) = mpris2.getplayingtrack()
        print(f'Artist: {artist} | Title: {title} | Filename: {filename}')
        data = mpris2.getplayingtrack()
        if 'coverimageraw' in data:
            print('Got coverart')
            del data['coverimageraw']
        print(data)
    else:

        print(mpris2.get_mpris2_services())


if __name__ == "__main__":
    main()
