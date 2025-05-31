#!/usr/bin/env python3
''' pull out metadata '''

import asyncio
import copy
import logging
import re
import os
import string
import sys
import textwrap
import typing as t

import nltk
import tinytag
import url_normalize

import nowplaying.config
import nowplaying.hostmeta
import nowplaying.musicbrainz
import nowplaying.tinytag_fixes
import nowplaying.utils

# Apply tinytag patches - will be called after logging is set up

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
            for processor in 'hostmeta', 'tinytag', 'image2png':
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

        try:
            musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(config=self.config)
            addmeta = await musicbrainz.recognize(copy.copy(self.metadata))
            self.metadata = recognition_replacement(config=self.config,
                                                    metadata=self.metadata,
                                                    addmeta=addmeta)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('MusicBrainz recognition failed: %s', error)

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
            logging.error('Ignoring fallback failure.')

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
            done, pending = await asyncio.wait([task for _, task in tasks],
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
                    logging.error('Exception during task cleanup: %s', cleanup_error)

        except Exception as error:  # pylint: disable=broad-except
            logging.error('Artist extras processing failed: %s', error)
            # Cancel any remaining tasks and wait for cleanup
            remaining_tasks = [task for _, task in tasks if not task.done()]
            for task in remaining_tasks:
                task.cancel()
            if remaining_tasks:
                try:
                    await asyncio.gather(*remaining_tasks, return_exceptions=True)
                except Exception as cleanup_error:  # pylint: disable=broad-except
                    logging.error('Exception during task cleanup in exception handler: %s',
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

    _patches_applied = False

    def __init__(self, imagecache: "nowplaying.imagecache.ImageCache" = None):
        self.imagecache = imagecache
        self.metadata = {}
        self.datedata = {}

        # Apply tinytag patches once after logging is set up
        if not TinyTagRunner._patches_applied:
            nowplaying.tinytag_fixes.apply_tinytag_patches()
            TinyTagRunner._patches_applied = True

    @staticmethod
    def tt_date_calc(tag) -> t.Optional[str]:
        ''' deal with tinytag dates '''
        datedata = {}
        other = getattr(tag, "other", {})
        for datetype in ['originaldate', 'tdor', 'originalyear', 'tory', 'date', 'year']:
            if hasattr(tag, datetype) and getattr(tag, datetype):
                datedata[datetype] = getattr(tag, datetype)
            elif other.get(datetype):
                # Convert lists to strings for date fields
                value = other[datetype]
                if isinstance(value, list) and value:
                    datedata[datetype] = str(value[0])
                else:
                    datedata[datetype] = value
        return _date_calc(datedata)

    def process(self, metadata) -> dict:  # pylint: disable=too-many-branches
        ''' given a chunk of metadata, try to fill in more '''
        self.metadata = metadata

        if not metadata or not metadata.get('filename'):
            return metadata

        try:
            tag = tinytag.TinyTag.get(self.metadata['filename'], image=True)
        except tinytag.TinyTagException as error:
            logging.error('tinytag could not process %s: %s', self.metadata['filename'], error)
            return metadata

        if tag:
            self._got_tag(tag)

        return self.metadata

    def _ufid(self, extra):
        if ufid := extra.get('ufid'):
            # Handle both string and list cases from tinytag 2.1.1
            ufid_str = ufid[0] if isinstance(ufid, list) and ufid else ufid
            if isinstance(ufid_str, bytes):
                ufid_str = ufid_str.decode('utf-8', errors='replace')
            if isinstance(ufid_str, str) and '\x00' in ufid_str:
                key, value = ufid_str.split('\x00')
                if key == "http://musicbrainz.org":
                    self.metadata['musicbrainzrecordingid'] = value

    def _split_delimited_string(self, value: str) -> list[str]:  # pylint: disable=no-self-use
        """Split a string on common delimiters."""
        if '/' in value:
            return value.split('/')
        if ';' in value:
            return value.split(';')
        return [value]

    def _process_list_field(self, value, newkey: str) -> None:
        """Process fields that should be stored as lists."""
        if isinstance(value, list):
            # Handle lists that might contain strings needing splitting
            result_list = []
            for item in value:
                item_str = str(item)
                result_list.extend(self._split_delimited_string(item_str))
            self.metadata[newkey] = result_list
        elif isinstance(value, str):
            self.metadata[newkey] = self._split_delimited_string(value)
        else:
            self.metadata[newkey] = [str(value)]

    def _process_single_field(self, value, newkey: str) -> None:
        """Process fields that should be stored as single values."""
        if isinstance(value, list) and value:
            self.metadata[newkey] = str(value[0])
        else:
            self.metadata[newkey] = value

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
            "set_subtitle": "discsubtitle",
        }

        list_fields = {"isrc", "musicbrainz_artistid", "musicbrainz artist id", "website"}

        for key, newkey in extra_mapping.items():
            if not extra.get(key) or self.metadata.get(newkey):
                continue

            if key in list_fields:
                self._process_list_field(extra[key], newkey)
            else:
                self._process_single_field(extra[key], newkey)

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

        if getattr(tag, 'other', None):
            other = getattr(tag, 'other')

            self._ufid(other)
            self._process_extra(other)

        if getattr(tag, 'other', {}).get("url") and not self.metadata.get("artistwebsites"):
            urls = tag.other["url"]
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
            self.metadata['coverimageraw'] = images.front_cover.data

        if self.metadata.get("album") and self.imagecache:
            # Get all images using as_dict() for tinytag 2.1.1 compatibility
            images_dict = images.as_dict()

            # Process all cover images (tinytag 2.1.1 stores multiple covers under 'cover' key)
            all_covers = images_dict.get('cover', [])
            if not all_covers and images_dict.get('front_cover'):
                # Fallback to front_cover if no cover images found
                all_covers = images_dict.get('front_cover', [])

            for index, cover in enumerate(all_covers):
                logging.debug("Placing audiofile_tt%s front cover", index)
                self.imagecache.put_db_cachekey(
                    identifier=self.metadata['album'],
                    srclocation=f"{self.metadata['album']}_audiofile_tt{index}",
                    imagetype="front_cover",
                    content=cover.data)


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
