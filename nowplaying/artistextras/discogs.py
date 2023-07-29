#!/usr/bin/env python3
''' start of support of discogs '''

import logging
import socket

import requests.exceptions
import urllib3.exceptions
import nowplaying.vendor.discogs_client
from nowplaying.vendor.discogs_client import models

from nowplaying.artistextras import ArtistExtrasPlugin
import nowplaying.utils


class Plugin(ArtistExtrasPlugin):
    ''' handler for discogs '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Discogs"
        self.client = None
        self.addmeta = {}

    def _get_apikey(self):
        apikey = self.config.cparser.value('discogs/apikey')
        if not apikey or not self.config.cparser.value('discogs/enabled', type=bool):
            return None
        return apikey

    def _setup_client(self):
        ''' setup the discogs client '''
        if apikey := self._get_apikey():
            delay = self.calculate_delay()
            self.client = nowplaying.vendor.discogs_client.Client(
                f'whatsnowplaying/{self.config.version}', user_token=apikey)
            self.client.set_timeout(connect=delay, read=delay)
            return True
        logging.error('Discogs API key is either wrong or missing.')
        return False

    def _process_metadata(self, artistname, artist, imagecache):
        ''' update metadata based upon an artist record '''
        if artist.images and imagecache:
            self.addmeta['artistfanarturls'] = []
            for record in artist.images:
                if record['type'] == 'primary' and record.get(
                        'uri150') and self.config.cparser.value('discogs/thumbnails', type=bool):
                    imagecache.fill_queue(config=self.config,
                                          artist=artistname,
                                          imagetype='artistthumbnail',
                                          urllist=[record['uri150']])

                if record['type'] == 'secondary' and record.get(
                        'uri') and self.config.cparser.value('discogs/fanart', type=bool):
                    self.addmeta['artistfanarturls'].append(record['uri'])

        if self.config.cparser.value('discogs/bio', type=bool):
            self.addmeta['artistlongbio'] = artist.profile_plaintext

        if self.config.cparser.value('discogs/websites', type=bool):
            self.addmeta['artistwebsites'] = artist.urls

    def _find_discogs_website(self, metadata, imagecache):
        ''' use websites listing to find discogs entries '''
        if not self.client and not self._setup_client():
            return False

        if not self.client or not metadata.get('artistwebsites'):
            return False

        artistnum = 0
        artist = None
        discogs_websites = [url for url in metadata['artistwebsites'] if 'discogs' in url]
        if len(discogs_websites) == 1:
            artistnum = discogs_websites[0].split('/')[-1]
            artist = self.client.artist(artistnum)
            artistname = str(artist.name)
            logging.debug('Found a singular discogs artist URL using %s instead of %s', artistname,
                          metadata['artist'])
        elif len(discogs_websites) > 1:
            for website in discogs_websites:
                artistnum = website.split('/')[-1]
                artist = self.client.artist(artistnum)
                webartistname = str(artist.name)
                if nowplaying.utils.normalize(webartistname) == nowplaying.utils.normalize(
                        metadata['artist']):
                    logging.debug(
                        'Found near exact match discogs artist URL %s using %s instead of %s',
                        website, webartistname, metadata['artist'])
                    artistname = webartistname
                    break
                artist = None
        if artist:
            self._process_metadata(metadata['imagecacheartist'], artist, imagecache)
            return True

        return False

    def _find_discogs_artist_releaselist(self, metadata):
        ''' given metadata, find the releases for an artist '''
        if not self.client and not self._setup_client():
            return None

        if not self.client:
            return None

        artistname = metadata['artist']
        try:
            logging.debug('Fetching %s - %s', artistname, metadata['album'])
            resultlist = self.client.search(metadata['album'], artist=artistname,
                                            type='title').page(1)
        except (
                requests.exceptions.ReadTimeout,  # pragma: no cover
                urllib3.exceptions.ReadTimeoutError,
                socket.timeout,
                TimeoutError):
            logging.error('discogs releaselist timeout error')
            return None
        except Exception as error:  # pragma: no cover pylint: disable=broad-except
            logging.error('discogs hit %s', error)
            return None

        return next(
            (result.artists[0] for result in resultlist if isinstance(result, models.Release)),
            None,
        )

    def download(self, metadata=None, imagecache=None):  # pylint: disable=too-many-branches, too-many-return-statements
        ''' download content '''

        if not self.config.cparser.value('discogs/enabled', type=bool):
            return None

        # discogs basically works by search for a combination of
        # artist and album so we need both
        if not metadata or not metadata.get('artist') or not metadata.get('album'):
            logging.debug('artist or album is empty, skipping')
            return None

        if not self.client and not self._setup_client():
            logging.error('No discogs apikey or client setup failed.')
            return None

        if not self.client:
            return None

        self.addmeta = {}

        if self._find_discogs_website(metadata, imagecache):
            logging.debug('used discogs website')
            return self.addmeta

        oldartist = metadata['artist']
        artistresultlist = None
        for variation in nowplaying.utils.artist_name_variations(metadata['artist']):
            metadata['artist'] = variation
            artistresultlist = self._find_discogs_artist_releaselist(metadata)
            if artistresultlist:
                break

        metadata['artist'] = oldartist

        if not artistresultlist:
            logging.debug('discogs did not find it')
            return None

        self._process_metadata(metadata['imagecacheartist'], artistresultlist, imagecache)
        return self.addmeta

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this plug-in '''
        return ['artistlongbio', 'artistthumbnailraw', 'discogs-artistfanarturls', 'artistwebsites']

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        if self.config.cparser.value('discogs/enabled', type=bool):
            qwidget.discogs_checkbox.setChecked(True)
        else:
            qwidget.discogs_checkbox.setChecked(False)
        qwidget.apikey_lineedit.setText(self.config.cparser.value('discogs/apikey'))

        for field in ['bio', 'fanart', 'thumbnails', 'websites']:
            func = getattr(qwidget, f'{field}_checkbox')
            func.setChecked(self.config.cparser.value(f'discogs/{field}', type=bool))

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

        self.config.cparser.setValue('discogs/enabled', qwidget.discogs_checkbox.isChecked())
        self.config.cparser.setValue('discogs/apikey', qwidget.apikey_lineedit.text())

        for field in ['bio', 'fanart', 'thumbnails', 'websites']:
            func = getattr(qwidget, f'{field}_checkbox')
            self.config.cparser.setValue(f'discogs/{field}', func.isChecked())

    def defaults(self, qsettings):
        for field in ['bio', 'fanart', 'thumbnails']:
            qsettings.setValue(f'discogs/{field}', False)

        qsettings.setValue('discogs/enabled', False)
        qsettings.setValue('discogs/apikey', '')
