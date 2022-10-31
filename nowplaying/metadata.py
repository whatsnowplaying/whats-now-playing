#!/usr/bin/env python3
''' pull out metadata '''

import logging
import os
import string
import sys
import textwrap

import nltk

import nowplaying.config
import nowplaying.hostmeta
import nowplaying.vendor.audio_metadata
from nowplaying.vendor.audio_metadata.formats.mp4_tags import MP4FreeformDecoders
import nowplaying.vendor.tinytag


class MetadataProcessors:  # pylint: disable=too-few-public-methods
    ''' Run through a bunch of different metadata processors '''

    def __init__(self, metadata, imagecache=None, config=None):
        self.metadata = metadata
        self.imagecache = imagecache
        if config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()

        #if 'filename' not in self.metadata:
        #    logging.debug('No filename')
        #    return

        if 'artistfanarturls' not in self.metadata:
            self.metadata['artistfanarturls'] = []

        for processor in 'hostmeta', 'audio_metadata', 'tinytag', 'image2png', 'plugins':
            logging.debug('running %s', processor)
            func = getattr(self, f'_process_{processor}')
            func()

        if 'publisher' in self.metadata:
            if 'label' not in self.metadata:
                self.metadata['label'] = self.metadata['publisher']
            del self.metadata['publisher']

        if 'year' in self.metadata:
            if 'date' not in self.metadata:
                self.metadata['date'] = self.metadata['year']
            del self.metadata['year']

        if self.metadata.get(
                'artistlongbio') and not self.metadata.get('artistshortbio'):
            self._generate_short_bio()

        self._uniqlists()

        self._strip_identifiers()

    def _strip_identifiers(self):

        if self.config.cparser.value('settings/stripextras',
                                     type=bool) and self.metadata.get('title'):
            self.metadata['title'] = nowplaying.utils.titlestripper_advanced(
                title=self.metadata['title'],
                title_regex_list=self.config.getregexlist())

    def _uniqlists(self):
        lists = ['artistwebsites', 'isrc', 'musicbrainzartistid']

        for listname in lists:
            if self.metadata.get(listname):
                newlist = sorted(set(self.metadata[listname]))
                self.metadata[listname] = newlist

    def _process_hostmeta(self):
        ''' add the host metadata so other subsystems can use it '''
        if self.config.cparser.value('weboutput/httpenabled', type=bool):
            self.metadata['httpport'] = self.config.cparser.value(
                'weboutput/httpport', type=int)
        hostmeta = nowplaying.hostmeta.gethostmeta()
        for key, value in hostmeta.items():
            self.metadata[key] = value

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
                    tempdata[dest] = MP4FreeformDecoders[freeform.data_type](
                        freeform.value)

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
                            str(MP4FreeformDecoders[freeform.data_type](
                                freeform.value)))

                    else:
                        tempdata[dest] = [
                            str(MP4FreeformDecoders[freeform.data_type](
                                freeform.value))
                        ]

            return tempdata

        tempdata = {}
        for freeformlist in freeformparentlist:
            for freeform in freeformlist:
                if freeform.description == 'com.apple.iTunes':
                    tempdata = _itunes(tempdata, freeform)

        self._recognition_replacement(tempdata)

    def _process_audio_metadata_id3_usertext(self, usertextlist):
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

    def _process_audio_metadata_othertags(self, tags):
        if 'discnumber' in tags and 'disc' not in self.metadata:
            text = tags['discnumber'][0].replace('[', '').replace(']', '')
            try:
                self.metadata['disc'], self.metadata[
                    'disc_total'] = text.split('/')
            except:  # pylint: disable=bare-except
                pass

        if 'tracknumber' in tags and 'track' not in self.metadata:
            text = tags['tracknumber'][0].replace('[', '').replace(']', '')
            try:
                self.metadata['track'], self.metadata[
                    'track_total'] = text.split('/')
            except:  # pylint: disable=bare-except
                pass

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
        if not self.metadata.get('filename'):
            return

        try:
            base = nowplaying.vendor.audio_metadata.load(
                self.metadata['filename'])
        except Exception as error:  # pylint: disable=broad-except
            logging.debug('audio_metadata could not process %s: %s',
                          self.metadata['filename'], error)
            return

        for key in [
                'album',
                'albumartist',
                'artist',
                'bpm',
                'comments',
                'composer',
                'discsubtitle',
                'genre',
                'key',
                'label',
                'title',
        ]:
            if key not in self.metadata and key in base.tags:
                if isinstance(base.tags[key], list):
                    self.metadata[key] = '/'.join(
                        str(x) for x in base.tags[key])
                else:
                    self.metadata[key] = str(base.tags[key])

        if 'ufid' in base.tags:
            for index in base.tags.ufid:
                if index.owner == 'http://musicbrainz.org':
                    self.metadata[
                        'musicbrainzrecordingid'] = index.identifier.decode(
                            'utf-8')

        self._process_audio_metadata_remaps(base.tags)
        self._process_audio_metadata_othertags(base.tags)

        if 'bitrate' not in self.metadata and getattr(base, 'streaminfo'):
            self.metadata['bitrate'] = base.streaminfo['bitrate']

        if getattr(base, 'pictures') and 'coverimageraw' not in self.metadata:
            self.metadata['coverimageraw'] = base.pictures[0].data

    def _process_tinytag(self):
        ''' given a chunk of metadata, try to fill in more '''
        if not self.metadata.get('filename'):
            return

        try:
            tag = nowplaying.vendor.tinytag.TinyTag.get(
                self.metadata['filename'], image=True)
        except nowplaying.vendor.tinytag.tinytag.TinyTagException as error:
            logging.error('tinytag could not process %s: %s',
                          self.metadata['filename'], error)
            return

        if tag:
            for key in [
                    'album', 'albumartist', 'artist', 'bitrate', 'bpm',
                    'comments', 'composer', 'disc', 'disc_total', 'genre',
                    'key', 'lang', 'publisher', 'title', 'track',
                    'track_total', 'year'
            ]:
                if key not in self.metadata and hasattr(tag, key) and getattr(
                        tag, key):
                    self.metadata[key] = getattr(tag, key)

            if getattr(tag, 'extra'):
                extra = getattr(tag, 'extra')
                for key in ['isrc']:
                    if extra.get(key):
                        self.metadata[key] = extra[key].split('/')

            if 'date' not in self.metadata and hasattr(
                    tag, 'year') and getattr(tag, 'year'):
                self.metadata['date'] = getattr(tag, 'year')

            if 'coverimageraw' not in self.metadata:
                self.metadata['coverimageraw'] = tag.get_image()

    def _process_image2png(self):
        # always convert to png

        if 'coverimageraw' not in self.metadata or not self.metadata[
                'coverimageraw']:
            return

        self.metadata['coverimageraw'] = nowplaying.utils.image2png(
            self.metadata['coverimageraw'])
        self.metadata['coverimagetype'] = 'png'
        self.metadata['coverurl'] = 'cover.png'

    def _recognition_replacement(self, addmeta):

        # if there is nothing in addmeta, then just bail early
        if not addmeta:
            return

        for meta in addmeta:
            if meta in ['artist', 'title', 'artistwebsites']:
                if self.config.cparser.value(f'recognition/replace{meta}',
                                             type=bool) and addmeta.get(meta):
                    self.metadata[meta] = addmeta[meta]
                elif not self.metadata.get(meta) and addmeta.get(meta):
                    self.metadata[meta] = addmeta[meta]
            elif not self.metadata.get(meta) and addmeta.get(meta):
                self.metadata[meta] = addmeta[meta]

    def _musicbrainz(self):
        musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(
            config=self.config)
        metalist = musicbrainz.providerinfo()

        addmeta = {}

        if self.metadata.get('musicbrainzrecordingid'):
            logging.debug(
                'musicbrainz recordingid detected; attempting shortcuts')
            if any(meta not in self.metadata for meta in metalist):
                addmeta = musicbrainz.recordingid(
                    self.metadata['musicbrainzrecordingid'])
                self._recognition_replacement(addmeta)
        elif self.metadata.get('isrc'):
            logging.debug('Preprocessing with musicbrainz isrc')
            if any(meta not in self.metadata for meta in metalist):
                addmeta = musicbrainz.isrc(self.metadata['isrc'])
                self._recognition_replacement(addmeta)
        elif self.metadata.get('musicbrainzartistid'):
            logging.debug('Preprocessing with musicbrainz artistid')
            if any(meta not in self.metadata for meta in metalist):
                addmeta = musicbrainz.artistids(
                    self.metadata['musicbrainzartistid'])
                self._recognition_replacement(addmeta)

        return addmeta

    def _process_plugins(self):
        addmeta = self._musicbrainz()

        for plugin in self.config.plugins['recognition']:
            metalist = self.config.pluginobjs['recognition'][
                plugin].providerinfo()
            provider = any(meta not in self.metadata for meta in metalist)
            if provider:
                try:
                    if addmeta := self.config.pluginobjs['recognition'][
                            plugin].recognize(metadata=self.metadata):
                        self._recognition_replacement(addmeta)
                except Exception as error:  # pylint: disable=broad-except
                    logging.debug('%s threw exception %s',
                                  plugin,
                                  error,
                                  exc_info=True)

        if self.config.cparser.value('artistextras/enabled', type=bool):
            for plugin in self.config.plugins['artistextras']:
                metalist = self.config.pluginobjs['artistextras'][
                    plugin].providerinfo()
                try:
                    if addmeta := self.config.pluginobjs['artistextras'][
                            plugin].download(metadata=self.metadata,
                                             imagecache=self.imagecache):
                        self._recognition_replacement(addmeta)

                except Exception as error:  # pylint: disable=broad-except
                    logging.debug('%s threw exception %s',
                                  plugin,
                                  error,
                                  exc_info=True)

    def _generate_short_bio(self):
        message = self.metadata['artistlongbio']
        message = message.replace('\n', ' ')
        message = message.replace('\r', ' ')
        message = str(message).strip()
        text = textwrap.TextWrapper(width=450).wrap(message)[0]
        tokens = nltk.sent_tokenize(text)

        if tokens[-1][-1] in string.punctuation and tokens[-1][-1] not in [
                ':', ',', ';', '-'
        ]:
            self.metadata['artistshortbio'] = ' '.join(tokens)
        else:
            self.metadata['artistshortbio'] = ' '.join(tokens[:-1])


def main():
    ''' entry point as a standalone app'''
    logging.basicConfig(
        format=
        '%(asctime)s %(process)d %(threadName)s %(module)s:%(funcName)s:%(lineno)d '
        + '%(levelname)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z',
        level=logging.DEBUG)
    logging.captureWarnings(True)
    bundledir = os.path.abspath(os.path.dirname(__file__))
    nowplaying.config.ConfigFile(bundledir=bundledir)
    metadata = {'filename': sys.argv[1]}
    myclass = MetadataProcessors(metadata=metadata)
    metadata = myclass.metadata
    if 'coverimageraw' in metadata:
        print('got an image')
        del metadata['coverimageraw']
    print(metadata)


if __name__ == "__main__":
    main()
