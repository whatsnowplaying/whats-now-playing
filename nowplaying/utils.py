#!/usr/bin/env python3
''' handler to read the metadata from various file formats '''

from html.parser import HTMLParser

import importlib
import io
import logging
import pkgutil
import os

import jinja2
import normality
import PIL.Image

import nowplaying.metadata


class HTMLFilter(HTMLParser):
    ''' simple class to strip HTML '''
    text = ""

    def handle_data(self, data):
        self.text += data

    def error(self, message):  # pylint: disable=no-self-use
        ''' handle error messages '''
        logging.debug('HTMLFilter: %s', message)


class TemplateHandler():  # pylint: disable=too-few-public-methods
    ''' Set up a template  '''

    def __init__(self, filename=None):
        self.envdir = envdir = None
        self.template = None
        self.filename = filename

        if not self.filename:
            return

        if os.path.exists(self.filename):
            envdir = os.path.dirname(self.filename)
        else:
            logging.error('%s does not exist!', self.filename)
            return

        if not self.envdir or self.envdir != envdir:
            self.envdir = envdir
            self.env = self.setup_jinja2(self.envdir)

        basename = os.path.basename(filename)

        self.template = self.env.get_template(basename)

    def _finalize(self, variable):  # pylint: disable=no-self-use
        ''' helper routine to avoid NoneType exceptions '''
        if variable:
            return variable
        return ''

    def setup_jinja2(self, directory):
        ''' set up the environment '''
        return jinja2.Environment(loader=jinja2.FileSystemLoader(directory),
                                  finalize=self._finalize,
                                  autoescape=jinja2.select_autoescape(
                                      ['htm', 'html', 'xml']))

    def generate(self, metadatadict=None):
        ''' get the generated template '''
        logging.debug('generating data for %s', self.filename)

        if not self.filename or not os.path.exists(
                self.filename) or not self.template:
            return " No template found; check Now Playing settings."
        return self.template.render(**metadatadict)


def getmoremetadata(metadata=None, imagecache=None):
    ''' given a chunk of metadata, try to fill in more '''

    logging.debug('getmoremetadata called')

    if not metadata or 'filename' not in metadata:
        return metadata

    if not os.path.isfile(metadata['filename']):
        return metadata

    logging.debug('getmoremetadata calling metadata processor for %s',
                  metadata['filename'])
    try:
        myclass = nowplaying.metadata.MetadataProcessors(metadata=metadata,
                                                         imagecache=imagecache)
        metadata = myclass.metadata
    except OSError as error:  # pragma: no cover
        logging.error('MetadataProcessor failed for %s with %s',
                      metadata['filename'], error)

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
        textfh.write(txttemplate)
    logging.debug('writetxttrack: finished write')


def import_plugins(namespace):
    ''' import plugins and return an object
        with all of them '''

    def iter_ns(ns_pkg):
        ''' iterate over a package and return children.
            used to monkey patch in plugins
        '''
        prefix = f'{ns_pkg.__name__}.'
        for pkg in pkgutil.iter_modules(ns_pkg.__path__, prefix):
            if 'test' not in pkg[1]:
                yield pkg[1]

        # special handling when the package is bundled with PyInstaller
        # See https://github.com/pyinstaller/pyinstaller/issues/1905#issuecomment-445787510
        toc = set()
        for importer in pkgutil.iter_importers(
                ns_pkg.__name__.partition(".")[0]):  # pragma: no cover
            if hasattr(importer, 'toc'):
                toc |= importer.toc
        for name in toc:  # pragma: no cover
            if name.startswith(prefix):
                yield name

    plugins = {
        name: importlib.import_module(name)
        for name in iter_ns(namespace)
    }
    return plugins


def image2png(rawdata):
    ''' convert an image to png '''

    if not rawdata:
        return None

    if rawdata.startswith(b'\211PNG\r\n\032\n'):
        logging.debug('already PNG, skipping convert')
        return rawdata

    try:
        origimage = rawdata
        imgbuffer = io.BytesIO(origimage)
        logging.getLogger('PIL.TiffImagePlugin').setLevel(logging.CRITICAL + 1)
        logging.getLogger('PIL.PngImagePlugin').setLevel(logging.CRITICAL + 1)
        image = PIL.Image.open(imgbuffer)
        if image.format != 'PNG':
            image.convert(mode='RGB').save(imgbuffer, format='png')
    except Exception as error:  #pylint: disable=broad-except
        logging.debug(error)
        return None
    logging.debug("Leaving image2png")
    return imgbuffer.getvalue()


def songpathsubst(config, filename):
    ''' if needed, change the pathing of a file '''

    origfilename = filename

    if not config.cparser.value('quirks/filesubst', type=bool):
        return filename

    slashmode = config.cparser.value('quirks/slashmode')

    if slashmode == 'toforward':
        newname = filename.replace('\\', '/')
        filename = newname
    elif slashmode == 'toback':
        newname = filename.replace('/', '\\')
        filename = newname

    if songin := config.cparser.value('quirks/filesubstin'):
        songout = config.cparser.value('quirks/filesubstout')
        if not songout:
            songout = ''

        try:
            newname = filename.replace(songin, songout)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('Unable to do path replacement (%s -> %s on %s): %s',
                          songin, songout, filename, error)
            return filename

    logging.debug('filename substitution: %s -> %s', origfilename, newname)
    return newname


def normalize(crazystring):
    ''' take a string and genericize it '''
    if not crazystring:
        return None
    if len(crazystring) < 4:
        return 'TEXT IS TOO SMALL IGNORE'
    return normality.normalize(crazystring).replace(' ', '')
