#!/usr/bin/env python3
# pylint: disable=invalid-name
''' Use acoustid w/help from musicbrainz to recognize the file '''

import copy
import json
import os
import pathlib
import subprocess
import sys
import time

import logging
import logging.config
import logging.handlers

from PySide6.QtCore import QDir  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

import acoustid

import nowplaying.bootstrap
import nowplaying.config
from nowplaying.recognition import RecognitionPlugin
from nowplaying.exceptions import PluginVerifyError
import nowplaying.musicbrainz
import nowplaying.utils

import nowplaying.version


class Plugin(RecognitionPlugin):
    ''' handler for acoustidmb '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.qwidget = None
        self.musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(
            self.config)
        self.acoustidmd = {}
        self.fpcalcexe = None

    def _fetch_from_acoustid(self, apikey, filename):  # pylint: disable=no-self-use,too-many-branches
        results = None
        completedprocess = None
        fpcalc = os.environ.get('FPCALC', 'fpcalc')
        command = [fpcalc, '-json', "-length", '120', filename]
        completedprocess = None
        try:
            if sys.platform == "win32":
                completedprocess = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                completedprocess = subprocess.run(command,
                                                  stdin=subprocess.DEVNULL,
                                                  capture_output=True,
                                                  check=True)
        except Exception as error:  # pylint: disable=broad-except
            if completedprocess:
                logging.error('Exception: %s stderr: %s', error,
                              completedprocess.stderr)
            else:
                logging.error('Exception: %s', error)
            return None

        if not completedprocess or not completedprocess.stdout:
            return None

        data = json.loads(completedprocess.stdout.decode('utf-8'))

        try:
            counter = 0
            while counter < 3:
                logging.debug('Performing acoustid lookup')
                results = acoustid.lookup(apikey,
                                          data['fingerprint'],
                                          data['duration'],
                                          meta=[
                                              'recordings', 'recordingids',
                                              'releases', 'tracks', 'usermeta'
                                          ],
                                          timeout=5)
                if ('error' not in results
                        or 'rate limit' not in results['error']['message']):
                    break
                logging.info(
                    'acoustid complaining about rate limiting. Sleeping then rying again.'
                )
                time.sleep(.5)
                counter += 1
        except acoustid.NoBackendError:
            results = None
            logging.error("chromaprint library/tool not found")
        except acoustid.WebServiceError as error:
            results = None
            logging.error("web service request failed: %s", error)
        except Exception as error:  # pylint: disable=broad-except
            results = None
            logging.error('Problem getting a response from Acoustid: %s',
                          error)
        if not results:
            return None

        if 'error' in results:
            logging.error('Aborting. acoustid responded with: %s',
                          results['error']['message'])
            return None

        return results['results']

    def _read_acoustid_tuples(self, metadata, results):  # pylint: disable=too-many-branches, too-many-statements, too-many-locals
        fnstr = nowplaying.utils.normalize(metadata['filename'])
        artistnstr = ''
        titlenstr = ''
        if metadata.get('artist'):
            artistnstr = nowplaying.utils.normalize(metadata['artist'])
        if metadata.get('title'):
            titlenstr = nowplaying.utils.normalize(metadata['title'])

        completenstr = fnstr + artistnstr + titlenstr

        lastscore = 0
        artistlist = []
        title = None
        rid = None

        logging.debug(results)

        newdata = {}
        for result in results:  # pylint: disable=too-many-nested-blocks
            acoustidid = result['id']
            score = result['score']
            if 'recordings' not in result:
                logging.debug('No recordings for this match, skipping %s',
                              acoustidid)
                continue

            logging.debug('Processing %s', acoustidid)
            for recording in result['recordings']:
                score = result['score']
                if 'id' in recording:
                    rid = recording['id']
                if 'releases' not in recording:
                    logging.debug('Skipping acoustid record %s', recording)
                    continue

                for release in recording['releases']:
                    if 'artists' in release:
                        for artist in release['artists']:
                            if 'name' in artist:
                                albumartist = artist['name']
                            elif isinstance(artist, str):
                                albumartist = artist
                            if albumartist == 'Various Artists':
                                score = score - .10
                            elif albumartist and nowplaying.utils.normalize(
                                    albumartist) in completenstr:
                                score = score + .20

                    title = release['mediums'][0]['tracks'][0]['title']
                    if release.get('title'):
                        album = release['title']
                    else:
                        album = None
                    if title and nowplaying.utils.normalize(
                            title) in completenstr:
                        score = score + .10
                    artistlist = []
                    artistidlist = []
                    for trackartist in release['mediums'][0]['tracks'][0][
                            'artists']:
                        if 'name' in trackartist:
                            artistlist.append(trackartist['name'])
                            artistidlist.append(trackartist['id'])
                        elif isinstance(trackartist, str):
                            artistlist.append(trackartist)
                        if trackartist and artistnstr:
                            if nowplaying.utils.normalize(
                                    trackartist) == artistnstr:
                                score = score + .30
                            else:
                                score = score - .50
                        if trackartist and nowplaying.utils.normalize(
                                trackartist) in completenstr:
                            score = score + .10

                    artist = ' & '.join(artistlist)

                    logging.debug(
                        'weighted score = %s, rid = %s, title = %s, artist = %s album = %s',
                        score, rid, title, artist, album)

                    if score > lastscore:
                        newdata = {'acoustidid': acoustidid}
                        if artistlist:
                            newdata['artist'] = ' & '.join(artistlist)
                        if title:
                            newdata['title'] = title
                        if album:
                            newdata['album'] = album
                        if rid:
                            newdata['musicbrainzrecordingid'] = rid
                        if artistidlist:
                            newdata['musicbrainzartistid'] = artistidlist
                        lastscore = score

        for key, value in newdata.items():
            self.acoustidmd[key] = value

        logging.debug(
            'picked weighted score = %s, rid = %s, title = %s, artist = %s album = %s',
            lastscore, self.acoustidmd.get('musicbrainzrecordingid'),
            self.acoustidmd.get('title'), self.acoustidmd.get('artist'),
            self.acoustidmd.get('album'))

    def _configure_fpcalc(self, fpcalcexe=None):  # pylint: disable=too-many-return-statements
        ''' deal with all the potential issues of finding and running fpcalc '''

        if fpcalcexe and not os.environ.get("FPCALC"):
            os.environ.setdefault("FPCALC", fpcalcexe)
            os.environ["FPCALC"] = fpcalcexe

        try:
            fpcalcexe = os.environ["FPCALC"]
        except NameError:
            logging.error('fpcalc is not configured')
            return False

        if not fpcalcexe:
            logging.error('fpcalc is not configured')
            return False

        fpcalcexepath = pathlib.Path(fpcalcexe)

        if not fpcalcexepath.exists():
            logging.error('defined fpcalc [%s] does not exist.', fpcalcexe)
            return False

        if not fpcalcexepath.is_file():
            logging.error('defined fpcalc [%s] is not a file.', fpcalcexe)
            return False

        if sys.platform == 'win32':
            try:
                exts = [
                    ext.lower() for ext in os.environ["PATHEXT"].split(";")
                ]
                testex = '.' + fpcalcexepath.name.split('.')[1].lower()
                logging.debug('Checking %s against %s', testex, exts)
                if testex not in exts:
                    logging.error('defined fpcalc [%s] is not executable.',
                                  fpcalcexe)
                    return False
            except Exception as error:  # pylint: disable=broad-except
                logging.error('Testing fpcalc on windows hit: %s', error)
        elif not os.access(fpcalcexe, os.X_OK):
            logging.error('defined fpcalc [%s] is not executable.', fpcalcexe)
            return False

        self.fpcalcexe = fpcalcexe
        return True

    def recognize(self, metadata=None):  #pylint: disable=too-many-statements
        # we need to make sure we don't modify the passed
        # structure so do a deep copy here
        self.acoustidmd = copy.deepcopy(metadata)
        if not self.config.cparser.value('acoustidmb/enabled', type=bool):
            return None

        if not self.acoustidmd.get('musicbrainzrecordingid'):

            logging.debug(
                'No musicbrainzrecordingid in metadata, so use acoustid')
            if 'filename' not in metadata:
                logging.warning('No filename in metadata')
                return None

            if not self._configure_fpcalc(fpcalcexe=self.config.cparser.value(
                    'acoustidmb/fpcalcexe')):
                logging.error('fpcalc is not configured')
                return None

            apikey = self.config.cparser.value('acoustidmb/acoustidapikey')
            results = self._fetch_from_acoustid(apikey, metadata['filename'])
            if not results:
                logging.info(
                    'acoustid could not recognize %s. Will need to be tagged.',
                    metadata['filename'])
                return self.acoustidmd

            self._read_acoustid_tuples(metadata, results)

        if not self.acoustidmd.get('musicbrainzrecordingid'):
            logging.info(
                'acoustidmb: no musicbrainz rid %s. Returning everything else.',
                metadata['filename'])
            return self.acoustidmd

        if musicbrainzlookup := self.musicbrainz.recordingid(
                self.acoustidmd['musicbrainzrecordingid']):
            if self.acoustidmd.get(
                    'musicbrainzartistid') and musicbrainzlookup.get(
                        'musicbrainzartistid'):
                del musicbrainzlookup['musicbrainzartistid']
            self.acoustidmd.update(musicbrainzlookup)
        return self.acoustidmd

    def providerinfo(self):
        ''' return list of what is provided by this recognition system '''
        return self.musicbrainz.providerinfo()

    def connect_settingsui(self, qwidget):
        ''' connect m3u button to filename picker'''
        self.qwidget = qwidget
        qwidget.fpcalcexe_button.clicked.connect(self.on_fpcalcexe_button)
        qwidget.acoustid_checkbox.clicked.connect(self.on_acoustid_checkbox)

    def on_fpcalcexe_button(self):
        ''' filename button clicked action'''
        if self.qwidget.fpcalcexe_lineedit.text():
            startdir = os.path.dirname(self.qwidget.fpcalcexe_lineedit.text())
        else:
            startdir = QDir.homePath()
        dirname = QFileDialog.getOpenFileName(self.qwidget, 'Select fpcalc',
                                              startdir, 'fpcalc fpcalc.exe')
        if dirname and dirname[0]:
            self.qwidget.fpcalcexe_lineedit.setText(dirname[0])

    def on_acoustid_checkbox(self):
        ''' if acoustid is turned on, then musicbrainz must also be on '''
        if self.qwidget.acoustid_checkbox.isChecked():
            self.qwidget.musicbrainz_checkbox.setChecked(True)

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        if self.config.cparser.value('acoustidmb/enabled', type=bool):
            qwidget.acoustid_checkbox.setChecked(True)
        else:
            qwidget.acoustid_checkbox.setChecked(False)

        if self.config.cparser.value('musicbrainz/enabled', type=bool):
            qwidget.musicbrainz_checkbox.setChecked(True)
        else:
            qwidget.musicbrainz_checkbox.setChecked(False)
        qwidget.emailaddress_lineedit.setText(
            self.config.cparser.value('musicbrainz/emailaddress'))

        qwidget.apikey_lineedit.setText(
            self.config.cparser.value('acoustidmb/acoustidapikey'))

        qwidget.fpcalcexe_lineedit.setText(
            self.config.cparser.value('acoustidmb/fpcalcexe'))

        if self.config.cparser.value('acoustidmb/websites', type=bool):
            qwidget.websites_checkbox.setChecked(True)
        else:
            qwidget.websites_checkbox.setChecked(False)

        for website in [
                'bandcamp',
                'homepage',
                'lastfm',
                'musicbrainz',
                'discogs',
        ]:
            guiattr = getattr(qwidget, f'ws_{website}_checkbox')
            guiattr.setChecked(
                self.config.cparser.value(f'acoustidmb/{website}', type=bool))

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''
        if qwidget.acoustid_checkbox.isChecked(
        ) and not qwidget.apikey_lineedit.text():
            raise PluginVerifyError(
                'Acoustid enabled, but no API Key provided.')

        if qwidget.musicbrainz_checkbox.isChecked(
        ) and not qwidget.emailaddress_lineedit.text():
            raise PluginVerifyError(
                'Acoustid enabled, but no email address provided.')

        if qwidget.acoustid_checkbox.isChecked(
        ) and not qwidget.fpcalcexe_lineedit.text():
            raise PluginVerifyError(
                'Acoustid enabled, but no fpcalc binary provided.')

        if qwidget.acoustid_checkbox.isChecked(
        ) and qwidget.fpcalcexe_lineedit.text():
            fpcalcexe = qwidget.fpcalcexe_lineedit.text()
            if not self._configure_fpcalc(fpcalcexe=fpcalcexe):
                raise PluginVerifyError(
                    'Acoustid enabled, but fpcalc is not executable.')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('acoustidmb/enabled',
                                     qwidget.acoustid_checkbox.isChecked())
        self.config.cparser.setValue('musicbrainz/enabled',
                                     qwidget.musicbrainz_checkbox.isChecked())
        self.config.cparser.setValue('acoustidmb/acoustidapikey',
                                     qwidget.apikey_lineedit.text())
        self.config.cparser.setValue('musicbrainz/emailaddress',
                                     qwidget.emailaddress_lineedit.text())
        self.config.cparser.setValue('acoustidmb/fpcalcexe',
                                     qwidget.fpcalcexe_lineedit.text())

        self.config.cparser.setValue('acoustidmb/websites',
                                     qwidget.websites_checkbox.isChecked())

        for website in [
                'bandcamp',
                'homepage',
                'lastfm',
                'musicbrainz',
                'discogs',
        ]:
            guiattr = getattr(qwidget, f'ws_{website}_checkbox')
            self.config.cparser.setValue(f'acoustidmb/{website}',
                                         guiattr.isChecked())

    def defaults(self, qsettings):
        qsettings.setValue('acoustidmb/enabled', False)
        qsettings.setValue('acoustidmb/acoustidapikey', None)
        qsettings.setValue('acoustidmb/emailaddress', None)
        qsettings.setValue('acoustidmb/fpcalcexe', None)
        qsettings.setValue('acoustidmb/websites', False)

        for website in [
                'bandcamp',
                'homepage',
                'lastfm',
                'musicbrainz',
                'discogs',
        ]:
            qsettings.setValue(f'acoustidmb/{website}', False)
        qsettings.setValue('acoustidmb/homepage', True)


def main():
    ''' integration test '''
    filename = sys.argv[1]

    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names()
    # need to make sure config is initialized with something
    nowplaying.config.ConfigFile(bundledir=bundledir)
    plugin = Plugin()
    metadata = plugin.recognize({'filename': filename})
    if not metadata:
        print('No information')
        sys.exit(1)

    if 'coverimageraw' in metadata:
        print('got an image')
        del metadata['coverimageraw']
    print(metadata)


if __name__ == "__main__":
    main()
