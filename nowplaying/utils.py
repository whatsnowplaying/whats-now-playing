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

import imghdr
import jinja2
import tinytag


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
    # libraries.  But this is good enough for us.

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
        coverimage = tag.get_image()

        if coverimage:
            metadata['coverimageraw'] = coverimage
            iostream = io.BytesIO(metadata['coverimageraw'])
            headertype = imghdr.what(iostream)
            if headertype == 'jpeg':
                headertype = 'jpg'
            metadata['coverimagetype'] = headertype
            if 'deck' in metadata:
                deck = metadata['deck']
                metadata['coverurl'] = f'cover{deck}.{headertype}'
            else:
                metadata['coverurl'] = f'cover.{headertype}'
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


def update_javascript(serverdir='/tmp', templatehandler=None, metadata=None):
    ''' update the image with the new info '''

    logging.debug('update_javascript: called')
    if not serverdir:
        logging.debug('update_javascript: no serverdir')
        return

    if not templatehandler:
        logging.debug('update_javascript: no templatehandler')
        return

    if not metadata:
        logging.debug('update_javascript: incomplete metadata')
        return

    logging.debug('update_javascript:using dir %s', serverdir)

    indexhtm = os.path.join(serverdir, "index.htm")

    logging.debug('update_javascript:generating template')
    titlecardhtml = templatehandler.generate(metadata)

    logging.debug('update_javascript: writing index file')
    # need to -specifically- open as utf-8 otherwise
    # pyinstaller built app crashes
    with open(indexhtm, "w", encoding='utf-8') as indexfh:
        indexfh.write(titlecardhtml)

    if 'coverimageraw' in metadata:
        logging.debug('update_javascript: writing cover image')
        extension = metadata['coverimagetype']  # probably png or jpg
        coverfilename = f'cover.{extension}'
        with open(coverfilename, "wb") as coverfh:
            coverfh.write(metadata['coverimageraw'])
        if 'deck' in metadata:
            deck = metadata['deck']
            coverfilename = f'cover{deck}.{extension}'
            with open(coverfilename, "wb") as coverfh:
                coverfh.write(metadata['coverimageraw'])
    logging.debug('update_javascript: done')


def main():
    ''' entry point as a standalone app'''
    metadata = {'filename': sys.argv[1]}
    metadata = getmoremetadata(metadata)
    print(metadata)


if __name__ == "__main__":
    main()
