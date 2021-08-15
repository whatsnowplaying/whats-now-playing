#!/usr/bin/env python3
# pylint: disable=invalid-name
''' Use ACRCloud to recognize the file '''

import json
import os
import sys

import logging
import logging.config
import logging.handlers

try:
    from acrcloud.recognizer import ACRCloudRecognizer
    ACRCLOUD_STATUS = True
except ImportError:
    ACRCLOUD_STATUS = False

import nowplaying.bootstrap
import nowplaying.config
from nowplaying.recognition import RecognitionPlugin
from nowplaying.exceptions import PluginVerifyError


class Plugin(RecognitionPlugin):
    ''' handler for NowPlaying '''
    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)

    def _response_check(self, data):  # pylint: disable=no-self-use
        if not data or 'status' not in data or 'metadata' not in data:
            logging.warning('Empty response from ACRCloud')
            return False

        if 'msg' not in data['status'] or data['status']['msg'] != 'Success':
            logging.info('ACRCloud does not know this track')
            return False

        if 'music' not in data['metadata']:
            logging.info('ACRCloud did not return a music identifier.')
            return False

        if 'score' not in data['metadata']['music'][0]:
            logging.info('ACRCloud did not return a score. Ignoring')
            return False

        logging.debug('ACRCloud confidence: %s',
                      data['metadata']['music'][0]['score'])
        if data['metadata']['music'][0]['score'] < 50:
            logging.info('ACRCloud returned a score less than 50: %s',
                         data['metadata']['music'])
            return False

        return True

    def recognize(self, metadata):  # pylint: disable=too-many-branches
        if not self.config.cparser.value('acrcloud/enabled', type=bool):
            return None

        if 'filename' not in metadata:
            return None

        if not ACRCLOUD_STATUS:
            logging.error(
                'Unable to load ACRCloud support. Is VCREDIST installed?')
            return None

        acrcloudconfig = {
            'host': self.config.cparser.value('acrcloud/host'),
            'access_key': self.config.cparser.value('acrcloud/key'),
            'access_secret': self.config.cparser.value('acrcloud/secret'),
            'timeout': 20  # seconds
        }

        logging.debug('Trying ACRCloud on %s', metadata['filename'])
        try:
            recognizer = ACRCloudRecognizer(acrcloudconfig)
            data = recognizer.recognize_by_file(metadata['filename'], 0)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('Problem getting a response from ACRCloud: %s',
                          error)
            return None

        # the APIs for ACRCloud can get weird
        if isinstance(data, str):
            data = json.loads(data)

        if not self._response_check(data):
            return None

        try:
            musicdata = sorted(data['metadata']['music'],
                               key=lambda k: k['release_date'],
                               reverse=False)[0]
        except Exception:  # pylint: disable=broad-except
            musicdata = data['metadata']['music'][0]

        logging.debug('Using %s', musicdata)
        if 'album' in musicdata:
            metadata['album'] = musicdata['album']['name']
        if 'artists' in musicdata:
            metadata['artist'] = '; '.join(
                list(map(lambda x: x['name'], musicdata['artists'])))
        if 'label' in musicdata:
            metadata['label'] = musicdata['label']
        if 'date' in musicdata:
            metadata['date'] = musicdata['release_date']
        if 'title' in musicdata:
            metadata['title'] = musicdata['title']

        # ACRCloud's musicbrainz data is slightly unreliable but... generally better than nothing.

        if 'external_metadata' in musicdata and 'musicbrainz' in musicdata[
                'external_metadata']:
            if isinstance(musicdata['external_metadata']['musicbrainz'], list):
                metadata['musicbrainzrecordingid'] = musicdata[
                    'external_metadata']['musicbrainz'][0]['track']['id']
            else:
                metadata['musicbrainzrecordingid'] = musicdata[
                    'external_metadata']['musicbrainz']['track']['id']

        return metadata

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this recognition system '''
        return [
            'album',
            'artist',
            'date',
            'label',
            'title',
        ]

    def connect_settingsui(self, qwidget):
        ''' not needed '''

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        if self.config.cparser.value('acrcloud/enabled', type=bool):
            qwidget.acrcloud_checkbox.setChecked(True)
        else:
            qwidget.acrcloud_checkbox.setChecked(False)
        qwidget.host_lineedit.setText(
            self.config.cparser.value('acrcloud/host'))
        qwidget.access_key_lineedit.setText(
            self.config.cparser.value('acrcloud/key'))
        qwidget.access_secret_lineedit.setText(
            self.config.cparser.value('acrcloud/secret'))

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''
        if qwidget.acrcloud_checkbox.isChecked(
        ) and not qwidget.acrcrloud_host_lineedit.txt(
        ) and not qwidget.access_key_lineedit.text(
        ) and not qwidget.acess_secret_lineedit.text():
            raise PluginVerifyError(
                'ACRCloud enabled, but no authentication provided.')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('acrcloud/enabled',
                                     qwidget.acrcloud_checkbox.isChecked())
        self.config.cparser.setValue('acrcloud/host',
                                     qwidget.host_lineedit.text())
        self.config.cparser.setValue('acrcloud/key',
                                     qwidget.access_key_lineedit.text())
        self.config.cparser.setValue('acrcloud/secret',
                                     qwidget.access_secret_lineedit.text())

    def defaults(self, qsettings):
        qsettings.setValue('acrcloud/enabled', False)
        qsettings.setValue('acrcloud/host', None)
        qsettings.setValue('acrcloud/key', None)
        qsettings.setValue('acrcloud/secret', None)


def main():
    ''' integration test '''
    filename = sys.argv[1]

    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names()
    # need to make sure config is initialized with something
    nowplaying.config.ConfigFile(bundledir=bundledir)
    plugin = Plugin()
    print(plugin.recognize({'filename': filename}))


if __name__ == "__main__":
    main()
