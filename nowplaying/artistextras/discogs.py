#!/usr/bin/env python3
''' start of support of discogs '''

import asyncio
import logging

import nowplaying.apicache
import nowplaying.discogsclient
from nowplaying.discogsclient import Models as models

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

            # Use optimized client based on what features are enabled
            need_bio = self.config.cparser.value('discogs/bio', type=bool)
            need_images = (self.config.cparser.value('discogs/fanart', type=bool)
                           or self.config.cparser.value('discogs/thumbnails', type=bool))

            self.client = nowplaying.discogsclient.get_optimized_client_for_nowplaying(
                f'whatsnowplaying/{self.config.version}',
                user_token=apikey,
                need_bio=need_bio,
                need_images=need_images,
                timeout=delay)
            return True
        logging.error('Discogs API key is either wrong or missing.')
        return False

    async def _search_async_cached(self, album_title, artist_name, search_type='title'):
        """Cached version of discogs search_async."""

        async def fetch_func():
            result = await self.client.search_async(album_title, artist=artist_name,
                                                   search_type=search_type)
            # Convert to JSON-serializable format for caching
            if hasattr(result, 'results'):
                return {
                    'results': [
                        {
                            'type': 'release' if isinstance(r, models.Release) else 'unknown',
                            'data': r.data if hasattr(r, 'data') else r,
                            'artists': [a.data if hasattr(a, 'data') else a
                                       for a in getattr(r, 'artists', [])]
                        } for r in result.results
                    ]
                }
            return result

        cached_result = await nowplaying.apicache.cached_fetch(
            provider='discogs',
            artist_name=artist_name,
            endpoint=f'search_{search_type}_{album_title}',
            fetch_func=fetch_func,
            ttl_seconds=24 * 60 * 60  # 24 hours for Discogs data per CLAUDE.md
        )

        # Reconstruct objects from cached JSON data if needed
        if isinstance(cached_result, dict) and 'results' in cached_result:
            # Create a mock search result with reconstructed Release objects
            class MockSearchResult:  # pylint: disable=too-few-public-methods
                """Mock search result with reconstructed Release objects."""
                def __init__(self, results):
                    self.results = []
                    for item in results:
                        if item['type'] == 'release':
                            # Reconstruct Release object
                            release = models.Release(item['data'])
                            # Reconstruct artist objects
                            release.artists = [models.Artist(artist_data)
                                              for artist_data in item['artists']]
                            self.results.append(release)

                def page(self, page_num):  # pylint: disable=unused-argument
                    """Return self for pagination compatibility."""
                    return self

                def __iter__(self):
                    return iter(self.results)

            return MockSearchResult(cached_result['results'])

        return cached_result

    async def _artist_async_cached(self, artist_id, artist_name):
        """Cached version of discogs artist_async."""

        async def fetch_func():
            artist = await self.client.artist_async(artist_id)
            # Convert to JSON-serializable format for caching
            if artist:
                return {
                    'type': 'artist',
                    'data': artist.data if hasattr(artist, 'data') else artist.__dict__
                }
            return None

        cached_result = await nowplaying.apicache.cached_fetch(
            provider='discogs',
            artist_name=artist_name,
            endpoint=f'artist_{artist_id}',
            fetch_func=fetch_func,
            ttl_seconds=24 * 60 * 60  # 24 hours for Discogs data per CLAUDE.md
        )

        # Reconstruct artist object from cached JSON data if needed
        if isinstance(cached_result, dict) and cached_result.get('type') == 'artist':
            # Reconstruct Artist object
            return models.Artist(cached_result['data'])

        return cached_result

    def _process_metadata(self, artistname, artist, imagecache):
        ''' update metadata based upon an artist record '''
        if artist.images and imagecache:
            self.addmeta['artistfanarturls'] = []
            gotonefanart = False
            for record in artist.images:
                if record['type'] == 'primary' and record.get(
                        'uri150') and self.config.cparser.value('discogs/thumbnails', type=bool):
                    imagecache.fill_queue(config=self.config,
                                          identifier=artistname,
                                          imagetype='artistthumbnail',
                                          srclocationlist=[record['uri150']])

                if record['type'] == 'secondary' and record.get(
                        'uri') and self.config.cparser.value('discogs/fanart', type=bool):
                    if not gotonefanart:
                        imagecache.fill_queue(config=self.config,
                                              identifier=artistname,
                                              imagetype='artistfanart',
                                              srclocationlist=[record['uri']])
                        gotonefanart = True
                    self.addmeta['artistfanarturls'].append(record['uri'])

        if self.config.cparser.value('discogs/bio', type=bool):
            self.addmeta['artistlongbio'] = artist.profile_plaintext

        if self.config.cparser.value('discogs/websites', type=bool):
            self.addmeta['artistwebsites'] = artist.urls

    async def _find_discogs_website_async(self, metadata, imagecache):
        ''' async use websites listing to find discogs entries '''
        if not self.client and not self._setup_client():
            return False

        if not self.client or not metadata.get('artistwebsites'):
            return False

        artistnum = 0
        artist = None
        discogs_websites = [url for url in metadata['artistwebsites'] if 'discogs' in url]
        if len(discogs_websites) == 1:
            artistnum = discogs_websites[0].split('/')[-1]
            artist = await self._artist_async_cached(artistnum, metadata['artist'])
            artistname = str(artist.name)
            logging.debug('Found a singular discogs artist URL using %s instead of %s', artistname,
                          metadata['artist'])
        elif len(discogs_websites) > 1:
            for website in discogs_websites:
                artistnum = website.split('/')[-1]
                artist = await self._artist_async_cached(artistnum, metadata['artist'])
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

    async def _find_discogs_artist_releaselist_async(self, metadata):
        ''' async given metadata, find the releases for an artist '''
        if not self.client and not self._setup_client():
            return None

        if not self.client:
            return None

        artistname = metadata['artist']
        try:
            logging.debug('Fetching async %s - %s', artistname, metadata['album'])
            resultlist = await self._search_async_cached(metadata['album'], artistname, 'title')
            # Get first page if paginated results
            if hasattr(resultlist, 'page'):
                resultlist = resultlist.page(1)
        except asyncio.TimeoutError:
            logging.error('discogs async releaselist timeout error')
            return None
        except Exception as error:  # pragma: no cover pylint: disable=broad-except
            logging.error('discogs async hit %s', error)
            return None

        return next(
            (result.artists[0] for result in resultlist if isinstance(result, models.Release)),
            None,
        )

    async def download_async(self, metadata=None, imagecache=None):  # pylint: disable=too-many-branches, too-many-return-statements
        ''' async download content '''

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

        if await self._find_discogs_website_async(metadata, imagecache):
            logging.debug('used discogs website')
            return self.addmeta

        oldartist = metadata['artist']
        artistresultlist = None
        for variation in nowplaying.utils.artist_name_variations(metadata['artist']):
            metadata['artist'] = variation
            artistresultlist = await self._find_discogs_artist_releaselist_async(metadata)
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
