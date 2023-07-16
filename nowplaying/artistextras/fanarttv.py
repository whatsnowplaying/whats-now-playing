#!/usr/bin/env python3
''' start of support of fanarttv '''

import logging
import logging.config
import logging.handlers
import socket

import requests
import requests.exceptions
import urllib3.exceptions

#import nowplaying.config
from nowplaying.artistextras import ArtistExtrasPlugin
#import nowplaying.utils


class Plugin(ArtistExtrasPlugin):
    ''' handler for fanart.tv '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.client = None
        self.version = config.version
        self.displayname = "fanart.tv"
        self.priority = 50

    def _fetch(self, apikey, artistid):
        artistrequest = None
        delay = self.calculate_delay()

        try:
            baseurl = f'http://webservice.fanart.tv/v3/music/{artistid}'
            logging.debug('fanarttv: calling %s', baseurl)
            artistrequest = requests.get(f'{baseurl}?api_key={apikey}', timeout=delay)
        except (
                requests.exceptions.ReadTimeout,  # pragma: no cover
                urllib3.exceptions.ReadTimeoutError,
                socket.timeout):
            logging.error('fantart.tv timeout getting artistid %s', artistid)
        except Exception as error:  # pragma: no cover pylint: disable=broad-except
            logging.error('fanart.tv: %s', error)

        return artistrequest

    def download(self, metadata=None, imagecache=None):  # pylint: disable=too-many-branches
        ''' download the extra data '''

        apikey = self.config.cparser.value('fanarttv/apikey')
        if not apikey or not self.config.cparser.value('fanarttv/enabled', type=bool):
            return None

        if not metadata or not metadata.get('artist'):
            logging.debug('skipping: no artist')
            return None

        if not imagecache:
            logging.debug('imagecache is dead?')
            return None

        if not metadata.get('musicbrainzartistid'):
            return None

        #fnstr = nowplaying.utils.normalize(metadata['artist'])
        logging.debug('got musicbrainzartistid: %s', metadata['musicbrainzartistid'])
        for artistid in metadata['musicbrainzartistid']:
            artistrequest = self._fetch(apikey, artistid)
            if not artistrequest:
                return None

            artist = artistrequest.json()

            # if artist.get('name') and nowplaying.utils.normalize(artist['name']) in fnstr:
            #     logging.debug("fanarttv Trusting : %s", artist['name'])
            # else:
            #     logging.debug("fanarttv Not trusting: %s vs %s", artist.get('name'), fnstr)
            #     continue

            if artist.get('musicbanner') and self.config.cparser.value('fanarttv/banners',
                                                                       type=bool):
                banner = sorted(artist['musicbanner'], key=lambda x: x['likes'], reverse=True)
                imagecache.fill_queue(config=self.config,
                                      artist=metadata['imagecacheartist'],
                                      imagetype='artistbanner',
                                      urllist=[x['url'] for x in banner])

            if self.config.cparser.value('fanarttv/logos', type=bool):
                logo = None
                if artist.get('hdmusiclogo'):
                    logo = sorted(artist['hdmusiclogo'], key=lambda x: x['likes'], reverse=True)
                elif artist.get('musiclogo'):
                    logo = sorted(artist['musiclogo'], key=lambda x: x['likes'], reverse=True)
                if logo:
                    imagecache.fill_queue(config=self.config,
                                          artist=metadata['imagecacheartist'],
                                          imagetype='artistlogo',
                                          urllist=[x['url'] for x in logo])

            if artist.get('artistthumb') and self.config.cparser.value('fanarttv/thumbnails',
                                                                       type=bool):
                thumbnail = sorted(artist['artistthumb'], key=lambda x: x['likes'], reverse=True)
                imagecache.fill_queue(config=self.config,
                                      artist=metadata['imagecacheartist'],
                                      imagetype='artistthumb',
                                      urllist=[x['url'] for x in thumbnail])

            if self.config.cparser.value('fanarttv/fanart',
                                         type=bool) and artist.get('artistbackground'):
                for image in artist['artistbackground']:
                    if not metadata.get('artistfanarturls'):
                        metadata['artistfanarturls'] = []
                    metadata['artistfanarturls'].append(image['url'])

        return metadata

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this plug-in '''
        return ['artistbannerraw', 'artistlogoraw', 'artistthumbraw', 'fanarttv-artistfanarturls']

    def connect_settingsui(self, qwidget, uihelp):
        ''' pass '''

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        if self.config.cparser.value('fanarttv/enabled', type=bool):
            qwidget.fanarttv_checkbox.setChecked(True)
        else:
            qwidget.fanarttv_checkbox.setChecked(False)
        qwidget.apikey_lineedit.setText(self.config.cparser.value('fanarttv/apikey'))

        for field in ['banners', 'logos', 'fanart', 'thumbnails']:
            func = getattr(qwidget, f'{field}_checkbox')
            func.setChecked(self.config.cparser.value(f'fanarttv/{field}', type=bool))

    def verify_settingsui(self, qwidget):
        ''' pass '''

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

        self.config.cparser.setValue('fanarttv/enabled', qwidget.fanarttv_checkbox.isChecked())
        self.config.cparser.setValue('fanarttv/apikey', qwidget.apikey_lineedit.text())

        for field in ['banners', 'logos', 'fanart', 'thumbnails']:
            func = getattr(qwidget, f'{field}_checkbox')
            self.config.cparser.setValue(f'fanarttv/{field}', func.isChecked())

    def defaults(self, qsettings):
        for field in ['banners', 'logos', 'fanart', 'thumbnails']:
            qsettings.setValue(f'fanarttv/{field}', False)

        qsettings.setValue('fanarttv/enabled', False)
        qsettings.setValue('fanarttv/apikey', '')
