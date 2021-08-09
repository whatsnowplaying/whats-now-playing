#!/usr/bin/env python3
# pylint: disable=invalid-name
''' Use ACRCloud to recognize the file '''

import os
import sys

import logging
import logging.config
import logging.handlers

import musicbrainzngs

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.version


class MusicBrainzHelper():
    ''' handler for NowPlaying '''
    def __init__(self, config=None):
        if config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()
        emailaddress = self.config.cparser.value('acoustidmb/emailaddress')

        if not emailaddress:
            emailaddress = 'aw@effectivemachines.com'

        musicbrainzngs.set_useragent(
            'whats-now-playing',
            nowplaying.version.get_versions()['version'],
            contact=emailaddress)

    def isrc(self, isrc):
        ''' lookup musicbrainz information based upon isrc '''
        if not self.config.cparser.value('acoustidmb/enabled', type=bool):
            return None

        try:
            mbdata = musicbrainzngs.get_recordings_by_isrc(
                isrc,
                includes=['releases'],
                release_status=['official'],
                release_type=['single'])
        except Exception:  # pylint: disable=broad-except
            try:
                mbdata = musicbrainzngs.get_recordings_by_isrc(
                    isrc, includes=['releases'], release_status=['official'])
            except Exception:  # pylint: disable=broad-except
                try:
                    mbdata = musicbrainzngs.get_recordings_by_isrc(
                        isrc, includes=['releases'])
                except Exception:  # pylint: disable=broad-except
                    logging.info('musicbrainz cannot find this ISRC')
                    return None

        if 'isrc' not in mbdata or 'recording-list' not in mbdata['isrc']:
            return None

        recordinglist = sorted(mbdata['isrc']['recording-list'],
                               key=lambda k: k['release-count'],
                               reverse=True)
        return self.recordingid(recordinglist[0]['id'])

    def recordingid(self, recordingid):  # pylint: disable=too-many-branches, too-many-return-statements
        ''' lookup the musicbrainz information based upon recording id '''
        if not self.config.cparser.value('acoustidmb/enabled', type=bool):
            return None

        def read_label(releasedata):
            if 'label-info-list' not in releasedata:
                return None

            for labelinfo in releasedata['label-info-list']:
                if 'type' not in labelinfo['label']:
                    continue

                if 'name' in labelinfo['label']:
                    return labelinfo['label']['name']

            return None

        newdata = {}
        try:
            mbdata = musicbrainzngs.get_recording_by_id(recordingid)
        except Exception:  # pylint: disable=broad-except
            logging.error('MusicBrainz does not know recording id %s',
                          recordingid)
            return None

        if 'recording' in mbdata and 'title' in mbdata['recording']:
            newdata['title'] = mbdata['recording']['title']

        try:
            mbdata = musicbrainzngs.browse_releases(
                recording=recordingid,
                includes=['labels', 'artist-credits'],
                release_status=['official'],
                release_type=['single'])
        except Exception as error:  # pylint: disable=broad-except
            logging.debug('MusicBrainz threw an error: %s', error)
            return None

        if 'release-count' not in mbdata or mbdata['release-count'] == 0:
            try:
                mbdata = musicbrainzngs.browse_releases(
                    recording=recordingid,
                    includes=['labels', 'artist-credits'],
                    release_status=['official'])
            except Exception:  # pylint: disable=broad-except
                logging.debug('MusicBrainz threw an error: %s', error)
                return None

        if 'release-count' not in mbdata or mbdata['release-count'] == 0:
            try:
                mbdata = musicbrainzngs.browse_releases(
                    recording=recordingid,
                    includes=['labels', 'artist-credits'])
            except Exception:  # pylint: disable=broad-except
                logging.debug('MusicBrainz threw an error: %s', error)
                return None

        if 'release-count' not in mbdata or mbdata['release-count'] == 0:
            return newdata

        musicdata = mbdata['release-list'][0]
        if 'artist-credit-phrase' in musicdata:
            newdata['artist'] = musicdata['artist-credit-phrase']
        if 'title' in musicdata:
            newdata['album'] = musicdata['title']
        if 'date' in musicdata:
            newdata['date'] = musicdata['date']
        label = read_label(musicdata)
        if label:
            newdata['label'] = label
        if 'cover-art-archive' in musicdata and 'artwork' in musicdata[
                'cover-art-archive'] and musicdata['cover-art-archive'][
                    'artwork']:
            try:
                newdata['coverimageraw'] = musicbrainzngs.get_image(
                    musicdata['id'], 'front')
            except Exception as error:  # pylint: disable=broad-except
                logging.error('Failed to get cover art: %s', error)

        return newdata

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this recognition system '''
        return [
            'album',
            'artist',
            'coverimageraw',
            'date',
            'label',
            'title',
        ]


def main():
    ''' integration test '''
    isrc = sys.argv[1]

    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names()
    # need to make sure config is initialized with something
    nowplaying.config.ConfigFile(bundledir=bundledir)
    musicbrainz = MusicBrainzHelper(config=nowplaying.config.ConfigFile(
        bundledir=bundledir))
    metadata = musicbrainz.isrc(isrc)
    if not metadata:
        print('No information')
        sys.exit(1)

    if 'coverimageraw' in metadata:
        print('got an image')
        del metadata['coverimageraw']
    print(metadata)


if __name__ == "__main__":
    main()
