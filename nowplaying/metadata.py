#!/usr/bin/env python3
''' pull out metadata '''

import io
import logging
import sys

import PIL.Image
import nowplaying.config
import nowplaying.vendor.audio_metadata
import nowplaying.vendor.tinytag


class MetadataProcessors:  # pylint: disable=too-few-public-methods
    ''' Run through a bunch of different metadata processors '''
    def __init__(self, metadata):
        self.metadata = metadata
        self.config = nowplaying.config.ConfigFile()

        if 'filename' not in self.metadata:
            logging.debug('No filename')
            return

        for processor in 'audio_metadata', 'tinytag', 'image2png', 'plugins':
            logging.debug('running %s', processor)
            func = getattr(self, f'_process_{processor}')
            func()

        if 'publisher' in self.metadata:
            if 'label' not in self.metadata:
                metadata['label'] = metadata['publisher']
            del metadata['publisher']

        if 'year' in self.metadata:
            if 'date' not in self.metadata:
                self.metadata['date'] = self.metadata['year']
            del metadata['year']

    def _process_audio_metadata(self):
        try:
            base = nowplaying.vendor.audio_metadata.load(
                self.metadata['filename'])
        except Exception as error:  # pylint: disable=broad-except
            logging.debug('audio_metadata could not process %s: %s',
                          self.metadata['filename'], error)
            return

        for key in [
                'album', 'albumartist', 'artist', 'bpm', 'comments',
                'composer', 'genre', 'key', 'label', 'title'
        ]:
            if key not in self.metadata and key in base.tags:
                if isinstance(base.tags[key], list):
                    self.metadata[key] = '/'.join(
                        str(x) for x in base.tags[key])
                else:
                    self.metadata[key] = base.tags[key]

        if 'date' in base.tags and 'date' not in self.metadata:
            self.metadata['date'] = base.tags['date'][0]

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

        coverimage = self.metadata['coverimageraw']
        imgbuffer = io.BytesIO(coverimage)
        image = PIL.Image.open(imgbuffer)
        image.save(imgbuffer, format='png')
        self.metadata['coverimageraw'] = imgbuffer.getvalue()
        self.metadata['coverimagetype'] = 'png'
        self.metadata['coverurl'] = 'cover.png'

    def _recogintion_replacement(self, addmeta):
        for replacelist in ['artist', 'title']:
            if self.config.cparser.value(f'recognition/replace{replacelist}',
                                         type=bool) and replacelist in addmeta:
                self.metadata[replacelist] = addmeta[replacelist]
                del addmeta[replacelist]

        for meta in addmeta:
            if meta not in self.metadata:
                self.metadata[meta] = addmeta[meta]

    def _process_plugins(self):
        for plugin in self.config.plugins['recognition']:
            metalist = self.config.pluginobjs['recognition'][
                plugin].providerinfo()
            provider = any(meta not in self.metadata for meta in metalist)
            if provider:
                try:
                    addmeta = self.config.pluginobjs['recognition'][
                        plugin].recognize(self.metadata)
                    if addmeta:
                        self._recogintion_replacement(addmeta)
                except Exception as error:  # pylint: disable=broad-except
                    logging.debug('%s threw exception %s', plugin, error)


def main():
    ''' entry point as a standalone app'''
    logging.basicConfig(level=logging.DEBUG)
    logging.captureWarnings(True)
    metadata = {'filename': sys.argv[1]}
    myclass = MetadataProcessors(metadata=metadata)
    metadata = myclass.metadata
    if 'coverimageraw' in metadata:
        print('got an image')
        del metadata['coverimageraw']
    print(metadata)


if __name__ == "__main__":
    main()
