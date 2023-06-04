#!/usr/bin/env python3
''' start of support of discogs '''

import logging
import logging.config
import logging.handlers
import re
import socket

import requests.exceptions
import urllib3.exceptions
import nowplaying.vendor.discogs_client
from nowplaying.vendor.discogs_client import models

from nowplaying.artistextras import ArtistExtrasPlugin


class Plugin(ArtistExtrasPlugin):
    ''' handler for discogs '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Discogs"
        self.client = None
        self.version = config.version
        self.there = re.compile('(?i)^the ')

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
        return False

    def _find_discogs_artist_releaselist(self, metadata):

        if not self.client and not self._setup_client():
            return None

        if not self.client:
            return None

        try:
            logging.debug('Fetching %s - %s', metadata['artist'], metadata['album'])
            resultlist = self.client.search(metadata['album'],
                                            artist=metadata['artist'],
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

        oldartist = metadata['artist']
        artistresultlist = self._find_discogs_artist_releaselist(metadata)

        if not artistresultlist and self.there.match(metadata['artist']):
            logging.debug('Trying without a leading \'The\'')
            metadata['artist'] = self.there.sub('', metadata['artist'])
            artistresultlist = self._find_discogs_artist_releaselist(metadata)

        if not artistresultlist:
            logging.debug('discogs did not find it')
            return None

        if self.config.cparser.value('discogs/bio', type=bool):
            metadata['artistlongbio'] = artistresultlist.profile_plaintext

        if self.config.cparser.value('discogs/websites', type=bool):
            metadata['artistwebsites'] = artistresultlist.urls

        if not imagecache:
            return metadata

        if not artistresultlist.images:
            return metadata

        if not metadata.get('artistfanarturls'):
            metadata['artistfanarturls'] = []

        for record in artistresultlist.images:
            if record['type'] == 'primary' and record.get('uri150') and self.config.cparser.value(
                    'discogs/thumbnails', type=bool):
                imagecache.fill_queue(config=self.config,
                                      artist=oldartist,
                                      imagetype='artistthumb',
                                      urllist=[record['uri150']])

            if record['type'] == 'secondary' and record.get('uri') and self.config.cparser.value(
                    'discogs/fanart',
                    type=bool) and record['uri'] not in metadata['artistfanarturls']:
                metadata['artistfanarturls'].append(record['uri'])

        return metadata

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this plug-in '''
        return ['artistlongbio', 'artistthumbraw', 'discogs-artistfanarturls', 'artistwebsites']

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
