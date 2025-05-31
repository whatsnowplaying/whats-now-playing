#!/usr/bin/env python3
''' start of support of fanarttv '''

import asyncio
import logging
import logging.config
import logging.handlers

import aiohttp

import nowplaying.apicache
import nowplaying.utils
from nowplaying.artistextras import ArtistExtrasPlugin


class Plugin(ArtistExtrasPlugin):
    ''' handler for fanart.tv '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.client = None
        self.version = config.version
        self.displayname = "fanart.tv"
        self.priority = 50

    async def _fetch_async(self, apikey, artistid):
        delay = self.calculate_delay()

        try:
            baseurl = f'http://webservice.fanart.tv/v3/music/{artistid}'
            logging.debug('fanarttv async: calling %s', baseurl)
            connector = nowplaying.utils.create_http_connector()
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(f'{baseurl}?api_key={apikey}',
                                       timeout=aiohttp.ClientTimeout(total=delay)) as response:
                    return await response.json()
        except asyncio.TimeoutError:
            logging.error('fantart.tv async timeout getting artistid %s', artistid)
            return None
        except Exception as error:  # pragma: no cover pylint: disable=broad-except
            logging.error('fanart.tv async: %s', error)
            return None

    async def _fetch_cached(self, apikey, artistid, artist_name):
        """Cached version of _fetch for better performance."""

        async def fetch_func():
            return await self._fetch_async(apikey, artistid)

        return await nowplaying.apicache.cached_fetch(
            provider='fanarttv',
            artist_name=artist_name,
            endpoint=f'music/{artistid}',  # Use the API endpoint path
            fetch_func=fetch_func,
            ttl_seconds=7 * 24 * 60 * 60  # 7 days for FanartTV data per CLAUDE.md
        )

    async def download_async(self, metadata=None, imagecache=None):
        ''' async download the extra data '''

        # Validate inputs
        if not self._validate_inputs(metadata, imagecache):
            return None

        apikey = self.config.cparser.value('fanarttv/apikey')
        # Process each MusicBrainz artist ID
        for artistid in metadata['musicbrainzartistid']:
            artist_data = await self._fetch_cached(apikey, artistid, metadata['artist'])
            if not artist_data or artist_data.get('status') == 'error':
                return None  # Match original behavior - fail on first error
            self._process_artist_images(artist_data, metadata, imagecache)
            break  # Success with first valid artist, no need to continue

        return metadata

    def _validate_inputs(self, metadata, imagecache):
        """Validate required inputs for fanart download."""
        apikey = self.config.cparser.value('fanarttv/apikey')
        if not apikey or not self.config.cparser.value('fanarttv/enabled', type=bool):
            return False

        if not metadata or not metadata.get('artist'):
            logging.debug('skipping: no artist')
            return False

        if not imagecache:
            logging.debug('imagecache is dead?')
            return False

        if not metadata.get('musicbrainzartistid'):
            return False

        logging.debug('got musicbrainzartistid: %s', metadata['musicbrainzartistid'])
        return True

    def _process_artist_images(self, artist_data, metadata, imagecache):
        """Process and queue artist images from FanartTV data."""
        identifier = metadata['imagecacheartist']
        # Process banners
        if (artist_data.get('musicbanner') and
            self.config.cparser.value('fanarttv/banners', type=bool)):
            self._queue_images(artist_data['musicbanner'], identifier, 'artistbanner', imagecache)

        # Process logos (prefer HD, fallback to regular)
        if self.config.cparser.value('fanarttv/logos', type=bool):
            logo_data = artist_data.get('hdmusiclogo') or artist_data.get('musiclogo')
            if logo_data:
                self._queue_images(logo_data, identifier, 'artistlogo', imagecache)

        # Process thumbnails
        if (artist_data.get('artistthumb') and
            self.config.cparser.value('fanarttv/thumbnails', type=bool)):
            self._queue_images(artist_data['artistthumb'], identifier, 'artistthumbnail',
                               imagecache)

        # Process fanart backgrounds
        if (self.config.cparser.value('fanarttv/fanart', type=bool) and
            artist_data.get('artistbackground')):
            self._process_fanart_backgrounds(artist_data['artistbackground'], metadata,
                                              identifier, imagecache)

    def _queue_images(self, image_list, identifier, image_type, imagecache):
        """Queue images sorted by popularity (likes)."""
        sorted_images = sorted(image_list, key=lambda x: x.get('likes', 0), reverse=True)
        urls = [img['url'] for img in sorted_images]
        imagecache.fill_queue(config=self.config,
                              identifier=identifier,
                              imagetype=image_type,
                              srclocationlist=urls)

    def _process_fanart_backgrounds(self, backgrounds, metadata, identifier, imagecache):
        """Process fanart backgrounds and collect URLs."""
        if not metadata.get('artistfanarturls'):
            metadata['artistfanarturls'] = []
        # Queue first image for display
        if backgrounds:
            imagecache.fill_queue(config=self.config,
                                  identifier=identifier,
                                  imagetype='artistfanart',
                                  srclocationlist=[backgrounds[0]['url']])
            # Collect all URLs for reference
            for background in backgrounds:
                metadata['artistfanarturls'].append(background['url'])

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this plug-in '''
        return [
            'artistbannerraw', 'artistlogoraw', 'artistthumbnailraw', 'fanarttv-artistfanarturls'
        ]

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
