#!/usr/bin/env python3
''' A _very_ simple and incomplete parser for Serato Live session files '''

import binascii
import collections
import datetime
import logging
import os
import pathlib
import struct
import time
import traceback

import lxml.html
import requests

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from PySide2.QtCore import QStandardPaths  # pylint: disable=no-name-in-module
from PySide2.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

from nowplaying.inputs import InputPlugin
from nowplaying.exceptions import PluginVerifyError

Header = collections.namedtuple('Header', 'chunktype size')


class ChunkParser():  #pylint: disable=too-few-public-methods
    ''' Basic Chunk Parser '''

    # The format of a chunk is fairly trivial:
    # [int field][int length][content of field]

    def __init__(self, chunktype=None, data=None):
        self.chunktype = chunktype
        self.bytecounter = 0
        self.headersize = 0
        self.data = data
        self.chunksize = 0
        self.chunkheader = 0

    def _header(self):
        ''' read the header '''

        # headers for hunks are 8 bytes
        # 4 byte identifier, 4 byte size
        # with the identifier, other program logic
        # will kick in

        (self.chunkheader,
         self.chunksize) = struct.unpack_from('>4sI', self.data,
                                              self.bytecounter)
        self.bytecounter += 8

    def _num(self, size=4):
        ''' read an number '''
        if size == 8:
            readnum = struct.unpack_from('>Q', self.data, self.bytecounter)[0]
            self.bytecounter += 8
        else:
            readnum = struct.unpack_from('>I', self.data, self.bytecounter)[0]
            self.bytecounter += 4
        return readnum

    def _numfield(self):
        ''' read the size of the number, then the number '''
        size = self._num()
        return self._num(size)

    def _string_nodecode(self):
        ''' read # of chars in a string, then the string '''
        stringsize = self._num()
        readstring = struct.unpack_from(f'{stringsize}s', self.data,
                                        self.bytecounter)[0]
        self.bytecounter += stringsize
        return readstring

    def _string(self):
        ''' read # of chars in a string, then the string '''

        # At least on the Mac, strings appear to be written
        # in UTF-16-BE which gives a wide variety of possible
        # choices of characters
        encoded = self._string_nodecode()

        try:
            decoded = encoded.decode('utf-16-be')
            # strip ending null character at the end
            decoded = decoded[:-1]
        except UnicodeDecodeError:
            logging.error('Blew up on %s:', encoded)
            logging.error(traceback.print_stack())
            # just take out all the nulls this time and hope for the best
            decoded = encoded.replace(b'\x00', b'')
        return decoded

    def _hex(self):
        ''' read a string, then encode as hex '''
        return self._string().encode('utf-8').hex()

    def _bytes(self):
        ''' read number of bytes, then that many bytes '''
        bytesize = self._num()
        readnum = struct.unpack_from(f'{bytesize}c', self.data,
                                     self.bytecounter)[0]
        self.bytecounter += 1
        return readnum

    def _bool(self):
        ''' true/false handling '''
        return bool(struct.unpack('b', self._bytes())[0])

    def _timestamp(self):
        ''' timestamps are numfields converted to a datetime object '''
        timestampnum = self._numfield()
        return datetime.datetime.fromtimestamp(timestampnum)

    def process(self):
        ''' overridable function meant to process the chunk '''

    def _debug(self):  # pragma: no cover
        ''' a dumb function to help debug stuff when writing a new chunk '''
        hexbytes = binascii.hexlify(self.data[self.bytecounter:])
        total = len(hexbytes)
        for j in range(1, total + 1, 8):
            logging.debug('_debug: %s', hexbytes[j:j + 7])

    def importantvalues(self):  # pragma: no cover
        ''' another debug function to see when these fields change '''
        for key, value in self.__dict__.items():
            # if key in [
            #         'deck', 'field16', 'field39', 'field68', 'field69',
            #         'field70', 'field72', 'field78', 'title', 'played',
            #         'playtime', 'starttime', 'updatedat'
            # ]:
            logging.info('thisdeck.%s = %s', key, value)

    def __iter__(self):
        yield self


class ChunkTrackADAT(ChunkParser):  #pylint: disable=too-many-instance-attributes, too-few-public-methods
    ''' Process the 'adat' chunk '''

    # adat contains the deck information.
    # it is important to note that, for all intents and purposes
    # Serato only updates the adat if the deck has some sort of
    # major event just as load and eject.  play is NOT written
    # until after a load/eject event!

    def __init__(self, data=None):
        self.added = None
        self.album = None
        self.artist = None
        self.bitrate = None
        self.bpm = None
        self.commentname = None
        self.comments = None
        self.composer = None
        self.deck = None
        self.endtime = None
        self.filename = None
        self.filesize = None
        self.frequency = None
        self.genre = None
        self.grouping = None
        self.key = None
        self.label = None
        self.lang = None
        self.length = None
        self.location = None
        self.pathstr = None
        self.played = False
        self.playername = None
        self.playtime = None
        self.remixer = None
        self.row = 0
        self.sessionid = 0
        self.starttime = datetime.datetime.now()
        self.title = None
        self.updatedat = self.starttime
        self.date = None

        self.field16 = None
        self.field39 = None
        self.field68 = None
        self.field69 = None
        self.field70 = None
        self.field72 = None
        self.field78 = 0

        self.data = data
        super().__init__(chunktype='adat', data=self.data)
        if data:
            self.process()
            # free some RAM
            self.data = None
            self.chunkheader = None

    def process(self):  #pylint: disable=too-many-branches,too-many-statements
        ''' process the 'adat' chunk '''

        # [adat][size][row][fields...]
        #
        # all fields are (effectively)
        # [field identifier][size of field][content]
        #

        self._header()
        self.row = self._num()

        while self.bytecounter < len(self.data):
            field = self._num()

            # Python's lack of 'case' is annoying. :(
            # opted to just use simple if/elif ladder
            # rather than anything particularly fancy

            if field == 2:
                self.pathstr = self._string()
            elif field == 3:
                self.location = self._string()
            elif field == 4:
                self.filename = self._string()
            elif field == 6:
                self.title = self._string()
            elif field == 7:
                self.artist = self._string()
            elif field == 8:
                self.album = self._string()
            elif field == 9:
                self.genre = self._string()
            elif field == 10:
                self.length = self._string()
            elif field == 11:
                self.filesize = self._string()
            elif field == 13:
                self.bitrate = self._string()
            elif field == 14:
                self.frequency = self._string()
            elif field == 15:
                self.bpm = self._numfield()
            elif field == 16:  # pragma: no cover
                self.field16 = self._hex()
            elif field == 17:
                self.comments = self._string()
            elif field == 18:
                self.lang = self._string()
            elif field == 19:
                self.grouping = self._string()
            elif field == 20:
                self.remixer = self._string()
            elif field == 21:
                self.label = self._string()
            elif field == 22:
                self.composer = self._string()
            elif field == 23:
                self.date = self._string()
            elif field == 28:
                self.starttime = self._timestamp()
            elif field == 29:
                self.endtime = self._timestamp()
            elif field == 31:
                self.deck = self._numfield()
            elif field == 39:
                self.field39 = self._string_nodecode()
            elif field == 45:
                self.playtime = self._numfield()
            elif field == 48:
                self.sessionid = self._numfield()
            elif field == 50:
                self.played = self._bytes()
            elif field == 51:
                self.key = self._string()
            elif field == 52:
                self.added = self._bool()
            elif field == 53:
                self.updatedat = self._timestamp()
            elif field == 63:
                self.playername = self._string()
            elif field == 64:
                self.commentname = self._string()
            elif field == 68:
                self.field68 = self._string_nodecode()
            elif field == 69:
                self.field69 = self._string_nodecode()
            elif field == 70:
                self.field70 = self._string_nodecode()
            elif field == 72:
                self.field72 = self._string_nodecode()
            elif field == 78:
                self.field78 = self._numfield()
            else:
                logging.debug('Unknown field: %s', field)
                self._debug()
                break

        # what people would expect in a filename meta
        # appears to be in pathstr
        if not self.filename:
            self.filename = self.pathstr


class ChunkVRSN(ChunkParser):  #pylint: disable=too-many-instance-attributes, too-few-public-methods
    ''' Process the 'vrsn' chunk '''

    # These chunks are very simple

    def __init__(self, data=None):
        self.version = None
        self.data = data
        super().__init__(chunktype='vrsn', data=self.data)
        self.process()

    def process(self):  #pylint: disable=too-many-branches,too-many-statements
        ''' process the 'vrsn' chunk '''
        headersize = len(self.data)
        self.version = struct.unpack(f'{headersize}s',
                                     self.data)[0].decode('utf-16-be')


class SessionFile():  #pylint: disable=too-few-public-methods
    ''' process a session file '''
    def __init__(self, filename=None):
        self.filename = filename
        self.adats = []
        self.vrsn = None
        self.decks = {}
        self.lastreaddeck = None

        while os.access(self.filename, os.R_OK) is False:
            time.sleep(0.5)

        # Serato session files are effectively:
        # 8 byte header = 4 byte ident + 4 byte length
        # 8 byte container = 4 byte ident + 4 byte length
        # ...

        # There are different types of containers.  The two
        # we care about are 'vrsn' and 'onet'.
        # * vrsn is just the version of the file
        # * onet is usually wrapping a single adat
        # * adat is the deck information, including what track is
        #   loaded
        # The rest get ignored

        if '.session' not in self.filename:
            return

        logging.debug('starting to read %s', self.filename)
        with open(self.filename, 'rb') as self.sessionfile:
            while True:
                header_bin = self.sessionfile.read(8)
                length_read = len(header_bin)
                if length_read < 8:
                    break

                try:
                    header = Header._make(struct.unpack('>4sI', header_bin))
                except:  # pylint: disable=bare-except
                    break

                if header.chunktype in [b'oent', b'oren']:
                    containertype = header.chunktype
                    continue

                data = self.sessionfile.read(header.size)

                if header.chunktype == b'adat' and containertype == b'oent':
                    self.adats.append(ChunkTrackADAT(data=data))
                    self.decks[self.adats[-1].deck] = self.adats[-1]
                    self.lastreaddeck = self.adats[-1].deck
                elif header.chunktype == b'adat' and containertype == b'oren':
                    # not currently parsed, but probably should be?
                    continue
                elif header.chunktype == b'vrsn':
                    self.vrsn = ChunkVRSN(data=data)
                else:
                    logging.warning('Skipping chunktype: %s', header.chunktype)
                    break

    def __iter__(self):  # pragma: no cover
        yield self


class SeratoHandler():  #pylint: disable=too-many-instance-attributes
    ''' Generic handler to get the currently playing track.

        To use Serato Live Playlits, construct with:
            self.seratourl='url')


        To use local Serato directory, construct with:
            self.seratodir='/path/to/_Serato_/History/Sessions')

    '''
    def __init__(self, mixmode='oldest', seratodir=None, seratourl=None):
        self.event_handler = None
        self.observer = None
        self.decks = {}
        self.parsedsessions = []
        self.playingadat = ChunkTrackADAT()
        self.lastprocessed = 0
        self.lastfetched = 0
        if seratodir:
            self.seratodir = seratodir
            self.watchdeck = None
            self.parsedsessions = []
            self.mode = 'local'
            self.mixmode = mixmode
            self._setup_watcher()

        if seratourl:
            self.url = seratourl
            self.mode = 'remote'
            self.mixmode = 'newest'  # there is only 1 deck so always newest
        else:
            self.url = None

        if self.mixmode not in ['newest', 'oldest']:
            self.mixmode = 'newest'

    def _setup_watcher(self):
        logging.debug('setting up watcher')
        self.event_handler = PatternMatchingEventHandler(
            patterns=['*.session'],
            ignore_patterns=['.DS_Store'],
            ignore_directories=True,
            case_sensitive=False)
        self.event_handler.on_modified = self.process_sessions
        self.observer = Observer()
        self.observer.schedule(self.event_handler,
                               self.seratodir,
                               recursive=False)
        self.observer.start()

        # process what is already there
        self.process_sessions(path=self.seratodir)

    def process_sessions(self, path):  # pylint: disable=unused-argument
        ''' read and process all of the relevant session files '''

        logging.debug('processing %s path', path)

        if self.mode == 'remote':
            return

        logging.debug('triggered by watcher')
        self.parsedsessions = []

        # Just nuke the OS X metadata file rather than
        # work around it

        dsstorefile = os.path.abspath(os.path.join(self.seratodir,
                                                   ".DS_Store"))

        if os.path.exists(dsstorefile):
            os.remove(dsstorefile)

        # Serato probably hasn't been started yet
        if not os.path.exists(self.seratodir):
            logging.debug('no seratodir?')
            return

        # some other conditions may give us FNF, so just
        # return here too
        try:
            files = sorted(os.listdir(self.seratodir),
                           key=lambda x: os.path.getmtime(
                               os.path.join(self.seratodir, x)))
        except FileNotFoundError:
            return

        # The directory exists, but nothing in it.
        if not files:
            logging.debug('dir is empty?')
            return

        logging.debug('all files %s', files)
        for file in files:
            sessionfilename = os.path.abspath(
                os.path.join(self.seratodir, file))
            filetimestamp = os.path.getmtime(sessionfilename)
            file_mod_age = time.time() - os.path.getmtime(sessionfilename)
            # ignore files older than 10 minutes
            if file_mod_age > 600:
                logging.debug('ignoring %s; too old', file)
                continue

            self.lastprocessed = filetimestamp
            logging.debug('processing %s', sessionfilename)
            self.parsedsessions.append(SessionFile(sessionfilename))

    def computedecks(self, deckskiplist=None):  # pylint: disable=no-self-use
        ''' based upon the session data, figure out what is actually
            on each deck '''

        if self.mode == 'remote':
            return

        self.decks = {}

        # keep track of each deck. run through
        # the session files trying to find
        # the most recent, unplayed track.
        # it is VERY IMPORTANT to know that
        # playtime is _ONLY_ set when that deck
        # has been reloaded!

        for index in reversed(self.parsedsessions):
            for adat in index.adats:
                if deckskiplist and str(adat.deck) in deckskiplist:
                    continue
                if 'playtime' in adat and adat.playtime > 0:
                    continue
                if (adat.deck in self.decks
                        and adat.updatedat < self.decks[adat.deck].updatedat):
                    continue
                logging.debug('Setting deck: %d artist: %s title: %s',
                              adat.deck, adat.artist, adat.title)
                self.decks[adat.deck] = adat

    def computeplaying(self):  # pylint: disable=no-self-use
        ''' set the adat for the playing track based upon the
            computed decks '''

        if self.mode == 'remote':
            logging.debug('in remote mode; skipping')
            return

        # at this point, self.decks should have
        # all decks with their _most recent_ unplayed tracks

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

        self.playingadat = ChunkTrackADAT()

        logging.debug('mixmode: %s', self.mixmode)

        if self.mixmode == 'newest':
            self.playingadat.starttime = datetime.datetime.fromtimestamp(0)
            self.playingadat.updatedat = self.playingadat.starttime

        logging.debug('Find the current playing deck. Starting at time: %s',
                      self.playingadat.starttime)
        for deck in self.decks:
            if self.mixmode == 'newest' and self.decks[
                    deck].starttime > self.playingadat.starttime:
                self.playingadat = self.decks[deck]
                logging.debug(
                    'Playing = time: %s deck: %d artist: %s title %s',
                    self.playingadat.starttime, self.playingadat.deck,
                    self.playingadat.artist, self.playingadat.title)
            elif self.mixmode == 'oldest' and self.decks[
                    deck].starttime < self.playingadat.starttime:
                self.playingadat = self.decks[deck]
                logging.debug(
                    'Playing = time: %s deck: %d artist: %s title %s',
                    self.playingadat.starttime, self.playingadat.deck,
                    self.playingadat.artist, self.playingadat.title)

    def getlocalplayingtrack(self, deckskiplist=None):
        ''' parse out last track from binary session file
            get latest session file
        '''

        if self.mode == 'remote':
            logging.debug('in remote mode; skipping')
            return None, None

        if not self.lastfetched or \
           self.lastprocessed >= self.lastfetched:
            self.lastfetched = self.lastprocessed + 1
            self.computedecks(deckskiplist=deckskiplist)
            self.computeplaying()

        if self.playingadat:
            return self.playingadat.artist, self.playingadat.title
        return None, None

    def getremoteplayingtrack(self):  # pylint: disable=too-many-return-statements, too-many-branches
        ''' get the currently playing title from Live Playlists '''

        if self.mode == 'local':
            logging.debug('in local mode; skipping')
            return None, None

        #
        # It is hard to believe in 2021, we are still scraping websites
        # and companies don't have APIs for data.
        #
        try:
            page = requests.get(self.url)
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot process %s: %s", self.url, error)
            return None, None

        if not page:
            return None, None

        try:
            tree = lxml.html.fromstring(page.text)
            # [\n(spaces)artist - title (tabs)]
            item = tree.xpath(
                '(//div[@class="playlist-trackname"]/text())[last()]')
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot process %s: %s", self.url, error)
            return None, None

        if not item:
            return None, None

        # cleanup
        tdat = str(item)
        tdat = tdat.replace("['", "")\
                   .replace("']", "")\
                   .replace("[]", "")\
                   .replace("\\n", "")\
                   .replace("\\t", "")\
                   .replace("[\"", "").replace("\"]", "")
        tdat = tdat.strip()

        if not tdat:
            self.playingadat = ChunkTrackADAT()
            return None, None

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

        self.playingadat.artist = artist

        if not title or title == '.':
            title = None
        else:
            title = title.strip()

        self.playingadat.title = title

        if not title and not artist:
            self.playingadat = ChunkTrackADAT()

        return artist, title

    def getplayingtrack(self, deckskiplist=None):
        ''' generate a dict of data '''

        if self.mode == 'local':
            return self.getlocalplayingtrack(deckskiplist=deckskiplist)
        return self.getremoteplayingtrack()

    def getplayingmetadata(self):  #pylint: disable=no-self-use
        ''' take the current adat and generate a media dict '''

        if not self.playingadat:
            return None

        return {
            key: getattr(self.playingadat, key)
            for key in [
                'album',
                'artist',
                'bitrate',
                'bpm',
                'comments',
                'composer',
                'date',
                'deck',
                'filename',
                'genre',
                'key',
                'label',
                'lang',
                'title',
            ] if hasattr(self.playingadat, key)
            and getattr(self.playingadat, key)
        }

    def stop(self):  # pylint: disable=no-self-use
        ''' stop serato handler '''
        self.decks = {}
        self.parsedsessions = []
        self.playingadat = ChunkTrackADAT()
        self.lastprocessed = 0
        self.lastfetched = 0
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def __del__(self):
        self.stop()


class Plugin(InputPlugin):
    ''' handler for NowPlaying '''
    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)

        self.url = None
        self.libpath = None
        self.local = True
        self.serato = None
        self.mixmode = "newest"
        self.qwidget = None

        if not qsettings:
            self.gethandler()

    def gethandler(self):
        ''' setup the SeratoHandler for this session '''

        stilllocal = self.config.cparser.value('serato/local', type=bool)

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
            self.serato = SeratoHandler(seratourl=self.url)
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
        sera_dir = self.libpath
        hist_dir = os.path.abspath(os.path.join(sera_dir, "History"))
        sess_dir = os.path.abspath(os.path.join(hist_dir, "Sessions"))
        if os.path.isdir(sess_dir):
            logging.debug('new session path = %s', sess_dir)
            self.serato = SeratoHandler(seratodir=sess_dir,
                                        mixmode=self.mixmode)
            #if self.serato:
            #    self.serato.process_sessions()

    def getplayingtrack(self):
        ''' wrapper to call getplayingtrack '''
        self.gethandler()

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
        return None, None

    def getplayingmetadata(self):
        ''' wrapper to call getplayingmetadata '''
        if self.serato:
            return self.serato.getplayingmetadata()
        return {}

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

    def stop(self):
        ''' stop the handler '''
        if self.serato:
            self.serato.stop()

    def on_serato_lib_button(self):
        ''' lib button clicked action'''
        startdir = self.qwidget.local_dir_lineedit.text()
        if not startdir:
            startdir = str(pathlib.Path.home())
        libdir = QFileDialog.getExistingDirectory(self.qwidget,
                                                  'Select directory', startdir)
        if libdir:
            self.qwidget.local_dir_lineedit.setText(libdir)

    def connect_settingsui(self, qwidget):
        ''' connect serato local dir button '''
        self.qwidget = qwidget
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
