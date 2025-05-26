#!/usr/bin/env python3
# pylint: disable=invalid-name
''' support for musicbrainz '''

import contextlib
import functools
import logging
import logging.config
import logging.handlers
import os
import re
import sys

from . import client
import nowplaying.cachingdecorator

import nowplaying.bootstrap
import nowplaying.config
from nowplaying.utils import normalize_text, normalize, artist_name_variations

REMIX_RE = re.compile(r'^\s*(.*)\s+[\(\[].*[\)\]]$')


@functools.lru_cache(maxsize=128, typed=False)
def _verify_artist_name(artistname, artistcredit):
    logging.debug('called verify_artist_name: %s vs %s', artistname, artistcredit)
    if 'Various Artists' in artistcredit:
        logging.debug('skipped %s -- VA')
        return False
    normname = normalize(artistname, nospaces=True)
    normcredit = normalize(artistcredit, nospaces=True)
    if not normname or not normcredit or normname not in normcredit:
        logging.debug('rejecting %s (ours) not in %s (mb)', normname, normcredit)
        return False
    return True


class MusicBrainzHelper():
    ''' handler for NowPlaying '''

    def __init__(self, config=None):
        logging.getLogger('musicbrainzngs').setLevel(logging.INFO)
        if config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()

        self.emailaddressset = False
        # Create our own MusicBrainz client instance
        self.mb_client = client.MusicBrainzClient(
            rate_limit_interval=0.5
        )

    def _setemail(self):
        ''' make sure the musicbrainz fetch has an email address set
            according to their requirements '''
        if not self.emailaddressset:
            emailaddress = self.config.cparser.value(
                'musicbrainz/emailaddress') or 'aw+wnp@effectivemachines.com'

            self.mb_client.set_useragent('whats-now-playing', self.config.version, emailaddress)
            self.emailaddressset = True

    async def _pickarecording(self, testdata, mbdata, allowothers=False):  #pylint: disable=too-many-statements, too-many-branches
        ''' core routine for last ditch '''

        def _check_build_artid():
            if len(recording['artist-credit']) > 1:
                artname = ''
                artid = []
                for artdata in recording['artist-credit']:
                    if isinstance(artdata, dict):
                        artname = artname + artdata['name']
                        artid.append(artdata['artist']['id'])
                        if testdata.get('artist') and not _verify_artist_name(
                                artdata['name'], testdata['artist']):
                            logging.debug('Rejecting bz %s does not appear in %s', artdata['name'],
                                          testdata['artist'])
                            return []
                    else:
                        artname = artname + artdata

                #if not _verify_artist_name(testdata.get('artist'), artname):
                #    return []
                mbartid = artid
            else:
                if not _verify_artist_name(testdata.get('artist'),
                                           recording['artist-credit'][0]['name']):
                    return []
                #logging.debug(recording)
                mbartid = [recording['artist-credit'][0]['artist']['id']]
            return mbartid

        def _check_not_allow_others():
            if relgroup.get('type') and 'Compilation' in relgroup['type']:
                logging.debug('skipped %s -- compilation type', title)
                return False
            if relgroup.get('secondary-type-list'):
                if 'Compilation' in relgroup['secondary-type-list']:
                    logging.debug('skipped %s -- 2nd compilation', title)
                    return False
                if 'Live' in relgroup['secondary-type-list']:
                    logging.debug('skipped %s -- 2nd live', title)
                    return False
            return True

        riddata = {}
        mbartid = []
        if not mbdata.get('recording-list'):
            return riddata

        newlist = sorted(mbdata['recording-list'],
                         key=lambda d: d.get('first-release-date', '9999-99-99'))
        variousartistrid = None
        #logging.debug(newlist)
        for recording in newlist:
            rid = recording['id']
            logging.debug('recording id = %s', rid)
            if not recording.get('release-list'):
                logging.debug('skipping recording id %s -- no releases', rid)
                continue
            mbartid = _check_build_artid()
            if not mbartid:
                continue
            for release in recording['release-list']:
                title = release['title']
                if testdata.get('album') and normalize_text(
                        testdata['album']) != normalize_text(title):
                    logging.debug('skipped %s <> %s', title, testdata['album'])
                    continue
                if release.get('artist-credit'
                               ) and release['artist-credit'][0]['name'] == 'Various Artists':
                    if not variousartistrid:
                        variousartistrid = rid
                        logging.debug('saving various artist just in case')
                    else:
                        logging.debug('already have a various artist')
                    continue
                relgroup = release['release-group']
                if not relgroup:
                    logging.debug('skipped %s -- no rel group', title)
                    continue
                if not allowothers and not _check_not_allow_others():
                    continue
                logging.debug('checking %s', recording['id'])
                if riddata := await self.recordingid(recording['id']):
                    return riddata
        if not riddata and variousartistrid:
            logging.debug('Using a previous analyzed various artist release')
            if riddata := await self.recordingid(variousartistrid):
                riddata['musicbrainzartistid'] = mbartid
                return riddata
        logging.debug('Exitting pick a recording')
        return riddata

    async def _lastditchrid(self, metadata):

        async def havealbum():
            for artist in artist_name_variations(addmeta['artist']):
                try:
                    mydict = await self.mb_client.search_recordings(artist=artist,
                                                                         recording=addmeta['title'],
                                                                         release=addmeta['album'])
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.exception("mb_client.search_recordings- ar:%s, t:%s, al:%s",
                                      artist, addmeta['title'], addmeta['album'])
                    continue

                if riddata := await self._pickarecording(addmeta,
                                                         mydict) or await self._pickarecording(
                                                             addmeta, mydict, allowothers=True):
                    return riddata
            return {}

        mydict = {}
        riddata = {}
        addmeta = {
            'artist': metadata.get('artist'),
            'title': metadata.get('title'),
            'album': metadata.get('album')
        }

        if addmeta.get('musicbrainzrecordingid'):
            logging.debug('Skipping fallback: already have a rid')
            return None

        logging.debug('Starting data: %s', addmeta)
        if addmeta['album']:
            if riddata := await havealbum():
                return riddata

        for artist in artist_name_variations(addmeta['artist']):
            logging.debug('Trying %s', artist)
            try:
                mydict = await self.mb_client.search_recordings(artist=artist,
                                                                     recording=addmeta['title'])
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("mb_client.search_recordings- ar:%s, t:%s (strict)", artist,
                                  addmeta['title'])
                continue

            if mydict.get('recording-count', 0) == 0:
                logging.debug('no recordings found for this artist/title combination')
                continue

            if mydict.get('recording-count', 0) > 100:
                logging.debug('too many, going stricter')
                query = (f"artist:{artist} AND recording:\"{addmeta['title']}\" AND "
                         "-(secondarytype:compilation OR secondarytype:live) AND status:official")
                logging.debug(query)
                try:
                    mydict = await self.mb_client.search_recordings(query=query, limit=100)
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.exception("mb_client.search_recordings- q:%s", query)
                continue
            if riddata := await self._pickarecording(addmeta, mydict):
                return riddata

        if riddata := await self._pickarecording(addmeta, mydict, allowothers=True):
            return riddata
        logging.debug('Last ditch MB lookup failed. Sorry.')
        return riddata

    async def lastditcheffort(self, metadata):
        ''' there is like no data, so... '''

        if not self.config.cparser.value('musicbrainz/enabled',
                                         type=bool) or self.config.cparser.value('control/beam',
                                                                                 type=bool):
            return None

        self._setemail()

        addmeta = {
            'artist': metadata.get('artist'),
            'title': metadata.get('title'),
            'album': metadata.get('album')
        }

        riddata = await self._lastditchrid(addmeta)
        if not riddata and REMIX_RE.match(addmeta['title']):
            addmeta['title'] = REMIX_RE.match(addmeta['title']).group(1)
            riddata = await self._lastditchrid(addmeta)

        if riddata:
            if normalize(riddata['title']) != normalize(metadata.get('title')):
                logging.debug('No title match, so just using artist data')

                # Check if strict album matching is enabled
                strict_album_matching = self.config.cparser.value(
                    'musicbrainz/strict_album_matching', True, type=bool)

                # If original request had an album and we're in strict mode, return nothing
                # rather than partial data to avoid wrong album information
                if strict_album_matching and metadata.get('album'):
                    logging.debug(
                        'Strict album matching enabled: rejecting partial match for album request')
                    return None

                # Otherwise, return artist data without album/recording info
                for delitem in [
                        'album',
                        'coverimageraw',
                        'date',
                        'genre',
                        'label',
                        'musicbrainzrecordingid',
                ]:
                    if delitem in riddata:
                        del riddata[delitem]
            logging.debug('metadata added artistid = %s / recordingid = %s',
                          riddata.get('musicbrainzartistid'), riddata.get('musicbrainzrecordingid'))
        return riddata

    async def recognize(self, metadata):
        ''' fill in any blanks from musicbrainz '''

        if not self.config.cparser.value('musicbrainz/enabled',
                                         type=bool) or self.config.cparser.value('control/beam',
                                                                                 type=bool):
            return None

        addmeta = {}

        if metadata.get('musicbrainzrecordingid'):
            logging.debug('Preprocessing with musicbrainz recordingid')
            addmeta = await self.recordingid(metadata['musicbrainzrecordingid'])
        elif metadata.get('isrc'):
            logging.debug('Preprocessing with musicbrainz isrc')
            addmeta = await self.isrc(metadata['isrc'])
        elif metadata.get('musicbrainzartistid'):
            logging.debug('Preprocessing with musicbrainz artistid')
            addmeta = await self.artistids(metadata['musicbrainzartistid'])
        return addmeta

    async def isrc(self, isrclist):
        ''' lookup musicbrainz information based upon isrc '''
        if not self.config.cparser.value('musicbrainz/enabled',
                                         type=bool) or self.config.cparser.value('control/beam',
                                                                                 type=bool):
            return None

        self._setemail()
        mbdata = {}

        for isrc in isrclist:
            with contextlib.suppress(Exception):
                mbdata = await self.mb_client.get_recordings_by_isrc(
                    isrc, includes=['releases'], release_status=['official'])
        if not mbdata:
            for isrc in isrclist:
                try:
                    mbdata = await self.mb_client.get_recordings_by_isrc(
                        isrc, includes=['releases'])
                except Exception as error:  # pylint: disable=broad-except
                    logging.info('musicbrainz cannot find ISRC %s: %s', isrc, error)

        if 'isrc' not in mbdata or 'recording-list' not in mbdata['isrc']:
            return None

        recordinglist = sorted(mbdata['isrc']['recording-list'],
                               key=lambda k: k['release-count'],
                               reverse=True)
        return await self.recordingid(recordinglist[0]['id'])

    async def recordingid(self, recordingid):  # pylint: disable=too-many-branches, too-many-return-statements, too-many-statements
        ''' lookup the musicbrainz information based upon recording id '''
        if not self.config.cparser.value('musicbrainz/enabled',
                                         type=bool) or self.config.cparser.value('control/beam',
                                                                                 type=bool):
            return None

        # Use cached version for better performance
        async def fetch_func():
            return await self._recordingid_uncached(recordingid)

        return await nowplaying.cachingdecorator.cached_fetch(
            provider='musicbrainz',
            artist_name='recording',  # Use a generic key for recording lookups
            endpoint=f'recording/{recordingid}',
            fetch_func=fetch_func,
            ttl_seconds=7 * 24 * 60 * 60  # 7 days for MusicBrainz data
        )

    async def _recordingid_uncached(self, recordingid):  # pylint: disable=too-many-branches,too-many-statements
        ''' uncached version of recordingid lookup '''
        self._setemail()

        def read_label(releasedata):
            if 'label-info-list' not in releasedata:
                return None

            for labelinfo in releasedata['label-info-list']:
                if 'label' not in labelinfo:
                    continue

                if 'type' not in labelinfo['label']:
                    continue

                if 'name' in labelinfo['label']:
                    return labelinfo['label']['name']

            return None

        async def releaselookup_noartist(recordingid):
            mbdata = None

            self._setemail()

            try:
                mbdata = await self.mb_client.browse_releases(
                    recording=recordingid,
                    includes=['artist-credits', 'labels', 'release-groups', 'release-group-rels'],
                    release_status=['official'])
            except Exception as error:  # pylint: disable=broad-except
                logging.error('MusicBrainz threw an error: %s', error)
                return None

            if 'release-count' not in mbdata or mbdata['release-count'] == 0:
                try:
                    mbdata = await self.mb_client.browse_releases(
                        recording=recordingid,
                        includes=['artist-credits', 'labels', 'release-groups',
                                  'release-group-rels'])
                except Exception as error:  # pylint: disable=broad-except
                    logging.error('MusicBrainz threw an error: %s', error)
                    return None
            return mbdata

        def _pickarelease(newdata, mbdata):
            namedartist = []
            variousartist = []
            for release in mbdata['release-list']:
                if len(newdata['musicbrainzartistid']) > 1 and newdata.get(
                        'artist') and release['artist-credit-phrase'] in newdata['artist']:
                    namedartist.append(release)
                elif 'artist' in newdata and normalize_text(
                        release['artist-credit-phrase']) == normalize_text(newdata['artist']):
                    namedartist.append(release)
                elif release['artist-credit-phrase'] == 'Various Artists':
                    variousartist.append(release)

            if not namedartist:
                return variousartist

            return namedartist

        newdata = {'musicbrainzrecordingid': recordingid}
        try:
            logging.debug('looking up recording id %s', recordingid)
            mbdata = await self.mb_client.get_recording_by_id(
                recordingid, includes=['artists', 'genres', 'release-group-rels'])
        except Exception as error:  # pylint: disable=broad-except
            logging.error('MusicBrainz does not know recording id %s: %s', recordingid, error)
            return None

        if 'recording' in mbdata:
            if 'title' in mbdata['recording']:
                newdata['title'] = mbdata['recording']['title']
            if 'artist-credit-phrase' in mbdata['recording']:
                newdata['artist'] = mbdata['recording']['artist-credit-phrase']
                for artist in mbdata['recording']['artist-credit']:
                    if not isinstance(artist, dict):
                        continue
                    if not newdata.get('musicbrainzartistid'):
                        newdata['musicbrainzartistid'] = []
                    newdata['musicbrainzartistid'].append(artist['artist']['id'])
            if 'first-release-date' in mbdata['recording']:
                newdata['date'] = mbdata['recording']['first-release-date']
            if 'genre-list' in mbdata['recording']:
                newdata['genres'] = []
                for genre in sorted(mbdata['recording']['genre-list'],
                                    key=lambda d: d['count'],
                                    reverse=True):
                    newdata['genres'].append(genre['name'])
                newdata['genre'] = '/'.join(newdata['genres'])

        mbdata = await releaselookup_noartist(recordingid)

        if not mbdata or 'release-count' not in mbdata or mbdata['release-count'] == 0:
            return newdata

        mbdata = _pickarelease(newdata, mbdata)
        if not mbdata:
            logging.debug('questionable release; skipping for safety')
            return None

        release = mbdata[0]
        if 'title' in release:
            newdata['album'] = release['title']
        if 'date' in release and not newdata.get('date'):
            newdata['date'] = release['date']
        label = read_label(release)
        if label:
            newdata['label'] = label

        if 'cover-art-archive' in release and 'artwork' in release['cover-art-archive'] and release[
                'cover-art-archive']['artwork'] == 'true':
            try:
                newdata['coverimageraw'] = await self.mb_client.get_image_front(release['id'])
            except Exception as error:  # pylint: disable=broad-except
                logging.error('Failed to get release cover art: %s', error)

        if not newdata.get('coverimageraw'):
            try:
                newdata['coverimageraw'] = await self.mb_client.get_image_front(
                    release['release-group']['id'], 'release-group')
            except Exception as error:  # pylint: disable=broad-except
                logging.error('Failed to get release group cover art: %s', error)

        newdata['artistwebsites'] = await self._websites(newdata['musicbrainzartistid'])
        #self.recordingid_tempcache[recordingid] = newdata
        return newdata

    async def artistids(self, idlist):
        ''' add data available via musicbrainz artist ids '''

        self._setemail()

        if not self.config.cparser.value('musicbrainz/enabled',
                                         type=bool) or self.config.cparser.value('control/beam',
                                                                                 type=bool):
            return None

        return {'artistwebsites': await self._websites(idlist)}

    async def _websites(self, idlist):

        if not idlist:
            return None

        sitelist = []
        for artistid in idlist:
            if self.config.cparser.value('acoustidmb/musicbrainz', type=bool):
                sitelist.append(f'https://musicbrainz.org/artist/{artistid}')
            try:
                webdata = await self.mb_client.get_artist_by_id(artistid, includes=['url-rels'])
            except Exception as error:  # pylint: disable=broad-except
                logging.error('MusicBrainz does not know artistid id %s: %s', artistid, error)
                return None

            if not webdata.get('artist') or not webdata['artist'].get('url-relation-list'):
                continue

            convdict = {
                'bandcamp': 'bandcamp',
                'official homepage': 'homepage',
                'last.fm': 'lastfm',
                'discogs': 'discogs',
                'wikidata': 'wikidata'
            }

            for urlrel in webdata['artist']['url-relation-list']:
                #logging.debug('checking %s', urlrel['type'])
                for src, dest in convdict.items():
                    if self.config.cparser.value('discogs/enabled',
                                                 type=bool) and urlrel['type'] == 'discogs':
                        sitelist.append(urlrel['target'])
                        logging.debug('placed %s', dest)
                    elif urlrel['type'] == 'wikidata':
                        sitelist.append(urlrel['target'])
                    elif urlrel['type'] == src and self.config.cparser.value(f'acoustidmb/{dest}',
                                                                             type=bool):
                        sitelist.append(urlrel['target'])
                        logging.debug('placed %s', dest)
        return list(dict.fromkeys(sitelist))

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this recognition system '''
        return [
            'album', 'artist', 'artistwebsites', 'coverimageraw', 'date', 'label', 'title', 'genre',
            'genres'
        ]


def main():
    ''' integration test '''
    isrc = sys.argv[1]

    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names()
    # need to make sure config is initialized with something
    nowplaying.config.ConfigFile(bundledir=bundledir)
    musicbrainz = MusicBrainzHelper(config=nowplaying.config.ConfigFile(bundledir=bundledir))
    metadata = musicbrainz.recordingid(isrc)
    if not metadata:
        print('No information')
        sys.exit(1)

    if 'coverimageraw' in metadata:
        print('got an image')
        del metadata['coverimageraw']
    print(metadata)


if __name__ == "__main__":
    main()
