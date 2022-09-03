#!/usr/bin/env python3
''' start of support of theaudiodb '''

import logging
import logging.config
import logging.handlers

import requests
import requests.utils

import nowplaying.bootstrap
import nowplaying.config
from nowplaying.artistextras import ArtistExtrasPlugin
import nowplaying.version
import nowplaying.utils


class Plugin(ArtistExtrasPlugin):
    ''' handler for TheAudioDB '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.htmlfilter = nowplaying.utils.HTMLFilter()
        self.fnstr = None

    def _filter(self, text):
        self.htmlfilter.feed(text)
        return self.htmlfilter.text

    def _fetch(self, apikey, api):  # pylint: disable=no-self-use
        try:
            logging.debug('Fetching %s', api)
            page = requests.get(
                f'https://theaudiodb.com/api/v1/json/{apikey}/{api}',
                timeout=5)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('TheAudioDB hit %s', error)
            return None
        return page.json()

    def _check_artist(self, artdata):
        ''' is this actually the artist we are looking for? '''
        found = False
        for fieldname in ['strArtist', 'strArtistAlternate']:
            if artdata.get(fieldname) and nowplaying.utils.normalize(
                    artdata[fieldname]) in self.fnstr:
                logging.debug('theaudiodb Trusting %s: %s', fieldname,
                              artdata[fieldname])
                found = True
            else:
                logging.debug(
                    'theaudiodb not Trusting %s vs. %s', self.fnstr,
                    nowplaying.utils.normalize(artdata.get(fieldname)))
        return found

    def _handle_extradata(self, extradata, metadata, imagecache):    # pylint: disable=too-many-branches
        ''' deal with the various bits of data '''
        lang1 = self.config.cparser.value('theaudiodb/bio_iso')

        bio = ''

        for artdata in extradata:

            if not self._check_artist(artdata):
                continue

            if not metadata.get('artistlongbio') and self.config.cparser.value(
                    'theaudiodb/bio', type=bool):
                if f'strBiography{lang1}' in artdata:
                    bio += self._filter(artdata[f'strBiography{lang1}'])
                elif self.config.cparser.value(
                        'theaudiodb/bio_iso_en_fallback',
                        type=bool) and 'strBiographyEN' in artdata:
                    bio += self._filter(artdata['strBiographyEN'])

            if self.config.cparser.value(
                'theaudiodb/websites', type=bool
            ) and artdata.get('strWebsite'):
                webstr = 'https://' + artdata['strWebsite']
                if not metadata.get('artistwebsites'):
                    metadata['artistwebsites'] = []
                metadata['artistwebsites'].append(webstr)

            if imagecache:
                if not metadata.get('artistbannerraw') and artdata.get(
                        'strArtistBanner') and self.config.cparser.value(
                            'theaudiodb/banners', type=bool):
                    imagecache.fill_queue(config=self.config,
                                          artist=metadata['artist'],
                                          imagetype='artistbanner',
                                          urllist=[artdata['strArtistBanner']])

                if not metadata.get('artistlogoraw') and artdata.get(
                        'strArtistLogo') and self.config.cparser.value(
                            'theaudiodb/logos', type=bool):
                    imagecache.fill_queue(config=self.config,
                                          artist=metadata['artist'],
                                          imagetype='artistlogo',
                                          urllist=[artdata['strArtistLogo']])

                if not metadata.get('artistthumbraw') and artdata.get(
                        'strArtistThumb') and self.config.cparser.value(
                            'theaudiodb/thumbnails', type=bool):
                    imagecache.fill_queue(config=self.config,
                                          artist=metadata['artist'],
                                          imagetype='artistthumb',
                                          urllist=[artdata['strArtistThumb']])

                if self.config.cparser.value('theaudiodb/fanart', type=bool):
                    for num in ['', '2', '3', '4']:
                        artstring = f'strArtistFanart{num}'
                        if artdata.get(artstring):
                            metadata['artistfanarturls'].append(
                                artdata[artstring])

        if bio:
            metadata['artistlongbio'] = bio

        return metadata

    def download(self, metadata=None, imagecache=None):  # pylint: disable=too-many-branches
        ''' do data lookup '''

        if not self.config.cparser.value('theaudiodb/enabled', type=bool):
            return None

        if not metadata.get('artist'):
            logging.debug('No artist; skipping')
            return None

        apikey = self.config.cparser.value('theaudiodb/apikey')
        if not apikey:
            logging.debug('No API key.')
            return None

        extradata = []
        self.fnstr = nowplaying.utils.normalize(metadata['artist'])

        if metadata.get('musicbrainzartistid'):
            logging.debug('got musicbrainzartistid: %s',
                          metadata['musicbrainzartistid'])
            for mbid in metadata['musicbrainzartistid']:
                if newdata := self.artistdatafrommbid(apikey, mbid):
                    extradata.extend(artist for artist in newdata['artists']
                                     if self._check_artist(artist))
        elif metadata.get('artist'):
            logging.debug('got artist')
            if artistdata := self.artistdatafromname(apikey,
                                                     metadata['artist']):
                extradata.extend(artist for artist in artistdata.get('artists')
                                 if self._check_artist(artist))
        if not extradata:
            return None

        return self._handle_extradata(extradata, metadata, imagecache)

    def artistdatafrommbid(self, apikey, mbartistid):
        ''' get artist data from mbid '''
        data = self._fetch(apikey, f'artist-mb.php?i={mbartistid}')
        if not data or not data.get('artists'):
            return None
        return data

    def artistdatafromname(self, apikey, artist):
        ''' get artist data from name '''
        if not artist:
            return None
        urlart = requests.utils.requote_uri(artist)
        data = self._fetch(apikey, f'search.php?s={urlart}')
        if not data or not data.get('artists'):
            return None
        return data

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this plug-in '''
        return [
            'artistbannerraw', 'artistlongbio', 'artistlogoraw',
            'artistthumbraw', 'theaudiodb-artistfanarturls'
        ]

    def connect_settingsui(self, qwidget):
        ''' pass '''

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        if self.config.cparser.value('theaudiodb/enabled', type=bool):
            qwidget.theaudiodb_checkbox.setChecked(True)
        else:
            qwidget.theaudiodb_checkbox.setChecked(False)
        qwidget.apikey_lineedit.setText(
            self.config.cparser.value('theaudiodb/apikey'))
        qwidget.bio_iso_lineedit.setText(
            self.config.cparser.value('theaudiodb/bio_iso'))

        for field in ['banners', 'bio', 'fanart', 'logos', 'thumbnails']:
            func = getattr(qwidget, f'{field}_checkbox')
            func.setChecked(
                self.config.cparser.value(f'theaudiodb/{field}', type=bool))

    def verify_settingsui(self, qwidget):
        ''' pass '''

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

        self.config.cparser.setValue('theaudiodb/enabled',
                                     qwidget.theaudiodb_checkbox.isChecked())
        self.config.cparser.setValue('theaudiodb/apikey',
                                     qwidget.apikey_lineedit.text())
        self.config.cparser.setValue('theaudiodb/bio_iso',
                                     qwidget.bio_iso_lineedit.text())
        self.config.cparser.setValue('theaudiodb/bio_iso_en_fallback',
                                     qwidget.bio_iso_en_checkbox.isChecked())

        for field in [
                'banners', 'bio', 'fanart', 'logos', 'thumbnails', 'websites'
        ]:
            func = getattr(qwidget, f'{field}_checkbox')
            self.config.cparser.setValue(f'theaudiodb/{field}',
                                         func.isChecked())

    def defaults(self, qsettings):
        for field in [
                'banners', 'bio', 'fanart', 'logos', 'thumbnails', 'websites'
        ]:
            qsettings.setValue(f'theaudiodb/{field}', False)

        qsettings.setValue('theaudiodb/enabled', False)
        qsettings.setValue('theaudiodb/apikey', '')
        qsettings.setValue('theaudiodb/bio_iso', 'EN')
        qsettings.setValue('theaudiodb/bio_iso_en_fallback', True)
