#!/usr/bin/env python3
''' A _very_ simple and incomplete toy parser for Serato Live session files '''

import binascii
import collections
import datetime
import logging
import os
import struct
import sys
import time
import traceback

import lxml.html
import requests

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
         self.chunksize) = struct.unpack_from('>4si', self.data,
                                              self.bytecounter)
        self.bytecounter += 8

    def _int(self):
        ''' read an integer '''
        readint = struct.unpack_from('>i', self.data, self.bytecounter)[0]
        self.bytecounter += 4
        return readint

    def _intfield(self):
        ''' read the # of ints, then the int '''
        self._int()  # number of ints, which always seems to be 1, so ignore
        actualint = self._int()
        return actualint

    def _string_nodecode(self):
        ''' read # of chars in a string, then the string '''
        stringsize = self._int()
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
            print(f'Blew up on {encoded}:')
            traceback.print_stack()
            # just take out all the nulls this time and hope for the best
            decoded = encoded.replace(b'\x00', b'')
        return decoded

    def _hex(self):
        ''' read a string, then encode as hex '''
        return self._string().encode('utf-8').hex()

    def _bytes(self):
        ''' read number of bytes, then that many bytes '''
        bytesize = self._int()
        readint = struct.unpack_from(f'{bytesize}c', self.data,
                                     self.bytecounter)[0]
        self.bytecounter += 1
        return readint

    def _bool(self):
        ''' true/false handling '''
        return bool(struct.unpack('b', self._bytes())[0])

    def _timestamp(self):
        ''' read # of timestamps, then the timestamp '''
        self._int()  # number of timestamps. we ignore
        timestampint = self._int()
        return datetime.datetime.fromtimestamp(timestampint)

    def process(self):
        ''' overridable function meant to process the chunk '''

    def _debug(self):
        ''' a dumb function to help debug stuff when writing a new chunk '''
        hexbytes = binascii.hexlify(self.data[self.bytecounter:])
        total = len(hexbytes)
        j = 1
        while j < total:
            print(f'{hexbytes[j:j+7]} ')
            j = j + 8

    def importantvalues(self):
        ''' another debug function to see when these fields change '''
        for key, value in self.__dict__.items():
            if key in [
                    'deck', 'field16', 'field39', 'field68', 'field69',
                    'field70', 'field72', 'field78', 'title', 'played',
                    'playtime', 'starttime', 'updatedat'
            ]:
                print(f'thisdeck.{key} = {value}')

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
        self.publisher = None
        self.remixer = None
        self.row = 0
        self.sessionid = 0
        self.starttime = datetime.datetime.now()
        self.title = None
        self.updatedat = self.starttime
        self.year = None

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
        # [int][size][content]
        #

        self._header()
        self.row = self._int()

        while self.bytecounter < len(self.data):
            field = self._int()

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
                self.bpm = self._intfield()
            elif field == 16:
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
                self.year = self._string()
            elif field == 28:
                self.starttime = self._timestamp()
            elif field == 29:
                self.endtime = self._timestamp()
            elif field == 31:
                self.deck = self._intfield()
            elif field == 39:
                self.field39 = self._string_nodecode()
            elif field == 45:
                self.playtime = self._intfield()
            elif field == 48:
                self.sessionid = self._intfield()
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
                self.field78 = self._intfield()
            else:
                print(f'Unknown field: {field}')
                break

        # what people would expect in a filename meta
        # appears to be in pathstr
        if not self.filename:
            self.filename = self.pathstr

        # what ID3 and friends call publisher, Serato
        # calls label
        if not self.publisher:
            self.publisher = self.label


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


class SessionFile():  # pylint: disable=too-few-public-methods
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

        with open(self.filename, 'rb') as self.sessionfile:
            while True:
                header_bin = self.sessionfile.read(8)
                length_read = len(header_bin)
                if length_read < 8:
                    break

                try:
                    header = Header._make(struct.unpack('>4si', header_bin))
                except:  # pylint: disable=bare-except
                    break

                if header.chunktype == b'oent' or \
                   header.chunktype == b'oren':
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
                    print(f'Skipping chunktype: {header.chunktype}')
                    break

    def __iter__(self):
        yield self


class SeratoHandler():
    ''' Generic handler to get the currently playing track.

        To use Serato Live Playlits, construct with:
            SeratoHandler(seratourl='url')


        To use local Serato directory, construct with:
            SeratoHandler(seratodir='/path/to/_Serato_')

    '''

    # These class globals are for trying to keep track of what is
    # actually on the decks

    decks = {}
    playingadat = ChunkTrackADAT()
    lastprocessed = None
    lastfetched = None
    mode = None

    def __init__(self, mixmode='oldest', seratodir=None, seratourl=None):
        if seratodir:
            self.seratodir = seratodir
            self.watchdeck = None
            self.parsedsessions = []
            SeratoHandler.mode = 'local'
            self.mixmode = mixmode

        if seratourl:
            self.url = seratourl
            SeratoHandler.mode = 'remote'
            self.mixmode = 'oldest'  # there is only 1 deck so always newest

        if self.mixmode not in ['newest', 'oldest']:
            self.mixmode = 'newest'

    def process_sessions(self):
        ''' read and process all of the relevant session files '''

        if SeratoHandler.mode == 'remote':
            logging.debug('in remote mode; skipping')
            return

        self.parsedsessions = []

        # Just nuke the OS X metadata file rather than
        # work around it

        dsstorefile = os.path.abspath(os.path.join(self.seratodir,
                                                   ".DS_Store"))

        if os.path.exists(dsstorefile):
            os.remove(dsstorefile)

        # Serato probably hasn't been started yet
        if not os.path.exists(self.seratodir):
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
            return

        #
        for file in files:
            sessionfilename = os.path.abspath(
                os.path.join(self.seratodir, file))
            filetimestamp = os.path.getmtime(sessionfilename)
            file_mod_age = time.time() - os.path.getmtime(sessionfilename)
            # ignore files older than 10 minutes
            if file_mod_age > 600:
                continue

            if not SeratoHandler.lastprocessed or\
               filetimestamp > SeratoHandler.lastprocessed:
                SeratoHandler.lastprocessed = filetimestamp
                logging.debug('processing %s', sessionfilename)
                self.parsedsessions.append(SessionFile(sessionfilename))

    def computedecks(self):
        ''' based upon the session data, figure out what is actually
            on each deck '''

        if SeratoHandler.mode == 'remote':
            logging.debug('in remote mode; skipping')
            return

        SeratoHandler.decks = {}

        # keep track of each deck. run through
        # the session files trying to find
        # the most recent, unplayed track.
        # it is VERY IMPORTANT to know that
        # playtime is _ONLY_ set when that deck
        # has been reloaded!

        for index in reversed(self.parsedsessions):
            for adat in index.adats:
                if 'playtime' in adat and adat.playtime > 0:
                    continue
                if adat.deck in SeratoHandler.decks:
                    if adat.deck in SeratoHandler.decks:
                        if adat.updatedat < SeratoHandler.decks[
                                adat.deck].updatedat:
                            continue
                logging.debug('Setting deck: %d artist: %s title: %s',
                              adat.deck, adat.artist, adat.title)
                SeratoHandler.decks[adat.deck] = adat

    def computeplaying(self):  # pylint: disable=no-self-use
        ''' set the adat for the playing track based upon the
            computed decks '''

        if SeratoHandler.mode == 'remote':
            logging.debug('in remote mode; skipping')
            return

        # at this point, SeratoHandler.decks should have
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

        SeratoHandler.playingadat = ChunkTrackADAT()

        logging.debug('mixmode: %s', self.mixmode)

        if self.mixmode == 'newest':
            SeratoHandler.playingadat.starttime = datetime.datetime.fromtimestamp(
                0)
            SeratoHandler.playingadat.updatedat = SeratoHandler.playingadat.starttime

        logging.debug('Find the current playing deck. Starting at time: %s',
                      SeratoHandler.playingadat.starttime)
        for deck in SeratoHandler.decks:
            if self.mixmode == 'newest' and SeratoHandler.decks[
                    deck].starttime > SeratoHandler.playingadat.starttime:
                SeratoHandler.playingadat = SeratoHandler.decks[deck]
                logging.debug(
                    'Playing = time: %s deck: %d artist: %s title %s',
                    SeratoHandler.playingadat.starttime,
                    SeratoHandler.playingadat.deck,
                    SeratoHandler.playingadat.artist,
                    SeratoHandler.playingadat.title)
            elif self.mixmode == 'oldest' and SeratoHandler.decks[
                    deck].starttime < SeratoHandler.playingadat.starttime:
                SeratoHandler.playingadat = SeratoHandler.decks[deck]
                logging.debug(
                    'Playing = time: %s deck: %d artist: %s title %s',
                    SeratoHandler.playingadat.starttime,
                    SeratoHandler.playingadat.deck,
                    SeratoHandler.playingadat.artist,
                    SeratoHandler.playingadat.title)

    def getlocalplayingtrack(self):
        ''' parse out last track from binary session file
            get latest session file
        '''

        if SeratoHandler.mode == 'remote':
            logging.debug('in remote mode; skipping')
            return None, None

        if not SeratoHandler.lastprocessed:
            self.process_sessions()

        if not SeratoHandler.lastfetched or \
           SeratoHandler.lastprocessed > SeratoHandler.lastfetched:
            SeratoHandler.lastfetched = SeratoHandler.lastprocessed

            self.computedecks()
            self.computeplaying()

        if SeratoHandler.playingadat:
            return SeratoHandler.playingadat.artist, SeratoHandler.playingadat.title
        return None, None

    def getremoteplayingtrack(self):  # pylint: disable=too-many-return-statements, too-many-branches
        ''' get the currently playing title from Live Playlists '''

        if SeratoHandler.mode == 'local':
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
            SeratoHandler.playingadat = ChunkTrackADAT()
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

        SeratoHandler.playingadat.artist = artist

        if not title or title == '.':
            title = None
        else:
            title = title.strip()

        SeratoHandler.playingadat.title = title

        if not title and not artist:
            SeratoHandler.playingadat = ChunkTrackADAT()

        return artist, title

    def getplayingtrack(self):
        ''' generate a dict of data '''

        if SeratoHandler.mode == 'local':
            return self.getlocalplayingtrack()
        return self.getremoteplayingtrack()

    def getplayingmetadata(self):  #pylint: disable=too-many-branches
        ''' take the current adat and generate a media dict '''
        metadata = {}

        self.getplayingtrack()

        if not SeratoHandler.playingadat:
            return None

        for key in [
                'album', 'artist', 'bitrate', 'bpm', 'composer', 'filename',
                'genre', 'key', 'publisher', 'lang', 'title', 'year'
        ]:

            if hasattr(SeratoHandler.playingadat, key) and getattr(
                    SeratoHandler.playingadat, key):
                metadata[key] = getattr(SeratoHandler.playingadat, key)

        return metadata


def main():
    ''' entry point as a standalone app'''

    seratohandler = SeratoHandler(seratodir=sys.argv[1])
    seratohandler.process_sessions()
    seratohandler.getplayingtrack()
    if seratohandler.playingadat:
        seratohandler.playingadat.importantvalues()
    else:
        print('No title currently suspecting of playing.')


if __name__ == "__main__":
    main()
