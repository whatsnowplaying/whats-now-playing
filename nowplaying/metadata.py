#!/usr/bin/env python3
''' pull out metadata '''

import asyncio
import copy
import contextlib
import logging
import re
import os
import string
import sys
import textwrap
import typing as t

import nltk
import url_normalize

import nowplaying.config
import nowplaying.hostmeta
import nowplaying.musicbrainz
import nowplaying.utils
from nowplaying.vendor import tinytag

import nowplaying.vendor.audio_metadata
from nowplaying.vendor.audio_metadata.formats.mp4_tags import MP4FreeformDecoders

NOTE_RE = re.compile('N(?i:ote):')
YOUTUBE_MATCH_RE = re.compile('^https?://[www.]*youtube.com/watch.v=')


def _date_calc(datedata: dict) -> t.Optional[str]:
    if datedata.get('originalyear') and datedata.get(
            'date') and datedata['originalyear'] in datedata['date']:
        del datedata['originalyear']

    if datedata.get('originalyear') and datedata.get(
            'year') and datedata['originalyear'] in datedata['year']:
        del datedata['originalyear']

    datelist = list(datedata.values())
    gooddate = None
    datelist = sorted(datelist)
    if len(datelist) > 2:
        if datelist[0] in datelist[1]:
            gooddate = datelist[1]
    elif datelist:
        gooddate = datelist[0]

    if gooddate:
        #logging.debug("realdate: %s rest: %s", gooddate, gooddate)
        return gooddate
    return None


class MetadataProcessors:  # pylint: disable=too-few-public-methods
    ''' Run through a bunch of different metadata processors '''

    def __init__(self, config: 'nowplaying.config.ConfigFile' = None):
        self.metadata: dict[str, t.Any] = {}
        self.imagecache = None
        if config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()

        self.extraslist = self._sortextras()
        #logging.debug("%s %s", type(self.extraslist), self.extraslist)

    def _sortextras(self) -> dict[int, list[str]]:
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

        if self.metadata.get('coverimageraw') and self.imagecache and self.metadata.get('album'):
            logging.debug("Placing provided front cover")
            self.imagecache.put_db_cachekey(identifier=self.metadata['album'],
                                            srclocation=f"{self.metadata['album']}_provided_0",
                                            imagetype="front_cover",
                                            content=self.metadata['coverimageraw'])

        try:
            for processor in 'hostmeta', 'audio_metadata', 'tinytag', 'image2png':
                logging.debug('running %s', processor)
                func = getattr(self, f'_process_{processor}')
                func()
        except Exception:  #pylint: disable=broad-except
            logging.exception('Ignoring sub-metaproc failure.')

        await self._process_plugins(skipplugins)

        if 'publisher' in self.metadata:
            if 'label' not in self.metadata:
                self.metadata['label'] = self.metadata['publisher']
            del self.metadata['publisher']

        self._fix_dates()

        if self.metadata.get('artistlongbio') and not self.metadata.get('artistshortbio'):
            self._generate_short_bio()

        if not self.metadata.get('artistlongbio') and self.metadata.get('artistshortbio'):
            self.metadata['artistlongbio'] = self.metadata['artistshortbio']

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
        try:
            self.metadata = AudioMetadataRunner(
                config=self.config, imagecache=self.imagecache).process(metadata=self.metadata)
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("AudioMetadata crashed: %s", err)

    def _process_tinytag(self):
        try:
            tempdata = TinyTagRunner(imagecache=self.imagecache).process(
                metadata=copy.copy(self.metadata))
            self.metadata = recognition_replacement(config=self.config,
                                                    metadata=self.metadata,
                                                    addmeta=tempdata)
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("TinyTag crashed: %s", err)

    def _process_image2png(self):
        # always convert to png

        if not self.metadata or 'coverimageraw' not in self.metadata or not self.metadata[
                'coverimageraw']:
            return

        self.metadata['coverimageraw'] = nowplaying.utils.image2png(self.metadata['coverimageraw'])
        self.metadata['coverimagetype'] = 'png'
        self.metadata['coverurl'] = 'cover.png'

    async def _musicbrainz(self):
        if not self.metadata:
            return None

        # Check if we already have key MusicBrainz data to avoid unnecessary lookups
        if (self.metadata.get('musicbrainzartistid') and self.metadata.get('musicbrainzrecordingid')
                and self.metadata.get('isrc')):
            logging.debug('Skipping MusicBrainz lookup - already have key identifiers')
            return

        musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(config=self.config)
        addmeta = await musicbrainz.recognize(copy.copy(self.metadata))
        self.metadata = recognition_replacement(config=self.config,
                                                metadata=self.metadata,
                                                addmeta=addmeta)

    async def _mb_fallback(self):
        ''' at least see if album can be found '''

        addmeta = {}
        # user does not want fallback support
        if not self.metadata or not self.config.cparser.value('musicbrainz/fallback', type=bool):
            return

        # either missing key data or has already been processed
        if (self.metadata.get('isrc') or self.metadata.get('musicbrainzartistid')
                or self.metadata.get('musicbrainzrecordingid') or not self.metadata.get('artist')
                or not self.metadata.get('title')):
            return

        logging.debug('Attempting musicbrainz fallback')

        musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(config=self.config)
        addmeta = await musicbrainz.lastditcheffort(copy.copy(self.metadata))
        self.metadata = recognition_replacement(config=self.config,
                                                metadata=self.metadata,
                                                addmeta=addmeta)

        # handle the youtube download case special
        if (not addmeta or not addmeta.get('album')) and ' - ' in self.metadata['title']:
            if comments := self.metadata.get('comments'):
                if YOUTUBE_MATCH_RE.match(comments):
                    await self._mb_youtube_fallback(musicbrainz)

    async def _mb_youtube_fallback(self, musicbrainz):
        if not self.metadata:
            return
        addmeta2 = copy.deepcopy(self.metadata)
        artist, title = self.metadata['title'].split(' - ')
        addmeta2['artist'] = artist.strip()
        addmeta2['title'] = title.strip()

        logging.debug('Youtube video fallback with %s and %s', artist, title)

        try:
            if addmeta := await musicbrainz.lastditcheffort(addmeta2):
                self.metadata['artist'] = artist
                self.metadata['title'] = title
                self.metadata = recognition_replacement(config=self.config,
                                                        metadata=self.metadata,
                                                        addmeta=addmeta)
        except Exception:  #pylint: disable=broad-except
            logging.exception('Ignoring fallback failure.')

    async def _process_plugins(self, skipplugins):
        await self._musicbrainz()

        for plugin in self.config.plugins['recognition']:
            metalist = self.config.pluginobjs['recognition'][plugin].providerinfo()
            provider = any(meta not in self.metadata for meta in metalist)
            if provider:
                try:
                    if addmeta := await self.config.pluginobjs['recognition'][plugin].recognize(
                            metadata=self.metadata):
                        self.metadata = recognition_replacement(config=self.config,
                                                                metadata=self.metadata,
                                                                addmeta=addmeta)
                except Exception as error:  # pylint: disable=broad-except
                    logging.error('%s threw exception %s', plugin, error, exc_info=True)

        await self._mb_fallback()

        if self.metadata and self.metadata.get('artist'):
            self.metadata['imagecacheartist'] = nowplaying.utils.normalize_text(
                self.metadata['artist'])

        if skipplugins:
            return

        if self.config.cparser.value(
                'artistextras/enabled',
                type=bool) and not self.config.cparser.value('control/beam', type=bool):
            await self._artist_extras()

    async def _artist_extras(self):  # pylint: disable=too-many-branches
        """Efficiently process artist extras plugins using native async calls"""
        tasks: list[tuple[str, asyncio.Task]] = []

        # Calculate dynamic timeout based on delay setting
        # With apicache integration, we need more time for cache misses but still be responsive
        base_delay = self.config.cparser.value('settings/delay', type=float, defaultValue=10.0)
        timeout = min(max(base_delay * 1.2, 5.0), 15.0)  # 5-15 second range

        # Start all plugin tasks concurrently using native async methods
        for _, plugins in self.extraslist.items():
            for plugin in plugins:
                try:
                    plugin_obj = self.config.pluginobjs['artistextras'][plugin]
                    # All artist extras plugins now have async support
                    task = asyncio.create_task(
                        plugin_obj.download_async(self.metadata, self.imagecache))
                    tasks.append((plugin, task))
                    logging.debug('Started %s plugin task', plugin)
                except Exception as error:  # pylint: disable=broad-except
                    logging.error('%s threw exception during setup: %s',
                                  plugin,
                                  error,
                                  exc_info=True)

        if not tasks:
            return

        # Wait for tasks with dynamic timeout and early completion detection
        try:
            # Use asyncio.wait with timeout instead of sleep + cancel
            done, pending = await asyncio.wait(
                [task for _, task in tasks],
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED)

            # Process completed tasks immediately
            for plugin, task in tasks:
                if task in done:
                    try:
                        addmeta = await task
                        if addmeta:
                            self.metadata = recognition_replacement(config=self.config,
                                                                    metadata=self.metadata,
                                                                    addmeta=addmeta)
                            logging.debug('%s plugin completed successfully', plugin)
                        else:
                            logging.debug('%s plugin returned no data', plugin)
                    except Exception as error:  # pylint: disable=broad-except
                        logging.error('%s plugin failed: %s', plugin, error, exc_info=True)

                elif task in pending:
                    logging.debug('%s plugin timed out after %ss', plugin, timeout)
                    task.cancel()

            # Wait for cancelled tasks to clean up properly
            if pending:
                try:
                    await asyncio.gather(*pending, return_exceptions=True)
                except Exception as cleanup_error:  # pylint: disable=broad-except
                    logging.warning('Exception during task cleanup: %s', cleanup_error)

        except Exception as error:  # pylint: disable=broad-except
            logging.error('Artist extras processing failed: %s', error, exc_info=True)
            # Cancel any remaining tasks and wait for cleanup
            remaining_tasks = [task for _, task in tasks if not task.done()]
            for task in remaining_tasks:
                task.cancel()
            if remaining_tasks:
                try:
                    await asyncio.gather(*remaining_tasks, return_exceptions=True)
                except Exception as cleanup_error:  # pylint: disable=broad-except
                    logging.warning('Exception during task cleanup in exception handler: %s',
                                   cleanup_error)

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


class TinyTagRunner:  # pylint: disable=too-few-public-methods
    ''' tinytag manager '''

    def __init__(self, imagecache: "nowplaying.imagecache.ImageCache" = None):
        self.imagecache = imagecache
        self.metadata = {}
        self.datedata = {}

    @staticmethod
    def tt_date_calc(tag) -> t.Optional[str]:
        ''' deal with tinytag dates '''
        datedata = {}
        extra = getattr(tag, "extra")
        for datetype in ['originaldate', 'tdor', 'originalyear', 'tory', 'date', 'year']:
            if hasattr(tag, datetype) and getattr(tag, datetype):
                datedata[datetype] = getattr(tag, datetype)
            elif extra.get(datetype):
                datedata[datetype] = extra[datetype]
        return _date_calc(datedata)

    def process(self, metadata) -> dict:  # pylint: disable=too-many-branches
        ''' given a chunk of metadata, try to fill in more '''
        self.metadata = metadata

        if not metadata or not metadata.get('filename'):
            return metadata

        try:
            tag = tinytag.TinyTag.get(self.metadata['filename'], image=True)
        except tinytag.tinytag.TinyTagException as error:
            logging.error('tinytag could not process %s: %s', self.metadata['filename'], error)
            return metadata

        if tag:
            self._got_tag(tag)

        return self.metadata

    def _ufid(self, extra):
        if ufid := extra.get('ufid'):
            if isinstance(ufid, str):
                key, value = ufid.split('\x00')
                if key == "http://musicbrainz.org":
                    self.metadata['musicbrainzrecordingid'] = value

    def _process_extra(self, extra):

        extra_mapping = {
            "acoustid id": "acoustidid",
            "bpm": "bpm",
            "isrc": "isrc",
            "key": "key",
            "composer": "composer",
            "musicbrainz album id": "musicbrainzalbumid",
            "musicbrainz artist id": "musicbrainzartistid",
            "musicbrainz_trackid": "musicbrainzrecordingid",
            "musicbrainz track id": "musicbrainzrecordingid",
            "musicbrainz_albumid": "musicbrainzalbumid",
            "musicbrainz_artistid": "musicbrainzartistid",
            "publisher": "publisher",
            "label": "label",
            "website": "artistwebsites",
        }

        for key, newkey in extra_mapping.items():
            if extra.get(key) and not self.metadata.get(newkey):
                #logging.debug("found {%s} -> {%s}: %s | %s", key, newkey, extra.get(key),
                #              type(extra.get(key)))
                if self.metadata.get(newkey):
                    continue

                if key in ["isrc", "musicbrainz_artistid", "musicbrainz artist id"] and isinstance(
                        extra[key], str):
                    if '/' in extra.get(key):
                        self.metadata[newkey] = extra[key].split('/')
                    elif ';' in extra.get(key):
                        self.metadata[newkey] = extra[key].split(';')
                    elif isinstance(extra[key], list):
                        self.metadata[newkey] = extra[key]
                    else:
                        self.metadata[newkey] = [extra[key]]
                        #logging.debug("%s %s", self.metadata[newkey], type(self.metadata[newkey]))
                else:
                    self.metadata[newkey] = extra[key]

    def _got_tag(self, tag):
        if not self.metadata.get('date'):
            if calcdate := self.tt_date_calc(tag):
                self.metadata['date'] = calcdate

        for key in [
                'album', 'albumartist', 'artist', 'bitrate', 'bpm', 'comment', 'comments', 'disc',
                'disc_total', 'duration', 'genre', 'key', 'lang', 'publisher', 'title', 'track',
                'track_total', 'label'
        ]:
            if key not in self.metadata and hasattr(tag, key) and getattr(tag, key):
                self.metadata[key] = str(getattr(tag, key))

        if self.metadata.get('comment') and not self.metadata.get('comments'):
            self.metadata['comments'] = self.metadata['comment']
            del self.metadata['comment']

        if getattr(tag, 'extra'):
            extra = getattr(tag, 'extra')

            self._ufid(extra)
            self._process_extra(extra)

        if tag.extra.get("url") and not self.metadata.get("artistwebsites"):
            urls = tag.extra["url"]
            if isinstance(urls, str) and urls.lower().count("http") == 1:
                self.metadata["artistwebsites"] = [urls]
            else:
                self.metadata["artistwebsites"] = urls

        if isinstance(self.metadata.get("artistwebsites"), str):
            self.metadata["artistwebsites"] = [self.metadata["artistwebsites"]]

        #logging.debug(tag)
        #logging.debug(tag.extra)

        self._images(tag.images)

    def _images(self, images):

        if 'coverimageraw' not in self.metadata and images.front_cover:
            self.metadata['coverimageraw'] = images.front_cover[0].data

        if images.front_cover and self.metadata.get("album") and self.imagecache:
            for index, cover in enumerate(images.front_cover):
                logging.debug("Placing audiofile_tt%s front cover", index)
                self.imagecache.put_db_cachekey(
                    identifier=self.metadata['album'],
                    srclocation=f"{self.metadata['album']}_audiofile_tt{index}",
                    imagetype="front_cover",
                    content=cover.data)


class AudioMetadataRunner:  # pylint: disable=too-few-public-methods
    ''' run through audio_metadata '''

    def __init__(self, config: 'nowplaying.config.ConfigFile' = None, imagecache=None):
        self.imagecache = imagecache
        self.metadata = {}
        self.config = config
        self.datedata = {}

    def process(self, metadata):
        ''' process it '''

        if not metadata:
            return metadata

        if not metadata.get('filename'):
            return metadata

        self.metadata = metadata
        self._process_audio_metadata()
        return self.metadata

    def _images(self, images: list[nowplaying.vendor.audio_metadata.Picture]):

        if 'coverimageraw' not in self.metadata:
            self.metadata['coverimageraw'] = images[0].data

        if self.metadata.get("album") and self.imagecache:
            for index, pic in enumerate(images):
                logging.debug("%s", type(pic))
                if isinstance(
                        pic,
                        nowplaying.vendor.audio_metadata.formats.mp4_tags.MP4Cover) and isinstance(
                            pic.format, nowplaying.vendor.audio_metadata.formats.MP4CoverFormat):
                    logging.debug("Placing audiofile_am%s MP4 front cover", index)
                    self.imagecache.put_db_cachekey(
                        identifier=self.metadata['album'],
                        srclocation=f"{self.metadata['album']}_audiofile_am{index}",
                        imagetype="front_cover",
                        content=pic.data)
                elif getattr(pic, "type") and pic.type == 3:
                    logging.debug("Placing audiofile_am%s %s front cover", index, type(pic))
                    self.imagecache.put_db_cachekey(
                        identifier=self.metadata['album'],
                        srclocation=f"{self.metadata['album']}_audiofile_am{index}",
                        imagetype="front_cover",
                        content=pic.data)
                else:
                    logging.debug("Ignoring audiofile_am%s %s %s", index, type(pic), pic.type)

    def _process_audio_metadata_mp4_freeform(self, freeformparentlist):

        def _itunes(tempdata, freeform):

            for src in ['originaldate', 'originalyear']:
                if freeform['name'] == src and not self.datedata.get(src):
                    self.datedata[src] = MP4FreeformDecoders[freeform.data_type](freeform.value)

            convdict = {
                'comment': 'comments',
                'LABEL': 'label',
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
                self.metadata['musicbrainzalbumid'] = usertext.text[0].split('/')
            elif usertext.description == 'MusicBrainz Artist Id':
                self.metadata['musicbrainzartistid'] = usertext.text[0].split('/')
            elif usertext.description == 'originalyear':
                self.datedata['originalyear'] = usertext.text[0]
            elif usertext.description == 'originaldate':
                self.datedata['date'] = usertext.text[0]

    def _process_audio_metadata_othertags(self, tags):  # pylint: disable=too-many-branches
        if not self.metadata:
            self.metadata = {}

        if 'discnumber' in tags and 'disc' not in self.metadata:
            text = tags['discnumber'][0].replace('[', '').replace(']', '')
            with contextlib.suppress(Exception):
                self.metadata['disc'], self.metadata['disc_total'] = text.split('/', maxsplit=2)

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
            'date': 'date',
            'originaldate': 'date',
        }

        for src in ['date', 'originaldate']:
            if not self.datedata.get(src) and src in tags:
                self.datedata[src] = str(tags[src][0])

        convdict = {
            'acoustid id': 'acoustidid',
            'musicbrainz album id': 'musicbrainzalbumid',
            'publisher': 'label',
            'comment': 'comments',
            'musicbrainz_trackid': 'musicbrainzrecordingid'
        }

        for src, dest in convdict.items():
            if not self.metadata.get(dest) and src in tags:
                self.metadata[dest] = str(tags[src][0])

        # lists
        convdict = {
            'musicbrainz artist id': 'musicbrainzartistid',
            'tsrc': 'isrc',
            'isrc': 'isrc',
            'musicbrainz_artistid': 'musicbrainzartistid',
        }

        for src, dest in convdict.items():
            if dest not in self.metadata and src in tags:
                #logging.debug("%s %s %s", src, type(tags[src]), tags[src])
                if '/' in tags[src][0]:
                    self.metadata[dest] = str(tags[src][0]).split('/')
                elif ';' in tags[src][0]:
                    self.metadata[dest] = str(tags[src][0]).split(';')
                else:
                    if not self.metadata.get(dest):
                        self.metadata[dest] = []
                    for tag in tags[src]:
                        self.metadata[dest].append(str(tag))

    def _process_audio_metadata(self):  # pylint: disable=too-many-branches
        if not self.metadata or not self.metadata.get('filename'):
            return

        try:
            base = nowplaying.vendor.audio_metadata.load(self.metadata['filename'])
        except Exception as error:  # pylint: disable=broad-except
            logging.error('audio_metadata could not process %s: %s', self.metadata['filename'],
                          error)
            return

        #logging.debug("%s", base.tags)
        for key in [
                'album',
                'albumartist',
                'artist',
                'bpm',
                'comment',
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
            self._images(base.pictures)

        self.metadata['date'] = _date_calc(self.datedata)


def recognition_replacement(config: 'nowplaying.config.ConfigFile' = None,
                            metadata=None,
                            addmeta=None) -> dict:
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
