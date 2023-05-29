#!/usr/bin/env python3
''' handler to read the metadata from various file formats '''

from html.parser import HTMLParser

import base64
import copy
import io
import logging
import os
import re
import time
import typing as t
import traceback

import jinja2
import normality
import PIL.Image
import pillow_avif  # pylint: disable=unused-import # pyright: ignore[unusedImport]

STRIPWORDLIST = ['clean', 'dirty', 'explicit', 'official music video']
STRIPRELIST = [
    re.compile(r' \((?i:{0})\)'.format('|'.join(STRIPWORDLIST))),  # pylint: disable=consider-using-f-string
    re.compile(r' - (?i:{0}$)'.format('|'.join(STRIPWORDLIST))),  # pylint: disable=consider-using-f-string
    re.compile(r' \[(?i:{0})\]'.format('|'.join(STRIPWORDLIST))),  # pylint: disable=consider-using-f-string
]

TRANSPARENT_PNG = ''.join([
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC', '1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAA',
    'ASUVORK5CYII='
])

TRANSPARENT_PNG_BIN = base64.b64decode(TRANSPARENT_PNG)


class HTMLFilter(HTMLParser):
    ''' simple class to strip HTML '''

    def __init__(self, convert_charrefs: bool = True):
        super().__init__(convert_charrefs=convert_charrefs)
        self.text = ""

    def handle_data(self, data: str):
        ''' handle data '''
        self.text += data

    @staticmethod
    def error(message: str):
        ''' handle error messages '''
        logging.debug('HTMLFilter: %s', message)


class TemplateHandler():  # pylint: disable=too-few-public-methods
    ''' Set up a template  '''

    def __init__(self, filename: str = ''):
        self.envdir: str = ''
        envdir: str = ''
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

        self.template: jinja2.Template = self.env.get_template(basename)

    @staticmethod
    def _finalize(variable: object) -> t.Any:
        ''' helper routine to avoid NoneType exceptions '''
        if variable:
            return variable
        return ''

    def setup_jinja2(
        self, directory: t.Union[str, os.PathLike, t.Sequence[t.Union[str, os.PathLike]]]
    ) -> jinja2.Environment:
        ''' set up the environment '''
        return jinja2.Environment(loader=jinja2.FileSystemLoader(directory),
                                  finalize=self._finalize,
                                  autoescape=jinja2.select_autoescape(['htm', 'html', 'xml']))

    def generate(self, metadatadict: dict[str, t.Any]) -> str:
        ''' get the generated template '''
        logging.debug('generating data for %s', self.filename)

        rendertext = 'Template has syntax errors'
        try:
            if not self.filename or not os.path.exists(self.filename) or not self.template:
                return " No template found; check Now Playing settings."
            rendertext = self.template.render(**metadatadict)
        except:  #pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
        return rendertext


def image2png(rawdata: bytes) -> bytes:
    ''' convert an image to png '''

    if not rawdata:
        return b''

    if rawdata.startswith(b'\211PNG\r\n\032\n'):
        logging.debug('already PNG, skipping convert')
        return rawdata

    try:
        imgbuffer = io.BytesIO(rawdata)
        logging.getLogger('PIL.TiffImagePlugin').setLevel(logging.CRITICAL + 1)
        logging.getLogger('PIL.PngImagePlugin').setLevel(logging.CRITICAL + 1)
        image = PIL.Image.open(imgbuffer)
        imgbuffer = io.BytesIO(rawdata)
        if image.format != 'PNG':
            image.convert(mode='RGB').save(imgbuffer, format='PNG')
    except Exception as error:  # pylint: disable=broad-except
        logging.debug(error)
        return b''
    logging.debug("Leaving image2png")
    return imgbuffer.getvalue()


def image2avif(rawdata: bytes) -> bytes:
    ''' convert an image to png '''

    if not rawdata:
        return b''

    if rawdata.startswith(b'\x00\x00\x00 ftypavif'):
        logging.debug('already AVIF, skipping convert')
        return rawdata

    try:
        imgbuffer = io.BytesIO(rawdata)
        logging.getLogger('PIL.TiffImagePlugin').setLevel(logging.CRITICAL + 1)
        logging.getLogger('PIL.PngImagePlugin').setLevel(logging.CRITICAL + 1)
        image = PIL.Image.open(imgbuffer)
        imgbuffer = io.BytesIO(rawdata)
        if image.format != 'AVIF':
            image.convert(mode='RGB').save(imgbuffer, format='AVIF')
    except Exception as error:  # pylint: disable=broad-except
        logging.debug(error)
        return b''
    logging.debug("Leaving image2png")
    return imgbuffer.getvalue()


def songpathsubst(config, filename: str) -> str:
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
    else:
        newname = filename

    if songin := config.cparser.value('quirks/filesubstin'):
        songout = config.cparser.value('quirks/filesubstout')
        if not songout:
            songout = ''

        try:
            newname = filename.replace(songin, songout)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('Unable to do path replacement (%s -> %s on %s): %s', songin, songout,
                          filename, error)
            return filename

    logging.debug('filename substitution: %s -> %s', origfilename, newname)
    return newname


def normalize(crazystring: str) -> str:
    ''' take a string and genericize it '''
    if not crazystring:
        return ''
    if len(crazystring) < 4:
        return 'TEXT IS TOO SMALL IGNORE'
    if text := normality.normalize(crazystring):
        return text.replace(' ', '')
    return ''


def titlestripper_basic(title: str = '',
                        title_regex_list: t.Optional[list[re.Pattern]] = None) -> str:
    ''' Basic title removal '''
    if not title_regex_list or len(title_regex_list) == 0:
        title_regex_list = STRIPRELIST
    return titlestripper_advanced(title=title, title_regex_list=title_regex_list)


def titlestripper_advanced(title: str = '',
                           title_regex_list: t.Optional[list[re.Pattern]] = None) -> str:
    ''' Basic title removal '''
    if not title:
        return ''
    trackname = copy.deepcopy(title)
    if not title_regex_list or len(title_regex_list) == 0:
        return trackname
    for index in title_regex_list:
        trackname = index.sub('', trackname)
    if len(trackname) == 0:
        trackname = copy.deepcopy(title)
    return trackname


def humanize_time(seconds: t.Any) -> str:
    ''' convert seconds into hh:mm:ss '''

    try:
        convseconds = int(float(seconds))
    except (ValueError, TypeError):
        return ''

    if seconds > 3600:
        return time.strftime('%H:%M:%S', time.gmtime(convseconds))
    if seconds > 60:
        return time.strftime('%M:%S', time.gmtime(convseconds))
    return time.strftime('%S', time.gmtime(convseconds))
