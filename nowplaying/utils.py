#!/usr/bin/env python3
''' handler to read the metadata from various file formats '''

#
# For now, this module is primarily a wrapper around tinytag
# with the idea that in the future there may be multiple
# engines or custom handling (pull tags from mixxing software?)
#

import io
import logging
import os
import sys

import jinja2
import tinytag
import PIL.Image


class TemplateHandler():  # pylint: disable=too-few-public-methods
    ''' Set up a template  '''
    def __init__(self, filename=None):
        self.envdir = envdir = None
        self.template = None

        if not filename:
            return

        if os.path.exists(filename):
            envdir = os.path.dirname(filename)
        else:
            logging.debug('os.path.exists failed for %s', filename)
            return

        self.filename = filename

        if not self.envdir or self.envdir != envdir:
            self.envdir = envdir
            self.env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(self.envdir),
                autoescape=jinja2.select_autoescape(['htm', 'html', 'xml']))

        basename = os.path.basename(filename)

        self.template = self.env.get_template(basename)

    def generate(self, metadatadict=None):
        ''' get the generated template '''
        logging.debug('generating data for %s', self.filename)
        if self.template:
            return self.template.render(metadatadict)
        return "No template found; check your settings"


def getmoremetadata(metadata=None):
    ''' given a chunk of metadata, try to fill in more '''

    logging.debug('getmoremetadata called')

    if not metadata or 'filename' not in metadata:
        return metadata

    # tinytag is pure python and supports a wide variety of
    # formats.  because of that, it doesn't necessarily
    # have all the bells and whistles of other, more specific
    # libraries.  But this is good enough for now.

    if not os.path.isfile(metadata['filename']):
        return metadata

    logging.debug('getmoremetadata calling TinyTag for %s',
                  metadata['filename'])

    tag = tinytag.TinyTag.get(metadata['filename'], image=True)

    for key in [
            'album', 'albumartist', 'artist', 'bitrate', 'bpm', 'composer',
            'disc', 'disc_total', 'genre', 'key', 'publisher', 'lang', 'title',
            'track', 'track_total', 'year'
    ]:
        if key not in metadata and hasattr(tag, key) and getattr(tag, key):
            metadata[key] = getattr(tag, key)

    if 'coverimageraw' not in metadata:
        metadata['coverimageraw'] = tag.get_image()

    # always convert to png

    if metadata['coverimageraw']:
        coverimage = metadata['coverimageraw']
        imgbuffer = io.BytesIO(coverimage)
        image = PIL.Image.open(imgbuffer)
        image.save(imgbuffer, format='png')
        metadata['coverimageraw'] = imgbuffer.getvalue()
        metadata['coverimagetype'] = 'png'
        metadata['coverurl'] = 'cover.png'
    return metadata


def writetxttrack(filename=None,
                  templatehandler=None,
                  metadata=None,
                  clear=False):
    ''' write new track info '''

    logging.debug('writetxttrack called for %s', filename)
    if templatehandler:
        txttemplate = templatehandler.generate(metadata)
    elif clear:
        txttemplate = ''
    else:
        txttemplate = '{{ artist }} - {{ title }}'

    logging.debug('writetxttrack: starting write')
    # need to -specifically- open as utf-8 otherwise
    # pyinstaller built app crashes
    with open(filename, "w", encoding='utf-8') as textfh:
        #print("writing...")
        textfh.write(txttemplate)
    logging.debug('writetxttrack: finished write')


def main():
    ''' entry point as a standalone app'''
    metadata = {'filename': sys.argv[1]}
    metadata = getmoremetadata(metadata)
    print(metadata)


if __name__ == "__main__":
    main()
