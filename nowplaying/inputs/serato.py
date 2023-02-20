#!/usr/bin/env python3
''' A _very_ simple and incomplete parser for Serato Live session files '''

#pylint: disable=too-many-lines

import asyncio
import copy
import datetime
import logging
import os
import re
import pathlib
import random
import struct
import time

import aiofiles
import lxml.html
import requests

from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import PatternMatchingEventHandler

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

from nowplaying.inputs import InputPlugin
from nowplaying.exceptions import PluginVerifyError

# when in local mode, these are shared variables between threads
LASTPROCESSED = 0
PARSEDSESSIONS = []

TIDAL_FORMAT = re.compile('^_(.*).tdl')


class SeratoCrateReader:
    ''' read a Serato crate (not smart crate) -
        based on https://gist.github.com/kerrickstaley/8eb04988c02fa7c62e75c4c34c04cf02 '''

    def __init__(self, filename):
        self.decode_func_full = {
            None: self._decode_struct,
            'vrsn': self._decode_unicode,
            'sbav': self._noop,
            'rart': self._noop,
            'rlut': self._noop,
            'rurt': self._noop,
        }

        self.decode_func_first = {
            'o': self._decode_struct,
            't': self._decode_unicode,
            'p': self._decode_unicode,
            'u': self._decode_unsigned,
            'b': self._noop,
        }

        self.cratepath = pathlib.Path(filename)
        self.crate = None

    def _decode_struct(self, data):
        ''' decode the structures of the crate'''
        ret = []
        i = 0
        while i < len(data):
            tag = data[i:i + 4].decode('ascii')
            length = struct.unpack('>I', data[i + 4:i + 8])[0]
            value = data[i + 8:i + 8 + length]
            value = self._datadecode(value, tag=tag)
            ret.append((tag, value))
            i += 8 + length
        return ret

    @staticmethod
    def _decode_unicode(data):
        return data.decode('utf-16-be')

    @staticmethod
    def _decode_unsigned(data):
        return struct.unpack('>I', data)[0]

    @staticmethod
    def _noop(data):
        return data

    def _datadecode(self, data, tag=None):
        if tag in self.decode_func_full:
            decode_func = self.decode_func_full[tag]
        else:
            decode_func = self.decode_func_first[tag[0]]

        return decode_func(data)

    async def loadcrate(self):
        ''' load/overwrite current crate '''
        async with aiofiles.open(self.cratepath, 'rb') as cratefhin:
            self.crate = self._datadecode(await cratefhin.read())

    def getfilenames(self):
        ''' get the filenames from this crate '''
        if not self.crate:
            logging.error('crate has not been loaded')
            return None
        filelist = []
        anchor = self.cratepath.anchor
        for tag in self.crate:
            if tag[0] != 'otrk':
                continue
            otrk = tag[1]
            for subtag in otrk:
                if subtag[0] != 'ptrk':
                    continue
                filelist.extend(f'{anchor}{filepart}'
                                for filepart in subtag[1:])
        return filelist


class SeratoSessionReader:
    ''' read a Serato session file '''

    def __init__(self):
        self.decode_func_full = {
            None: self._decode_struct,
            'vrsn': self._decode_unicode,
            'adat': self._decode_adat,
            'oent': self._decode_struct,
        }

        self.decode_func_first = {
            'o': self._decode_struct,
            't': self._decode_unicode,
            'p': self._decode_unicode,
            'u': self._decode_unsigned,
            'b': self._noop,
        }

        self._adat_func = {
            2: ['pathstr', self._decode_unicode],
            3: ['location', self._decode_unicode],
            4: ['filename', self._decode_unicode],
            6: ['title', self._decode_unicode],
            7: ['artist', self._decode_unicode],
            8: ['album', self._decode_unicode],
            9: ['genre', self._decode_unicode],
            10: ['length', self._decode_unicode],
            11: ['filesize', self._decode_unicode],
            13: ['bitrate', self._decode_unicode],
            14: ['frequency', self._decode_unicode],
            15: ['bpm', self._decode_unsigned],
            16: ['field16', self._decode_hex],
            17: ['comments', self._decode_unicode],
            18: ['lang', self._decode_unicode],
            19: ['grouping', self._decode_unicode],
            20: ['remixer', self._decode_unicode],
            21: ['label', self._decode_unicode],
            22: ['composer', self._decode_unicode],
            23: ['date', self._decode_unicode],
            28: ['starttime', self._decode_timestamp],
            29: ['endtime', self._decode_timestamp],
            31: ['deck', self._decode_unsigned],
            45: ['playtime', self._decode_unsigned],
            48: ['sessionid', self._decode_unsigned],
            50: ['played', self._decode_bool],
            51: ['key', self._decode_unicode],
            52: ['added', self._decode_bool],
            53: ['updatedat', self._decode_timestamp],
            63: ['playername', self._decode_unicode],
            64: ['commentname', self._decode_unicode],
        }

        self.sessiondata = []

    def _decode_adat(self, data):
        ret = {}
        #i = 0
        #tag = struct.unpack('>I', data[0:i + 4])[0]
        #length = struct.unpack('>I', data[i + 4:i + 8])[0]
        i = 8
        while i < len(data) - 8:
            tag = struct.unpack('>I', data[i + 4:i + 8])[0]
            length = struct.unpack('>I', data[i + 8:i + 12])[0]
            value = data[i + 12:i + 12 + length]
            try:
                field = self._adat_func[tag][0]
                value = self._adat_func[tag][1](value)
            except KeyError:
                field = f'unknown{tag}'
                value = self._noop(value)
            ret[field] = value
            i += 8 + length
        if not ret.get('filename'):
            ret['filename'] = ret.get('pathstr')
        return ret

    def _decode_struct(self, data):
        ''' decode the structures of the session'''
        ret = []
        i = 0
        while i < len(data):
            tag = data[i:i + 4].decode('ascii')
            length = struct.unpack('>I', data[i + 4:i + 8])[0]
            value = data[i + 8:i + 8 + length]
            value = self._datadecode(value, tag=tag)
            ret.append((tag, value))
            i += 8 + length
        return ret

    @staticmethod
    def _decode_unicode(data):
        return data.decode('utf-16-be')[:-1]

    @staticmethod
    def _decode_timestamp(data):
        try:
            timestamp = struct.unpack('>I', data)[0]
        except struct.error:
            timestamp = struct.unpack('>Q', data)[0]
        return datetime.datetime.fromtimestamp(timestamp)

    @staticmethod
    def _decode_hex(data):
        ''' read a string, then encode as hex '''
        return data.encode('utf-8').hex()

    @staticmethod
    def _decode_bool(data):
        ''' true/false handling '''
        return bool(struct.unpack('b', data)[0])

    @staticmethod
    def _decode_unsigned(data):
        try:
            field = struct.unpack('>I', data)[0]
        except struct.error:
            field = struct.unpack('>Q', data)[0]
        return field

    @staticmethod
    def _noop(data):
        return data

    def _datadecode(self, data, tag=None):
        if tag in self.decode_func_full:
            decode_func = self.decode_func_full[tag]
        else:
            decode_func = self.decode_func_first[tag[0]]
        return decode_func(data)

    async def loadsessionfile(self, filename):
        ''' load/extend current session '''
        async with aiofiles.open(filename, 'rb') as sessionfhin:
            self.sessiondata.extend(self._datadecode(await sessionfhin.read()))

    def condense(self):
        ''' shrink to just adats '''
        adatdata = []
        if not self.sessiondata:
            logging.error('session has not been loaded')
            return
        for sessiontuple in self.sessiondata:
            if sessiontuple[0] == 'oent':
                adatdata.extend(oentdata[1] for oentdata in sessiontuple[1]
                                if oentdata[0] == 'adat')

        self.sessiondata = adatdata

    def sortsession(self):
        ''' sort them by starttime '''
        records = sorted(self.sessiondata, key=lambda x: x.get('starttime'))
        self.sessiondata = records

    def getadat(self):
        ''' get the filenames from this session '''
        if not self.sessiondata:
            logging.error('session has not been loaded')
            return
        yield from self.sessiondata

    def getreverseadat(self):
        ''' same as getadat, but reversed order '''
        if not self.sessiondata:
            logging.error('session has not been loaded')
            return
        yield from reversed(self.sessiondata)


class SeratoHandler():  #pylint: disable=too-many-instance-attributes
    ''' Generic handler to get the currently playing track.

        To use Serato Live Playlits, construct with:
            self.seratourl='url')


        To use local Serato directory, construct with:
            self.seratodir='/path/to/_Serato_'

    '''

    def __init__(  #pylint: disable=too-many-arguments
            self,
            mixmode='oldest',
            pollingobserver=False,
            seratodir=None,
            seratourl=None,
            testmode=False):
        global LASTPROCESSED, PARSEDSESSIONS  #pylint: disable=global-statement
        self.pollingobserver = pollingobserver
        self.tasks = set()
        self.event_handler = None
        self.observer = None
        self.testmode = testmode
        self.decks = {}
        self.playingadat = {}
        PARSEDSESSIONS = []
        LASTPROCESSED = 0
        self.lastfetched = 0
        if seratodir:
            self.seratodir = pathlib.Path(seratodir)
            self.watchdeck = None
            PARSEDSESSIONS = []
            self.mode = 'local'
            self.mixmode = mixmode

        if seratourl:
            self.url = seratourl
            self.mode = 'remote'
            self.mixmode = 'newest'  # there is only 1 deck so always newest
        else:
            self.url = None

        if self.mixmode not in ['newest', 'oldest']:
            self.mixmode = 'newest'

    async def start(self):
        ''' perform any startup tasks '''
        if self.seratodir and self.mode == 'local':
            await self._setup_watcher()

    async def _setup_watcher(self):
        logging.debug('setting up watcher')
        self.event_handler = PatternMatchingEventHandler(
            patterns=['*.session'],
            ignore_patterns=['.DS_Store'],
            ignore_directories=True,
            case_sensitive=False)
        self.event_handler.on_modified = self.process_sessions

        if self.pollingobserver:
            self.observer = PollingObserver(timeout=5)
            logging.debug('Using polling observer')
        else:
            self.observer = Observer()
            logging.debug('Using fsevent observer')

        self.observer.schedule(
            self.event_handler,
            str(self.seratodir.joinpath("History", "Sessions")),
            recursive=False)
        self.observer.start()

        # process what is already there
        await self._async_process_sessions()

    def process_sessions(self, event):
        ''' handle incoming session file updates '''
        logging.debug('processing %s', event)
        try:
            loop = asyncio.get_running_loop()
            logging.debug('got a running loop')
            task = loop.create_task(self._async_process_sessions())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        except RuntimeError:
            loop = asyncio.new_event_loop()
            logging.debug('created a loop')
            loop.run_until_complete(self._async_process_sessions())

    async def _async_process_sessions(self):
        ''' read and process all of the relevant session files '''
        global LASTPROCESSED, PARSEDSESSIONS  #pylint: disable=global-statement

        if self.mode == 'remote':
            return

        logging.debug('triggered by watcher')

        # Just nuke the OS X metadata file rather than
        # work around it

        sessionpath = self.seratodir.joinpath("History", "Sessions")

        sessionlist = sorted(sessionpath.glob('*.session'),
                             key=lambda path: int(path.stem))
        #sessionlist = sorted(seratopath.glob('*.session'),
        #                     key=lambda path: path.stat().st_mtime)

        if not sessionlist:
            logging.debug('no session files found')
            return

        if not self.testmode:
            difftime = time.time() - sessionlist[-1].stat().st_mtime
            if difftime > 600:
                logging.debug('%s is too old', sessionlist[-1].name)
                return

        session = SeratoSessionReader()
        await session.loadsessionfile(sessionlist[-1])
        session.condense()

        sessiondata = list(session.getadat())
        LASTPROCESSED = round(time.time())
        PARSEDSESSIONS = copy.copy(sessiondata)
        #logging.debug(PARSEDSESSIONS)
        logging.debug('finished processing')

    def computedecks(self, deckskiplist=None):
        ''' based upon the session data, figure out what is actually
            on each deck '''

        logging.debug('called computedecks')

        if self.mode == 'remote':
            return

        self.decks = {}

        for adat in reversed(PARSEDSESSIONS):
            if not adat.get('deck'):
                # broken record
                continue
            if deckskiplist and str(adat['deck']) in deckskiplist:
                # on a deck that is supposed to be ignored
                continue
            if not adat.get('played'):
                # wasn't played, so skip it
                continue
            if adat['deck'] in self.decks and adat.get(
                    'starttime') < self.decks[adat['deck']].get('starttime'):
                # started after a deck that is already set
                continue
            self.decks[adat['deck']] = adat

    def computeplaying(self):
        ''' set the adat for the playing track based upon the
            computed decks '''

        logging.debug('called computeplaying')

        if self.mode == 'remote':
            logging.debug('in remote mode; skipping')
            return

        # at this point, self.decks should have
        # all decks with their _most recent_ "unplayed" tracks

        # under most normal operations, we should expect
        # a round-robin between the decks:

        # mixmode = oldest, better for a 2+ deck mixing scenario
        # 1. serato startup
        # 2. load deck 1   -> title set to deck 1 since only title known
        # 3. hit play
        # 4. load deck 2
        # 5. cross fade
        # 6. hit play
        # 7. load deck 1   -> title set to deck 2 since it is now the oldest
        # 8. go to #2

        # mixmode = newest, better for 1 deck or using autoplay
        # 1. serato startup
        # 2. load deck 1   -> title set to deck 1
        # 3. play
        # 4. go to #2

        # it is important to remember that due to the timestamp
        # checking in process_sessions, oldest/newest switching
        # will not effect until the NEXT session file update.
        # e.g., unless you are changing more than two decks at
        # once, this behavior should be the expected result

        self.playingadat = {}

        logging.debug('mixmode: %s', self.mixmode)

        if self.mixmode == 'newest':
            self.playingadat['starttime'] = datetime.datetime.fromtimestamp(0)
        else:
            self.playingadat['starttime'] = datetime.datetime.fromtimestamp(
                time.time())
        self.playingadat['updatedat'] = self.playingadat['starttime']

        logging.debug('Find the current playing deck. Starting at time: %s',
                      self.playingadat.get('starttime'))
        for deck, adat in self.decks.items():
            if self.mixmode == 'newest' and adat.get(
                    'starttime') > self.playingadat.get('starttime'):
                self.playingadat = adat
                logging.debug(
                    'Playing = time: %s deck: %d artist: %s title %s',
                    self.playingadat.get('starttime'), deck,
                    self.playingadat.get('artist'),
                    self.playingadat.get('title'))
            elif self.mixmode == 'oldest' and adat.get(
                    'starttime') < self.playingadat.get('starttime'):
                self.playingadat = adat
                logging.debug(
                    'Playing = time: %s deck: %d artist: %s title %s',
                    self.playingadat.get('starttime'), deck,
                    self.playingadat.get('artist'),
                    self.playingadat.get('title'))

    def getlocalplayingtrack(self, deckskiplist=None):
        ''' parse out last track from binary session file
            get latest session file
        '''

        if self.mode == 'remote':
            logging.debug('in remote mode; skipping')
            return None, None

        if not self.lastfetched or LASTPROCESSED >= self.lastfetched:
            self.lastfetched = LASTPROCESSED + 1
            self.computedecks(deckskiplist=deckskiplist)
            self.computeplaying()

        if self.playingadat:
            return self.playingadat.get('artist'), self.playingadat.get(
                'title'), self.playingadat.get('filename')
        return None, None, None

    def getremoteplayingtrack(self):  # pylint: disable=too-many-return-statements, too-many-branches
        ''' get the currently playing title from Live Playlists '''

        if self.mode == 'local':
            logging.debug('in local mode; skipping')
            return

        #
        # It is hard to believe in 2021, we are still scraping websites
        # and companies don't have APIs for data.
        #
        try:
            page = requests.get(self.url, timeout=5)
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot process %s: %s", self.url, error)
            return

        if not page:
            return

        try:
            tree = lxml.html.fromstring(page.text)
            # [\n(spaces)artist - title (tabs)]
            item = tree.xpath(
                '(//div[@class="playlist-trackname"]/text())[last()]')
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot process %s: %s", self.url, error)
            return

        if not item:
            return

        # cleanup
        tdat = str(item)
        for char in ["['", "']", "[]", "\\n", "\\t", "[\"", "\"]"]:
            tdat = tdat.replace(char, "")
        tdat = tdat.strip()

        if not tdat:
            self.playingadat = {}
            return

        if ' - ' not in tdat:
            artist = None
            title = tdat.strip()
        else:
            # artist - track
            #
            # The only hope we have is to split on ' - ' and hope that the
            # artist/title doesn't have a similar split.
            (artist, title) = tdat.split(' - ', 1)

        if not artist or artist == '.':
            artist = None
        else:
            artist = artist.strip()

        self.playingadat['artist'] = artist

        if not title or title == '.':
            title = None
        else:
            title = title.strip()

        self.playingadat['title'] = title

        if not title and not artist:
            self.playingadat = {}

        return

    def _get_tidal_cover(self, filename):
        ''' try to get the cover from tidal '''
        if tmatch := TIDAL_FORMAT.search(str(filename)):
            imgfile = f'{tmatch.group(1)}.jpg'
            tidalimgpath = self.seratodir.joinpath('Metadata', 'Tidal',
                                                   imgfile)
            logging.debug('using tidal image path: %s', tidalimgpath)
            if tidalimgpath.exists():
                with open(tidalimgpath, 'rb') as fhin:
                    return fhin.read()
        return None

    def getplayingtrack(self, deckskiplist=None):
        ''' generate a dict of data '''

        if self.mode == 'local':
            self.getlocalplayingtrack(deckskiplist=deckskiplist)
        else:
            self.getremoteplayingtrack()

        if not self.playingadat:
            return {}

        if self.playingadat.get('filename') and '.tdl' in self.playingadat.get(
                'filename'):
            if coverimage := self._get_tidal_cover(
                    self.playingadat['filename']):
                self.playingadat['coverimageraw'] = coverimage

        return {
            key: self.playingadat[key]
            for key in [
                'album',
                'artist',
                'bitrate',
                'bpm',
                'comments',
                'composer',
                'coverimageraw',
                'date',
                'deck',
                'filename',
                'genre',
                'key',
                'label',
                'lang',
                'title',
            ] if self.playingadat.get(key)
        }

    def stop(self):
        ''' stop serato handler '''
        global LASTPROCESSED, PARSEDSESSIONS  #pylint: disable=global-statement

        self.decks = {}
        PARSEDSESSIONS = []
        self.playingadat = {}
        LASTPROCESSED = 0
        self.lastfetched = 0
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def __del__(self):
        self.stop()


class Plugin(InputPlugin):  #pylint: disable=too-many-instance-attributes
    ''' handler for NowPlaying '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)

        self.url = None
        self.libpath = None
        self.local = True
        self.serato = None
        self.mixmode = "newest"
        self.testmode = False

    def install(self):
        ''' auto-install for Serato '''
        seratodir = pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.MusicLocation)[0]).joinpath("_Serato_")

        if seratodir.exists():
            self.config.cparser.value('settings/input', 'serato')
            self.config.cparser.value('serato/libpath', str(seratodir))
            return True

        return False

    async def gethandler(self):
        ''' setup the SeratoHandler for this session '''

        stilllocal = self.config.cparser.value('serato/local', type=bool)
        usepoll = self.config.cparser.value('quirks/pollingobserver',
                                            type=bool)

        # now configured as remote!
        if not stilllocal:
            stillurl = self.config.cparser.value('serato/url')

            # if previously remote and same URL, do nothing
            if not self.local and self.url == stillurl:
                return

            logging.debug('new url = %s', stillurl)
            self.local = stilllocal
            self.url = stillurl
            if self.serato:
                self.serato.stop()
            self.serato = SeratoHandler(pollingobserver=usepoll,
                                        seratourl=self.url,
                                        testmode=self.testmode)
            return

        # configured as local!

        self.local = stilllocal
        stilllibpath = self.config.cparser.value('serato/libpath')
        stillmixmode = self.config.cparser.value('serato/mixmode')

        # same path and same mixmode, no nothing
        if self.libpath == stilllibpath and self.mixmode == stillmixmode:
            return

        self.libpath = stilllibpath
        self.mixmode = stillmixmode

        self.serato = None

        # paths for session history
        hist_dir = os.path.abspath(os.path.join(self.libpath, "History"))
        sess_dir = os.path.abspath(os.path.join(hist_dir, "Sessions"))
        if os.path.isdir(sess_dir):
            logging.debug('new session path = %s', sess_dir)
            self.serato = SeratoHandler(seratodir=self.libpath,
                                        mixmode=self.mixmode,
                                        pollingobserver=usepoll,
                                        testmode=self.testmode)
            #if self.serato:
            #    self.serato.process_sessions()
        else:
            logging.error('%s does not exist!', sess_dir)
            return
        await self.serato.start()

    async def start(self, testmode=False):
        ''' get a handler '''
        self.testmode = testmode
        await self.gethandler()

    async def getplayingtrack(self):
        ''' wrapper to call getplayingtrack '''
        await self.gethandler()

        # get poll interval and then poll
        if self.local:
            interval = 1
        else:
            interval = self.config.cparser.value('settings/interval',
                                                 type=float)

        time.sleep(interval)

        if self.serato:
            deckskip = self.config.cparser.value('serato/deckskip')
            if deckskip and not isinstance(deckskip, list):
                deckskip = list(deckskip)
            return self.serato.getplayingtrack(deckskiplist=deckskip)
        return {}

    async def getrandomtrack(self, playlist):
        ''' Get the files associated with a playlist, crate, whatever '''

        libpath = self.config.cparser.value('serato/libpath')
        logging.debug('libpath: %s', libpath)
        if not libpath:
            return None

        crate_path = pathlib.Path(libpath).joinpath('Subcrates')
        smartcrate_path = pathlib.Path(libpath).joinpath('SmartCrates')

        logging.debug('Determined: %s %s', crate_path, smartcrate_path)
        if crate_path.joinpath(f'{playlist}.crate').exists():
            playlistfile = crate_path.joinpath(f'{playlist}.crate')
        elif smartcrate_path.joinpath(f'{playlist}.scrate'):
            playlistfile = smartcrate_path.joinpath(f'{playlist}.scrate')
        else:
            logging.error('Unknown crate: %s', playlist)
            return None

        logging.debug('Using %s', playlistfile)

        crate = SeratoCrateReader(playlistfile)
        await crate.loadcrate()
        filelist = crate.getfilenames()
        return filelist[random.randrange(len(filelist))]

    def defaults(self, qsettings):
        qsettings.setValue(
            'serato/libpath',
            os.path.join(
                QStandardPaths.standardLocations(
                    QStandardPaths.MusicLocation)[0], "_Serato_"))
        qsettings.setValue('serato/interval', 10.0)
        qsettings.setValue('serato/local', True)
        qsettings.setValue('serato/mixmode', "newest")
        qsettings.setValue('serato/url', None)
        qsettings.setValue('serato/deckskip', None)

    def validmixmodes(self):
        ''' let the UI know which modes are valid '''
        if self.config.cparser.value('serato/local', type=bool):
            return ['newest', 'oldest']

        return ['newest']

    def setmixmode(self, mixmode):
        ''' set the mixmode '''
        if mixmode not in ['newest', 'oldest']:
            mixmode = self.config.cparser.value('serato/mixmode')

        if not self.config.cparser.value('serato/local', type=bool):
            mixmode = 'newest'

        self.config.cparser.setValue('serato/mixmode', mixmode)
        return mixmode

    def getmixmode(self):
        ''' get the mixmode '''

        if self.config.cparser.value('serato/local', type=bool):
            return self.config.cparser.value('serato/mixmode')

        self.config.cparser.setValue('serato/mixmode', 'newest')
        return 'newest'

    async def stop(self):
        ''' stop the handler '''
        if self.serato:
            self.serato.stop()

    def on_serato_lib_button(self):
        ''' lib button clicked action'''
        startdir = self.qwidget.local_dir_lineedit.text()
        if not startdir:
            startdir = str(pathlib.Path.home())
        if libdir := QFileDialog.getExistingDirectory(self.qwidget,
                                                      'Select directory',
                                                      startdir):
            self.qwidget.local_dir_lineedit.setText(libdir)

    def connect_settingsui(self, qwidget, uihelp):
        ''' connect serato local dir button '''
        self.qwidget = qwidget
        self.uihelp = uihelp
        self.qwidget.local_dir_button.clicked.connect(
            self.on_serato_lib_button)

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''

        def handle_deckskip(cparser, qwidget):
            deckskip = cparser.value('serato/deckskip')
            qwidget.deck1_checkbox.setChecked(False)
            qwidget.deck2_checkbox.setChecked(False)
            qwidget.deck3_checkbox.setChecked(False)
            qwidget.deck4_checkbox.setChecked(False)

            if not deckskip:
                return

            if not isinstance(deckskip, list):
                deckskip = list(deckskip)

            if '1' in deckskip:
                qwidget.deck1_checkbox.setChecked(True)

            if '2' in deckskip:
                qwidget.deck2_checkbox.setChecked(True)

            if '3' in deckskip:
                qwidget.deck3_checkbox.setChecked(True)

            if '4' in deckskip:
                qwidget.deck4_checkbox.setChecked(True)

        if self.config.cparser.value('serato/local', type=bool):
            qwidget.local_button.setChecked(True)
            qwidget.remote_button.setChecked(False)
        else:
            qwidget.local_dir_button.setChecked(False)
            qwidget.remote_button.setChecked(True)
        qwidget.local_dir_lineedit.setText(
            self.config.cparser.value('serato/libpath'))
        qwidget.remote_url_lineedit.setText(
            self.config.cparser.value('serato/url'))
        qwidget.remote_poll_lineedit.setText(
            str(self.config.cparser.value('serato/interval')))
        handle_deckskip(self.config.cparser, qwidget)

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''
        if qwidget.remote_button.isChecked() and (
                'https://serato.com/playlists'
                not in qwidget.remote_url_lineedit.text()
                and 'https://www.serato.com/playlists'
                not in qwidget.remote_url_lineedit.text()
                or len(qwidget.remote_url_lineedit.text()) < 30):
            raise PluginVerifyError('Serato Live Playlist URL is invalid')

        if qwidget.local_button.isChecked() and (
                '_Serato_' not in qwidget.local_dir_lineedit.text()):
            raise PluginVerifyError(
                r'Serato Library Path is required.  Should point to "\_Serato\_" folder'
            )

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('serato/libpath',
                                     qwidget.local_dir_lineedit.text())
        self.config.cparser.setValue('serato/local',
                                     qwidget.local_button.isChecked())
        self.config.cparser.setValue('serato/url',
                                     qwidget.remote_url_lineedit.text())
        self.config.cparser.setValue('serato/interval',
                                     qwidget.remote_poll_lineedit.text())

        deckskip = []
        if qwidget.deck1_checkbox.isChecked():
            deckskip.append('1')
        if qwidget.deck2_checkbox.isChecked():
            deckskip.append('2')
        if qwidget.deck3_checkbox.isChecked():
            deckskip.append('3')
        if qwidget.deck4_checkbox.isChecked():
            deckskip.append('4')

        self.config.cparser.setValue('serato/deckskip', deckskip)

    def desc_settingsui(self, qwidget):
        ''' description '''
        qwidget.setText('This plugin provides support for Serato '
                        'in both a local and remote capacity.')
