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
import nowplaying.imagecache
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

    def pick_recognize(self, metadata):
        ''' do data lookup '''
        if not self.config.cparser.value('theaudiodb/enabled', type=bool):
            return metadata

        extradata = None

        if 'musicbrainzartistid' in metadata:
            extradata = self.artistdatafrommbid(
                metadata['musicbrainzartistid'])
        elif 'artist' in metadata:
            extradata = self.artistdatafromname(metadata['artist'])
        if not extradata:
            return metadata

        for artdata in extradata['artists']:
            if artdata['strArtist'] != metadata['artist']:
                continue
            if 'strBiographyEN' in artdata:
                metadata['artistbio'] = self._filter(artdata['strBiographyEN'])
            if 'strArtistThumb' in artdata:
                metadata['artistthumb'] = artdata['strArtistThumb']
            if 'strArtistLogo' in artdata:
                metadata['artistlogo'] = artdata['strArtistLogo']
            for num in ['', '2', '3', '4']:
                artstring = f'strArtistFanart{num}'
                if artdata.get(artstring):
                    metadata['artistfanarturls'].append(artdata[artstring])
        return metadata

    def recognize(self, metadata):
        ''' route and lookup '''
        metadata = self.pick_recognize(metadata)
        if not metadata:
            return None

        if 'artistthumb' in metadata:
            cache = nowplaying.imagecache.ArtistThumbCache()
            if thumb := cache.image_fetch(
                metadata['artist'], metadata['artistthumb']
            ):
                metadata['artistthumbraw'] = thumb

        if 'artistlogo' in metadata:
            cache = nowplaying.imagecache.ArtistLogoCache()
            if logo := cache.image_fetch(
                metadata['artist'], metadata['artistlogo']
            ):
                metadata['artistlogoraw'] = logo
        return metadata

    def artistdatafrommbid(self, mbartistid):
        ''' get artist data from mbid '''
        data = self._fetch(f'artist-mb.php?i={mbartistid}')
        if not data or not data.get('artists'):
            return None
        return data

    def artistdatafromname(self, artist):
        ''' get artist data from name '''
        if not artist:
            return None
        urlart = requests.utils.requote_uri(artist)
        data = self._fetch(f'search.php?s={urlart}')
        if not data or not data.get('artists'):
            return None
        return data

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this recognition system '''
        return [
            'artistbio', 'artistlogoraw', 'artistthumbraw', 'artistfanarturls'
        ]

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
