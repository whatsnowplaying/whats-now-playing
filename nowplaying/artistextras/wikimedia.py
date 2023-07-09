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

    def download(self, metadata=None, imagecache=None):
        ''' download content '''

        if self._check_missing(metadata):
            return {}

        mymeta = {}
        wikidata_websites = [url for url in metadata['artistwebsites'] if 'wikidata' in url]
        if not wikidata_websites:
            logging.debug('no wikidata entity')
            return {}

        for website in wikidata_websites:
            entity = website.split('/')[-1]
            logging.debug("Processing %s", entity)
            page = wptools.page(wikibase=entity, silent=True)
            page.get()

            if page.data['extext'] and self.config.cparser.value('wikimedia/bio', type=bool):
                mymeta['artistlongbio'] = page.data['extext']
            if page.data['claims'].get('P434'):
                mymeta['musicbrainzartistid'] = page.data['claims'].get('P434')
            mymeta['artistwebsites'] = []
            if page.data['claims'].get('P1953'):
                mymeta['artistwebsites'].append(
                    f"https://discogs.com/artist/{page.data['claims'].get('P1953')[0]}")
            mymeta['artistfanarturls'] = []
            thumbs = []
            if page.images():
                for image in page.images(['kind', 'url']):
                    if image['kind'] in ['wikidata-image', 'parse-image'
                                         ] and self.config.cparser.value('wikimedia/fanart',
                                                                         type=bool):
                        mymeta['artistfanarturls'].append(image['url'])
                    elif image['kind'] == 'query-thumbnail':
                        thumbs.append(image['url'])

            if imagecache and thumbs and self.config.cparser.value('wikimedia/thumbnails',
                                                                   type=bool):
                imagecache.fill_queue(config=self.config,
                                      artist=metadata['artist'],
                                      imagetype='artistthumb',
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

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

        self.config.cparser.setValue('wikimedia/enabled', qwidget.wikimedia_checkbox.isChecked())

        for field in ['bio', 'fanart', 'thumbnails', 'websites']:
            func = getattr(qwidget, f'{field}_checkbox')
            self.config.cparser.setValue(f'wikimedia/{field}', func.isChecked())

    def defaults(self, qsettings):
        for field in ['bio', 'fanart', 'thumbnails', 'websites']:
            qsettings.setValue(f'wikimedia/{field}', False)

        qsettings.setValue('wikimedia/enabled', False)
