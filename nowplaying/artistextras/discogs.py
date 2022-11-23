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

import nowplaying.config
from nowplaying.artistextras import ArtistExtrasPlugin
import nowplaying.version


class Plugin(ArtistExtrasPlugin):
    ''' handler for discogs '''

    def __init__(self, config=None, qsettings=None):
        self.client = None
        self.version = nowplaying.version.get_versions()['version']
        self.there = re.compile('(?i)^the ')
        super().__init__(config=config, qsettings=qsettings)

    def _find_discogs_releaselist(self, metadata):
        try:
            logging.debug('Fetching %s - %s', metadata['artist'],
                          metadata['album'])
            resultlist = self.client.search(metadata['album'],
                                            artist=metadata['artist'],
                                            type='title').page(1)
        except (requests.exceptions.ReadTimeout,
                urllib3.exceptions.ReadTimeoutError, socket.timeout):
            logging.error('discogs releaselist timeout error')
            return None
        except Exception as error:  # pylint: disable=broad-except
            logging.error('discogs hit %s', error)
            return None

        artistresultlist = next(
            (result.artists[0] for result in resultlist if isinstance(
                result, nowplaying.vendor.discogs_client.models.Release)),
            None,
        )

        return artistresultlist

    def download(self, metadata=None, imagecache=None):  # pylint: disable=too-many-branches, too-many-return-statements
        ''' download content '''

        apikey = self.config.cparser.value('discogs/apikey')
        oldartist = None

        if not apikey or not self.config.cparser.value('discogs/enabled',
                                                       type=bool):
            return None

        # discogs basically works by search for a combination of
        # artist and album so we need both
        if not metadata.get('artist') or not metadata.get('album'):
            logging.debug('artist or album is empty, skipping')
            return None

        if not self.client:
            self.client = nowplaying.vendor.discogs_client.Client(
                f'whatsnowplaying/{self.version}', user_token=apikey)
            self.client.set_timeout(connect=3, read=2)

        artistresultlist = self._find_discogs_releaselist(metadata)

        if not artistresultlist and self.there.match(metadata['artist']):
            logging.debug('Trying without a leading \'The\'')
            oldartist = metadata['artist']
            metadata['artist'] = self.there.sub('', metadata['artist'])
            artistresultlist = self._find_discogs_releaselist(metadata)

        if not artistresultlist:
            if oldartist:
                metadata['artist'] = oldartist
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

        for record in artistresultlist.images:
            if record['type'] == 'primary' and record.get(
                    'uri150') and self.config.cparser.value(
                        'discogs/thumbnails', type=bool):
                imagecache.fill_queue(config=self.config,
                                      artist=metadata['artist'],
                                      imagetype='artistthumb',
                                      urllist=[record['uri150']])

            if record['type'] == 'secondary' and record.get(
                    'uri') and self.config.cparser.value(
                        'discogs/fanart', type=bool
                    ) and record['uri'] not in metadata['artistfanarturls']:
                metadata['artistfanarturls'].append(record['uri'])

        return metadata

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this plug-in '''
        return [
            'artistlongbio', 'artistthumbraw', 'discogs-artistfanarturls',
            'artistwebsites'
        ]

    def connect_settingsui(self, qwidget):
        ''' pass '''

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        if self.config.cparser.value('discogs/enabled', type=bool):
            qwidget.discogs_checkbox.setChecked(True)
        else:
            qwidget.discogs_checkbox.setChecked(False)
        qwidget.apikey_lineedit.setText(
            self.config.cparser.value('discogs/apikey'))

        for field in ['bio', 'fanart', 'thumbnails', 'websites']:
            func = getattr(qwidget, f'{field}_checkbox')
            func.setChecked(
                self.config.cparser.value(f'discogs/{field}', type=bool))

    def verify_settingsui(self, qwidget):
        ''' pass '''

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

        self.config.cparser.setValue('discogs/enabled',
                                     qwidget.discogs_checkbox.isChecked())
        self.config.cparser.setValue('discogs/apikey',
                                     qwidget.apikey_lineedit.text())

        for field in ['bio', 'fanart', 'thumbnails', 'websites']:
            func = getattr(qwidget, f'{field}_checkbox')
            self.config.cparser.setValue(f'discogs/{field}', func.isChecked())

    def defaults(self, qsettings):
        for field in ['bio', 'fanart', 'thumbnails']:
            qsettings.setValue(f'discogs/{field}', False)

        qsettings.setValue('discogs/enabled', False)
        qsettings.setValue('discogs/apikey', '')
