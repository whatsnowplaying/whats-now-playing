#!/usr/bin/env python3
''' pull out metadata '''

import logging
import os
import sys

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

        if 'filename' not in self.metadata:
            logging.debug('No filename')
            return

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

    def _process_hostmeta(self):
        ''' add the host metadata so other subsystems can use it '''
        if self.config.cparser.value('weboutput/httpenabled', type=bool):
            self.metadata['httpport'] = self.config.cparser.value(
                'weboutput/httpport', type=int)
        hostmeta = nowplaying.hostmeta.gethostmeta()
        for key, value in hostmeta.items():
            self.metadata[key] = value

    def _process_audio_metadata_mp4_freeform(self, freeformparentlist):
        for freeformlist in freeformparentlist:
            for freeform in freeformlist:
                if freeform.description == 'com.apple.iTunes':
                    if freeform['name'] == 'originaldate':
                        self.metadata['date'] = MP4FreeformDecoders[
                            freeform.data_type](freeform.value)
                    if freeform['name'] == 'LABEL':
                        self.metadata['label'] = MP4FreeformDecoders[
                            freeform.data_type](freeform.value)
                    if freeform['name'] == 'DISCSUBTITLE':
                        self.metadata['discsubtitle'] = MP4FreeformDecoders[
                            freeform.data_type](freeform.value)
                    if freeform['name'] == 'MusicBrainz Album Id':
                        self.metadata[
                            'musicbrainzalbumid'] = MP4FreeformDecoders[
                                freeform.data_type](freeform.value)
                    if freeform['name'] == 'MusicBrainz Artist Id':
                        self.metadata[
                            'musicbrainzartistid'] = MP4FreeformDecoders[
                                freeform.data_type](freeform.value)
                    if freeform['name'] == 'Acoustid Id':
                        self.metadata['acoustidid'] = MP4FreeformDecoders[
                            freeform.data_type](freeform.value)
                    if freeform['name'] == 'MusicBrainz Track Id':
                        self.metadata[
                            'musicbrainzrecordingid'] = MP4FreeformDecoders[
                                freeform.data_type](freeform.value)

    def _process_audio_metadata_id3_usertext(self, usertextlist):
        for usertext in usertextlist:
            if usertext.description == 'Acoustid Id':
                self.metadata['acoustidid'] = usertext.text[0]
            elif usertext.description == 'DISCSUBTITLE':
                self.metadata['discsubtitle'] = usertext.text[0]
            elif usertext.description == 'MusicBrainz Album Id':
                self.metadata['musicbrainzalbumid'] = usertext.text[0]
            elif usertext.description == 'MusicBrainz Artist Id':
                self.metadata['musicbrainzartistid'] = usertext.text[0]
            elif usertext.description == 'MusicBrainz Release Track Id':
                self.metadata['musicbrainzrecordingid'] = usertext.text[0]
            elif usertext.description == 'originalyear':
                self.metadata['date'] = usertext.text[0]

    def _process_audio_metadata_specials(self, tags):

        convdict = {
            'acoustid id': 'acoustidid',
            'date': 'date',
            'musicbrainz album id': 'musicbrainzalbumid',
            'musicbrainz artist id': 'musicbrainzartistid',
            'musicbrainz release track id': 'musicbrainzrecordingid',
            'publisher': 'label',
            'tsrc': 'isrc',
        }

        for src, dest in convdict.items():
            if dest not in self.metadata and src in tags:
                if isinstance(tags[src], list):
                    self.metadata[dest] = '/'.join(str(x) for x in tags[src])
                else:
                    self.metadata[dest] = tags[src]

    def _process_audio_metadata(self):  # pylint: disable=too-many-branches
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
                'isrc',
                'key',
                'label',
                'title',
        ]:
            if key not in self.metadata and key in base.tags:
                if isinstance(base.tags[key], list):
                    self.metadata[key] = '/'.join(
                        str(x) for x in base.tags[key])
                else:
                    self.metadata[key] = base.tags[key]

        self._process_audio_metadata_specials(base.tags)

        if 'discnumber' in base.tags and 'disc' not in self.metadata:
            text = base.tags['discnumber'][0].replace('[', '').replace(']', '')
            try:
                self.metadata['disc'], self.metadata[
                    'disc_total'] = text.split('/')
            except:  # pylint: disable=bare-except
                pass

        if 'tracknumber' in base.tags and 'track' not in self.metadata:
            text = base.tags['tracknumber'][0].replace('[',
                                                       '').replace(']', '')
            try:
                self.metadata['track'], self.metadata[
                    'track_total'] = text.split('/')
            except:  # pylint: disable=bare-except
                pass

        if 'freeform' in base.tags:
            self._process_audio_metadata_mp4_freeform(base.tags.freeform)
        elif 'usertext' in base.tags:
            self._process_audio_metadata_id3_usertext(base.tags.usertext)

        if 'bitrate' not in self.metadata and getattr(base, 'streaminfo'):
            self.metadata['bitrate'] = base.streaminfo['bitrate']

        if getattr(base, 'pictures') and 'coverimageraw' not in self.metadata:
            self.metadata['coverimageraw'] = base.pictures[0].data

    def _process_tinytag(self):
        ''' given a chunk of metadata, try to fill in more '''
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
                        self.metadata[key] = extra[key]

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
            if meta in ['artist', 'title']:
                if self.config.cparser.value(f'recognition/replace{meta}',
                                             type=bool) and addmeta.get(meta):
                    self.metadata[meta] = addmeta[meta]

            elif not self.metadata.get(meta) and addmeta.get(meta):
                self.metadata[meta] = addmeta[meta]

    def _process_plugins(self):
        if self.metadata.get('musicbrainzartistid'):
            logging.debug(
                'musicbrainz recordingid detected; attempting shortcuts')
            musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(
                config=self.config)
            metalist = musicbrainz.providerinfo()
            if any(meta not in self.metadata for meta in metalist):
                addmeta = musicbrainz.recordingid(
                    self.metadata['musicbrainzrecordingid'])
                self._recognition_replacement(addmeta)
        elif self.metadata.get('isrc'):
            logging.debug('Preprocessing with musicbrainz isrc')
            musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(
                config=self.config)
            metalist = musicbrainz.providerinfo()
            if any(meta not in self.metadata for meta in metalist):
                addmeta = musicbrainz.isrc(self.metadata['isrc'].split('/'))
                self._recognition_replacement(addmeta)

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


def main():
    ''' entry point as a standalone app'''
    logging.basicConfig(level=logging.DEBUG)
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
