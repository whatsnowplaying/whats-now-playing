#!/usr/bin/env python3
''' start of support of theaudiodb '''

from html.parser import HTMLParser
import logging
import logging.config
import logging.handlers
import os

import requests
import requests.utils

import nowplaying.bootstrap
import nowplaying.config
from nowplaying.recognition import RecognitionPlugin


class HTMLFilter(HTMLParser):
    ''' simple class to strip HTML '''
    text = ""

    def handle_data(self, data):
        self.text += data

    def error(self, message):
        logging.debug('HTMLFilter: %s', message)


class Plugin(RecognitionPlugin):
    ''' handler for TheAudioDB '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.htmlfilter = HTMLFilter()

    def _filter(self, text):
        self.htmlfilter.feed(text)
        return self.htmlfilter.text

    def _fetch(self, api):
        apikey = self.config.cparser.value('theaudiodb/apikey')

        if not apikey:
            return None

        try:
            logging.debug('Fetching %s', api)
            page = requests.get(
                f'https://theaudiodb.com/api/v1/json/{apikey}/{api}',
                timeout=5)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('TheAudioDB hit %s', error)
            return None
        return page.json()

    def recognize(self, metadata):
        ''' do data lookup '''
        if not self.config.cparser.value('theaudiodb/enabled', type=bool):
            return None

        if 'musicbrainzartistid' in metadata:
            return self.artistdatafrommbid(metadata['musicbrainzartistid'])
        if 'artist' in metadata:
            return self.artistdatafromname(metadata['artist'])
        return None

    def artistdatafrommbid(self, mbartistid):
        ''' get artist data from mbid '''
        metadata = {}
        data = self._fetch(f'artist-mb.php?i={mbartistid}')
        if not data or 'artists' not in data or not data['artists']:
            return None

        artdata = data['artists'][0]
        if 'strBiographyEN' in artdata:
            metadata['artistbio'] = self._filter(artdata['strBiographyEN'])
        if 'strArtistThumb' in artdata:
            metadata['artistthumb'] = artdata['strArtistThumb']
        if 'strArtistLogo' in artdata:
            metadata['artistlogo'] = artdata['strArtistLogo']
        return metadata

    def artistdatafromname(self, artist):
        ''' get artist data from name '''
        metadata = {}
        if not artist:
            return None
        urlart = requests.utils.requote_uri(artist)
        data = self._fetch(f'search.php?s={urlart}')
        if not data or 'artists' not in data or not data['artists']:
            return None

        artdata = data['artists'][0]
        if 'strBiographyEN' in artdata:
            metadata['artistbio'] = self._filter(artdata['strBiographyEN'])
        if 'strArtistThumb' in artdata:
            metadata['artistthumb'] = artdata['strArtistThumb']
        if 'strArtistLogo' in artdata:
            metadata['artistlogo'] = artdata['strArtistLogo']
        return metadata

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this recognition system '''
        return ['artistbio', 'artistlogo', 'artistthumb']

    def connect_settingsui(self, qwidget):
        ''' pass '''

    def load_settingsui(self, qwidget):
        ''' pass '''

    def verify_settingsui(self, qwidget):
        ''' pass '''

    def save_settingsui(self, qwidget):
        ''' pass '''

    def defaults(self, qsettings):
        ''' pass '''


def main():
    ''' entry point as a standalone app'''

    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names()
    # need to make sure config is initialized with something
    config = nowplaying.config.ConfigFile(bundledir=bundledir)
    theaudiodb = Plugin(config=config)
    print(
        theaudiodb.artistdatafrommbid('45074d7c-5307-44a8-854f-ae072e1622ae'))
    print(theaudiodb.artistdatafromname('Cee Farrow'))


if __name__ == "__main__":
    main()
