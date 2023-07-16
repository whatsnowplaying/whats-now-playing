#!/usr/bin/env python3
''' pull out metadata '''

import asyncio
import concurrent.futures
import contextlib
import logging
import re
import os
import string
import sys
import textwrap
import traceback

import nltk
import tinytag
import url_normalize

import nowplaying.config
import nowplaying.hostmeta
import nowplaying.musicbrainz
import nowplaying.utils
import nowplaying.vendor.audio_metadata
from nowplaying.vendor.audio_metadata.formats.mp4_tags import MP4FreeformDecoders

NOTE_RE = re.compile('N(?i:ote):')


class MetadataProcessors:  # pylint: disable=too-few-public-methods
    ''' Run through a bunch of different metadata processors '''

    def __init__(self, config: 'nowplaying.config.ConfigFile' = None):
        self.metadata = {}
        self.imagecache = None
        if config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()

        self.extraslist = self._sortextras()

    def _sortextras(self):
        extras = {}
        for plugin in self.config.plugins['artistextras']:
            priority = self.config.pluginobjs['artistextras'][plugin].priority
            if not extras.get(priority):
                extras[priority] = []
            extras[priority].append(plugin)
        return dict(reversed(list(extras.items())))

    async def getmoremetadata(self, metadata=None, imagecache=None, skipplugins=False):
        ''' take metadata and process it '''
        if metadata:
            self.metadata = metadata
        else:
            self.metadata = {}
        self.imagecache = imagecache

        if 'artistfanarturls' not in self.metadata:
            self.metadata['artistfanarturls'] = []

        try:
            for processor in 'hostmeta', 'audio_metadata', 'tinytag', 'image2png':
                logging.debug('running %s', processor)
                func = getattr(self, f'_process_{processor}')
                func()
        except Exception:  #pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            logging.error('Ignoring sub-metaproc failure.')

        await self._process_plugins(skipplugins)

        if 'publisher' in self.metadata:
            if 'label' not in self.metadata:
                self.metadata['label'] = self.metadata['publisher']
            del self.metadata['publisher']

        self._fix_dates()

        if self.metadata.get('artistlongbio') and not self.metadata.get('artistshortbio'):
            self._generate_short_bio()

        self._uniqlists()

        self._strip_identifiers()
        self._fix_duration()
        return self.metadata

    def _fix_dates(self):
        ''' take care of year / date cleanup '''
        if not self.metadata:
            return

        if 'year' in self.metadata:
            if 'date' not in self.metadata:
                self.metadata['date'] = self.metadata['year']
            del self.metadata['year']

        if 'date' in self.metadata and (not self.metadata['date'] or self.metadata['date'] == '0'):
            del self.metadata['date']

    def _fix_duration(self):
        if not self.metadata or not self.metadata.get('duration'):
            return

        try:
            duration = int(float(self.metadata['duration']))
        except ValueError:
            logging.debug('Cannot convert duration = %s', self.metadata['duration'])
            del self.metadata['duration']
            return

        self.metadata['duration'] = duration

    def _strip_identifiers(self):
        if not self.metadata:
            return

        if self.config.cparser.value('settings/stripextras',
                                     type=bool) and self.metadata.get('title'):
            self.metadata['title'] = nowplaying.utils.titlestripper_advanced(
                title=self.metadata['title'], title_regex_list=self.config.getregexlist())

    def _uniqlists(self):
        if not self.metadata:
            return

        if self.metadata.get('artistwebsites'):
            newlist = [url_normalize.url_normalize(url) for url in self.metadata['artistwebsites']]
            self.metadata['artistwebsites'] = newlist

        lists = ['artistwebsites', 'isrc', 'musicbrainzartistid']
        for listname in lists:
            if self.metadata.get(listname):
                newlist = sorted(set(self.metadata[listname]))
                self.metadata[listname] = newlist

        if self.metadata.get('artistwebsites'):
            newlist = []
            for url in self.metadata['artistwebsites']:
                if 'wikidata' in url:
                    continue
                if 'http:' not in url:
                    newlist.append(url)
                    continue

                testurl = url.replace('http:', 'https:')
                if testurl not in self.metadata.get('artistwebsites'):
                    newlist.append(url)
            self.metadata['artistwebsites'] = newlist

    def _process_hostmeta(self):
        ''' add the host metadata so other subsystems can use it '''
        if self.metadata is None:
            self.metadata = {}

        if self.config.cparser.value('weboutput/httpenabled', type=bool):
            self.metadata['httpport'] = self.config.cparser.value('weboutput/httpport', type=int)
        hostmeta = nowplaying.hostmeta.gethostmeta()
        for key, value in hostmeta.items():
            self.metadata[key] = value

    def _process_audio_metadata(self):
        self.metadata = AudioMetadataRunner(config=self.config).process(metadata=self.metadata)

    def _process_tinytag(self):
        ''' given a chunk of metadata, try to fill in more '''
        if not self.metadata or not self.metadata.get('filename'):
            return

        try:
            tag = tinytag.TinyTag.get(self.metadata['filename'], image=True)
        except tinytag.tinytag.TinyTagException as error:
            logging.error('tinytag could not process %s: %s', self.metadata['filename'], error)
            return

        if tag:
            for key in [
                    'album', 'albumartist', 'artist', 'bitrate', 'bpm', 'comments', 'composer',
                    'disc', 'disc_total', 'duration', 'genre', 'key', 'lang', 'publisher', 'title',
                    'track', 'track_total', 'year'
            ]:
                if key not in self.metadata and hasattr(tag, key) and getattr(tag, key):
                    self.metadata[key] = getattr(tag, key)

            if getattr(tag, 'extra'):
                extra = getattr(tag, 'extra')
                for key in ['isrc']:
                    if extra.get(key):
                        self.metadata[key] = extra[key].split('/')

            if 'date' not in self.metadata and hasattr(tag, 'year') and getattr(tag, 'year'):
                self.metadata['date'] = getattr(tag, 'year')

            if 'coverimageraw' not in self.metadata:
                self.metadata['coverimageraw'] = tag.get_image()

    def _process_image2png(self):
        # always convert to png

        if not self.metadata or 'coverimageraw' not in self.metadata or not self.metadata[
                'coverimageraw']:
            return

        self.metadata['coverimageraw'] = nowplaying.utils.image2png(self.metadata['coverimageraw'])
        self.metadata['coverimagetype'] = 'png'
        self.metadata['coverurl'] = 'cover.png'

    def _musicbrainz(self):
        if not self.metadata:
            return None

        musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(config=self.config)
        addmeta = musicbrainz.recognize(self.metadata)
        self.metadata = recognition_replacement(config=self.config,
                                                metadata=self.metadata,
                                                addmeta=addmeta)
        return addmeta

    def _mb_fallback(self):
        ''' at least see if album can be found '''

        # user does not want fallback support
        if not self.metadata or not self.config.cparser.value('musicbrainz/fallback', type=bool):
            return

        # either missing key data or has already been processed
        if (self.metadata.get('isrc') or self.metadata.get('musicbrainzartistid')
                or self.metadata.get('musicbrainzrecordingid') or not self.metadata.get('artist')
                or not self.metadata.get('title')):
            return

        logging.debug('Attempting musicbrainz fallback')

        try:
            musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(config=self.config)
            addmeta = musicbrainz.lastditcheffort(self.metadata)
            self.metadata = recognition_replacement(config=self.config,
                                                    metadata=self.metadata,
                                                    addmeta=addmeta)
        except Exception:  #pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            logging.error('Ignoring fallback failure.')

    async def _process_plugins(self, skipplugins):
        addmeta = self._musicbrainz()

        for plugin in self.config.plugins['recognition']:
            metalist = self.config.pluginobjs['recognition'][plugin].providerinfo()
            provider = any(meta not in self.metadata for meta in metalist)
            if provider:
                try:
                    if addmeta := self.config.pluginobjs['recognition'][plugin].recognize(
                            metadata=self.metadata):
                        self.metadata = recognition_replacement(config=self.config,
                                                                metadata=self.metadata,
                                                                addmeta=addmeta)
                except Exception as error:  # pylint: disable=broad-except
                    logging.error('%s threw exception %s', plugin, error, exc_info=True)

        self._mb_fallback()

        if self.metadata and self.metadata.get('artist'):
            self.metadata['imagecacheartist'] = nowplaying.utils.normalize_text(
                self.metadata['artist'])

        if skipplugins:
            return

        if self.config.cparser.value(
                'artistextras/enabled',
                type=bool) and not self.config.cparser.value('control/beam', type=bool):
            tasks = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=3,
                                                       thread_name_prefix='artistextras') as pool:
                for priority in self.extraslist:
                    for plugin in self.extraslist[priority]:
                        try:
                            metalist = self.config.pluginobjs['artistextras'][plugin].providerinfo()
                            loop = asyncio.get_running_loop()
                            tasks.append(
                                loop.run_in_executor(
                                    pool, self.config.pluginobjs['artistextras'][plugin].download,
                                    self.metadata, self.imagecache))

                        except Exception as error:  # pylint: disable=broad-except
                            logging.error('%s threw exception %s', plugin, error, exc_info=True)

                for task in tasks:
                    if addmeta := await task:
                        self.metadata = recognition_replacement(config=self.config,
                                                                metadata=self.metadata,
                                                                addmeta=addmeta)

    def _generate_short_bio(self):
        if not self.metadata:
            return

        message = self.metadata['artistlongbio']
        message = message.replace('\n', ' ')
        message = message.replace('\r', ' ')
        message = str(message).strip()
        text = textwrap.TextWrapper(width=450).wrap(message)[0]
        tokens = nltk.sent_tokenize(text)

        nonotes = [sent for sent in tokens if not NOTE_RE.match(sent)]
        tokens = nonotes

        if tokens[-1][-1] in string.punctuation and tokens[-1][-1] not in [':', ',', ';', '-']:
            self.metadata['artistshortbio'] = ' '.join(tokens)
        else:
            self.metadata['artistshortbio'] = ' '.join(tokens[:-1])


class AudioMetadataRunner:  # pylint: disable=too-few-public-methods
    ''' run through audio_metadata '''

    def __init__(self, config: 'nowplaying.config.ConfigFile' = None):
        self.metadata = {}
        self.config = config

    def process(self, metadata):
        ''' process it '''

        if not metadata:
            return metadata

        if not metadata.get('filename'):
            return metadata

        self.metadata = metadata
        self._process_audio_metadata()
        return self.metadata

    def _process_audio_metadata_mp4_freeform(self, freeformparentlist):

        def _itunes(tempdata, freeform):
            convdict = {
                'LABEL': 'label',
                'originaldate': 'date',
                'DISCSUBTITLE': 'discsubtitle',
                'Acoustid Id': 'acoustidid',
                'MusicBrainz Album Id': 'musicbrainzalbumid',
                'MusicBrainz Track Id': 'musicbrainzrecordingid',
            }

            for src, dest in convdict.items():
                if freeform['name'] == src and not tempdata.get(dest):
                    tempdata[dest] = MP4FreeformDecoders[freeform.data_type](freeform.value)

            convdict = {
                'MusicBrainz Artist Id': 'musicbrainzartistid',
                'website': 'artistwebsites',
                'tsrc': 'isrc',
                'ISRC': 'isrc',
            }

            for src, dest in convdict.items():
                if freeform['name'] == src:
                    if tempdata.get(dest):
                        tempdata[dest].append(
                            str(MP4FreeformDecoders[freeform.data_type](freeform.value)))

                    else:
                        tempdata[dest] = [
                            str(MP4FreeformDecoders[freeform.data_type](freeform.value))
                        ]

            return tempdata

        tempdata = {}
        for freeformlist in freeformparentlist:
            for freeform in freeformlist:
                if freeform.description == 'com.apple.iTunes':
                    tempdata = _itunes(tempdata, freeform)

        self.metadata = recognition_replacement(config=self.config,
                                                metadata=self.metadata,
                                                addmeta=tempdata)

    def _process_audio_metadata_id3_usertext(self, usertextlist):

        if not self.metadata:
            self.metadata = {}

        for usertext in usertextlist:
            if usertext.description == 'Acoustid Id':
                self.metadata['acoustidid'] = usertext.text[0]
            elif usertext.description == 'DISCSUBTITLE':
                self.metadata['discsubtitle'] = usertext.text[0]
            elif usertext.description == 'MusicBrainz Album Id':
                self.metadata['musicbrainzalbumid'] = usertext.text[0]
            elif usertext.description == 'MusicBrainz Artist Id':
                self.metadata['musicbrainzartistid'] = usertext.text
            elif usertext.description == 'originalyear':
                self.metadata['date'] = usertext.text[0]

    def _process_audio_metadata_othertags(self, tags):  # pylint: disable=too-many-branches
        if not self.metadata:
            self.metadata = {}

        if 'discnumber' in tags and 'disc' not in self.metadata:
            text = tags['discnumber'][0].replace('[', '').replace(']', '')
            with contextlib.suppress(Exception):
                self.metadata['disc'], self.metadata['disc_total'] = text.split('/')

        if 'tracknumber' in tags and 'track' not in self.metadata:
            text = tags['tracknumber'][0].replace('[', '').replace(']', '')
            with contextlib.suppress(Exception):
                self.metadata['track'], self.metadata['track_total'] = text.split('/')
        for websitetag in ['WOAR', 'website']:
            if websitetag in tags and 'artistwebsites' not in self.metadata:
                if isinstance(tags[websitetag], list):
                    if not self.metadata.get('artistwebsites'):
                        self.metadata['artistwebsites'] = []
                    for tag in tags[websitetag]:
                        self.metadata['artistwebsites'].append(str(tag))
                else:
                    self.metadata['artistwebsites'] = [str(tags[websitetag])]

        if 'freeform' in tags:
            self._process_audio_metadata_mp4_freeform(tags.freeform)
        elif 'usertext' in tags:
            self._process_audio_metadata_id3_usertext(tags.usertext)

    def _process_audio_metadata_remaps(self, tags):
        if not self.metadata:
            self.metadata = {}

        # single:

        convdict = {
            'acoustid id': 'acoustidid',
            'date': 'date',
            'musicbrainz album id': 'musicbrainzalbumid',
            'musicbrainz_trackid': 'musicbrainzrecordingid',
            'publisher': 'label',
        }

        for src, dest in convdict.items():
            if not self.metadata.get(dest) and src in tags:
                self.metadata[dest] = str(tags[src][0])

        # lists
        convdict = {
            'musicbrainz artist id': 'musicbrainzartistid',
            'tsrc': 'isrc',
        }

        for src, dest in convdict.items():
            if dest not in self.metadata and src in tags:
                if isinstance(tags[src], list):
                    if not self.metadata.get(dest):
                        self.metadata[dest] = []
                    for tag in tags[src]:
                        self.metadata[dest].append(str(tag))
                else:
                    self.metadata[dest] = [str(tags[src])]

    def _process_audio_metadata(self):  # pylint: disable=too-many-branches
        if not self.metadata or not self.metadata.get('filename'):
            return

        try:
            base = nowplaying.vendor.audio_metadata.load(self.metadata['filename'])
        except Exception as error:  # pylint: disable=broad-except
            logging.error('audio_metadata could not process %s: %s', self.metadata['filename'],
                          error)
            return

        for key in [
                'album',
                'albumartist',
                'artist',
                'bpm',
                'comments',
                'composer',
                'discsubtitle',
                'duration',
                'genre',
                'key',
                'label',
                'title',
        ]:
            if key not in self.metadata and key in base.tags:
                if isinstance(base.tags[key], list):
                    self.metadata[key] = '/'.join(str(x) for x in base.tags[key])
                else:
                    self.metadata[key] = str(base.tags[key])

        if 'ufid' in base.tags:
            for index in base.tags.ufid:
                if index.owner == 'http://musicbrainz.org':
                    self.metadata['musicbrainzrecordingid'] = index.identifier.decode('utf-8')

        self._process_audio_metadata_remaps(base.tags)
        self._process_audio_metadata_othertags(base.tags)

        if 'bitrate' not in self.metadata and getattr(base, 'streaminfo'):
            self.metadata['bitrate'] = base.streaminfo['bitrate']

        if getattr(base, 'pictures') and 'coverimageraw' not in self.metadata:
            self.metadata['coverimageraw'] = base.pictures[0].data


def recognition_replacement(config: 'nowplaying.config.ConfigFile' = None,
                            metadata=None,
                            addmeta=None):
    ''' handle any replacements '''
    # if there is nothing in addmeta, then just bail early
    if not addmeta:
        return metadata

    if not metadata:
        metadata = {}

    for meta in addmeta:
        if meta in ['artist', 'title', 'artistwebsites']:
            if config.cparser.value(f'recognition/replace{meta}', type=bool) and addmeta.get(meta):
                metadata[meta] = addmeta[meta]
            elif not metadata.get(meta) and addmeta.get(meta):
                metadata[meta] = addmeta[meta]
        elif not metadata.get(meta) and addmeta.get(meta):
            metadata[meta] = addmeta[meta]
    return metadata


def main():
    ''' entry point as a standalone app'''
    logging.basicConfig(
        format='%(asctime)s %(process)d %(threadName)s %(module)s:%(funcName)s:%(lineno)d ' +
        '%(levelname)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z',
        level=logging.DEBUG)
    logging.captureWarnings(True)
    bundledir = os.path.abspath(os.path.dirname(__file__))
    config = nowplaying.config.ConfigFile(bundledir=bundledir)
    testmeta = {'filename': sys.argv[1]}
    myclass = MetadataProcessors(config=config)
    testdata = asyncio.run(myclass.getmoremetadata(metadata=testmeta))
    if 'coverimageraw' in testdata:
        print('got an image')
        del testdata['coverimageraw']
    print(testdata)


if __name__ == "__main__":
    main()
