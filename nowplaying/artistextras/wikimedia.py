#!/usr/bin/env python3
''' start of support of discogs '''

import logging
from nowplaying.vendor import wptools

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

    def _get_page(self, entity, lang):
        logging.debug("Processing %s", entity)
        try:
            page = wptools.page(wikibase=entity, lang=lang, silent=True)
            page.get()
        except Exception:  # pylint: disable=broad-except
            page = None
            if self.config.cparser.value('wikimedia/bio_iso_en_fallback',
                                         type=bool) and lang != 'en':
                try:
                    page = wptools.page(wikibase=entity, lang='en', silent=True)
                    page.get()
                except Exception:  # pylint: disable=broad-except
                    page = None
        return page

    def download(self, metadata=None, imagecache=None):  # pylint: disable=too-many-branches
        ''' download content '''

        def _get_bio():
            if page.data.get('extext'):
                mymeta['artistlongbio'] = page.data['extext']
            elif lang != 'en' and self.config.cparser.value('wikimedia/bio_iso_en_fallback',
                                                            type=bool):
                temppage = self._get_page(entity, 'en')
                if temppage.data.get('extext'):
                    mymeta['artistlongbio'] = temppage.data['extext']

            if not mymeta.get('artistlongbio') and page.data.get('description'):
                mymeta['artistshortbio'] = page.data['description']

        if self._check_missing(metadata):
            return {}

        mymeta = {}
        wikidata_websites = [url for url in metadata['artistwebsites'] if 'wikidata' in url]
        if not wikidata_websites:
            logging.debug('no wikidata entity')
            return {}

        lang = self.config.cparser.value('wikimedia/bio_iso', type=str) or 'en'
        for website in wikidata_websites:
            entity = website.split('/')[-1]
            page = self._get_page(entity, lang)
            if not page:
                continue

            if self.config.cparser.value('wikimedia/bio', type=bool):
                _get_bio()

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
                    if image.get('url') and image['kind'] in ['wikidata-image', 'parse-image'
                                         ] and self.config.cparser.value('wikimedia/fanart',
                                                                         type=bool):
                        mymeta['artistfanarturls'].append(image['url'])
                        if not gotonefanart and imagecache:
                            gotonefanart = True
                            imagecache.fill_queue(config=self.config,
                                                  artist=metadata['imagecacheartist'],
                                                  imagetype='artistfanart',
                                                  urllist=[image['url']])
                    elif image['kind'] == 'query-thumbnail':
                        thumbs.append(image['url'])

            if imagecache and thumbs and self.config.cparser.value('wikimedia/thumbnails',
                                                                   type=bool):
                imagecache.fill_queue(config=self.config,
                                      artist=metadata['imagecacheartist'],
                                      imagetype='artistthumbnail',
                                      urllist=thumbs)
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
