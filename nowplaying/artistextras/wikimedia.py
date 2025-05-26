#!/usr/bin/env python3
''' start of support of discogs '''

import logging

import nowplaying.apicache
import nowplaying.wikiclient

from nowplaying.artistextras import ArtistExtrasPlugin


class Plugin(ArtistExtrasPlugin):
    ''' handler for discogs '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Wikimedia"
        self.priority = 1000

    def _check_missing(self, metadata):
        ''' check for missing required data '''
        if not self.config or not self.config.cparser.value('wikimedia/enabled', type=bool):
            logging.debug('not configured')
            return True

        if not metadata:
            logging.debug('no metadata?')
            return True

        if not metadata.get('artistwebsites'):
            logging.debug('No artistwebsites.')
            return True
        return False

    async def _get_page_cached(self, entity, lang, artist_name):
        """Cached version of _get_page_async for better performance."""
        
        # Check what features are enabled to optimize API calls
        need_bio = self.config.cparser.value('wikimedia/bio', type=bool)
        need_images = (self.config.cparser.value('wikimedia/fanart', type=bool)
                       or self.config.cparser.value('wikimedia/thumbnails', type=bool))

        async def fetch_func():
            page = await nowplaying.wikiclient.get_page_async(
                entity=entity,
                lang=lang,
                timeout=5,
                need_bio=need_bio,
                need_images=need_images,
                max_images=5  # Limit for performance during live shows
            )
            # Convert to JSON-serializable format for caching
            if page:
                return {
                    'entity': page.entity,
                    'lang': page.lang,
                    'data': page.data,
                    'images': page._images,
                    'type': 'wikipage'
                }
            return None

        cached_result = await nowplaying.apicache.cached_fetch(
            provider='wikimedia',
            artist_name=artist_name,
            endpoint=f'{entity}_{lang}',  # Unique per entity + language combination
            fetch_func=fetch_func,
            ttl_seconds=24 * 60 * 60  # 24 hours for Wikimedia data per CLAUDE.md
        )

        # Reconstruct WikiPage object from cached JSON data if needed
        if isinstance(cached_result, dict) and cached_result.get('type') == 'wikipage':
            # Create a mock WikiPage with the cached data
            class MockWikiPage:
                def __init__(self, entity, lang, data, images):
                    self.entity = entity
                    self.lang = lang
                    self.data = data
                    self._images = images

                def images(self, fields=None):
                    if fields is None:
                        return self._images
                    return [{k: img.get(k) for k in fields if k in img} for img in self._images]

            return MockWikiPage(
                cached_result['entity'],
                cached_result['lang'], 
                cached_result['data'],
                cached_result['images']
            )

        return cached_result

    async def _get_page_async(self, entity, lang):
        logging.debug("Processing async %s", entity)

        # Check what features are enabled to optimize API calls
        need_bio = self.config.cparser.value('wikimedia/bio', type=bool)
        need_images = (self.config.cparser.value('wikimedia/fanart', type=bool)
                       or self.config.cparser.value('wikimedia/thumbnails', type=bool))

        try:
            page = await nowplaying.wikiclient.get_page_async(
                entity=entity,
                lang=lang,
                timeout=5,
                need_bio=need_bio,
                need_images=need_images,
                max_images=5  # Limit for performance during live shows
            )
        except Exception:  # pylint: disable=broad-except
            page = None
            if self.config.cparser.value('wikimedia/bio_iso_en_fallback',
                                         type=bool) and lang != 'en':
                try:
                    page = await nowplaying.wikiclient.get_page_async(entity=entity,
                                                                      lang='en',
                                                                      timeout=5,
                                                                      need_bio=need_bio,
                                                                      need_images=need_images,
                                                                      max_images=5)
                except Exception as err:  # pylint: disable=broad-except
                    page = None
                    logging.exception("wikimedia async page failure (%s): %s", err, entity)

        return page

    async def download_async(self,  # pylint: disable=too-many-branches
                             metadata=None,
                             imagecache: "nowplaying.imagecache.ImageCache" = None):
        ''' async download content '''

        async def _get_bio_async():
            if page.data.get('extext'):
                mymeta['artistlongbio'] = page.data['extext']
            elif lang != 'en' and self.config.cparser.value('wikimedia/bio_iso_en_fallback',
                                                            type=bool):
                temppage = await self._get_page_cached(entity, 'en', metadata['artist'])
                if temppage and temppage.data.get('extext'):
                    mymeta['artistlongbio'] = temppage.data['extext']

            if not mymeta.get('artistlongbio') and page.data.get('description'):
                mymeta['artistshortbio'] = page.data['description']

        if not metadata or self._check_missing(metadata):
            return {}

        mymeta = {}
        try:  # pylint: disable=too-many-nested-blocks
            wikidata_websites = [url for url in metadata['artistwebsites'] if 'wikidata' in url]
            if not wikidata_websites:
                logging.debug('no wikidata entity')
                return {}

            lang = self.config.cparser.value('wikimedia/bio_iso', type=str) or 'en'
            for website in wikidata_websites:
                entity = website.split('/')[-1]
                page = await self._get_page_cached(entity, lang, metadata['artist'])
                if not page or not page.data:
                    continue

                if self.config.cparser.value('wikimedia/bio', type=bool):
                    await _get_bio_async()

                if page.data['claims'].get('P434'):
                    mymeta['musicbrainzartistid'] = page.data['claims'].get('P434')
                mymeta['artistwebsites'] = []
                if page.data['claims'].get('P1953'):
                    mymeta['artistwebsites'].append(
                        f"https://discogs.com/artist/{page.data['claims'].get('P1953')[0]}")
                mymeta['artistfanarturls'] = []
                thumbs = []
                if page.images():
                    gotonefanart = False
                    for image in page.images(['kind', 'url']):
                        if image.get('url') and image['kind'] in [
                                'wikidata-image', 'parse-image'
                        ] and self.config.cparser.value('wikimedia/fanart', type=bool):
                            mymeta['artistfanarturls'].append(image['url'])
                            if not gotonefanart and imagecache:
                                gotonefanart = True
                                imagecache.fill_queue(config=self.config,
                                                      identifier=metadata['imagecacheartist'],
                                                      imagetype='artistfanart',
                                                      srclocationlist=[image['url']])
                        elif image['kind'] == 'query-thumbnail':
                            thumbs.append(image['url'])

                if imagecache and thumbs and self.config.cparser.value('wikimedia/thumbnails',
                                                                       type=bool):
                    imagecache.fill_queue(config=self.config,
                                          identifier=metadata['imagecacheartist'],
                                          imagetype='artistthumbnail',
                                          srclocationlist=thumbs)
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("Async metadata breaks wikimedia (%s): %s", err, metadata)
        return mymeta

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this plug-in '''
        return ['artistlongbio', 'wikimedia-artistfanarturls', 'artistwebsites']

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        if self.config.cparser.value('wikimedia/enabled', type=bool):
            qwidget.wikimedia_checkbox.setChecked(True)
        else:
            qwidget.wikimedia_checkbox.setChecked(False)

        for field in ['bio', 'fanart', 'thumbnails', 'websites']:
            func = getattr(qwidget, f'{field}_checkbox')
            func.setChecked(self.config.cparser.value(f'wikimedia/{field}', type=bool))
        qwidget.bio_iso_lineedit.setText(self.config.cparser.value('wikimedia/bio_iso'))
        if self.config.cparser.value('wikimedia/bio_iso_en_fallback', type=bool):
            qwidget.bio_iso_en_checkbox.setChecked(True)
        else:
            qwidget.bio_iso_en_checkbox.setChecked(False)

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

        self.config.cparser.setValue('wikimedia/enabled', qwidget.wikimedia_checkbox.isChecked())

        for field in ['bio', 'fanart', 'thumbnails', 'websites']:
            func = getattr(qwidget, f'{field}_checkbox')
            self.config.cparser.setValue(f'wikimedia/{field}', func.isChecked())
        self.config.cparser.setValue('wikimedia/bio_iso',
                                     str(qwidget.bio_iso_lineedit.text()).lower())
        self.config.cparser.setValue('wikimedia/bio_iso_en_fallback',
                                     qwidget.bio_iso_en_checkbox.isChecked())

    def defaults(self, qsettings):
        for field in ['bio', 'fanart', 'thumbnails', 'websites']:
            qsettings.setValue(f'wikimedia/{field}', True)

        qsettings.setValue('wikimedia/enabled', True)
        qsettings.setValue('wikimedia/bio_iso', 'en')
        qsettings.setValue('wikimedia/bio_iso_en_fallback', True)
