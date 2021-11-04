#!/usr/bin/env python3
# pylint: disable=invalid-name
''' Use ACRCloud to recognize the file '''

import json
import os
import pathlib
import string
import subprocess
import sys
import time

import logging
import logging.config
import logging.handlers

from PySide2.QtCore import QDir  # pylint: disable=no-name-in-module
from PySide2.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

import acoustid

import nowplaying.bootstrap
import nowplaying.config
from nowplaying.recognition import RecognitionPlugin
from nowplaying.exceptions import PluginVerifyError
import nowplaying.musicbrainz

import nowplaying.version


class Plugin(RecognitionPlugin):
    ''' handler for NowPlaying '''
    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.qwidget = None
        self.musicbrainz = nowplaying.musicbrainz.MusicBrainzHelper(
            self.config)
        self.wstrans = str.maketrans('', '',
                                     string.whitespace + string.punctuation)
        self.acoustidmd = {}
        self.fpcalcexe = None

    def _fetch_from_acoustid(self, apikey, filename):  # pylint: disable=no-self-use
        results = None
        fpcalc = os.environ.get('FPCALC', 'fpcalc')
        command = [fpcalc, '-json', "-length", '120', filename]
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
            logging.error('Exception: %s stderr: %s', error,
                          completedprocess.stderr)
            return None

        if not completedprocess or not completedprocess.stdout:
            return None

        data = json.loads(completedprocess.stdout.decode('utf-8'))

        try:
            counter = 0
            while counter < 3:
                results = acoustid.lookup(apikey,
                                          data['fingerprint'],
                                          data['duration'],
                                          meta=[
                                              'recordings', 'recordingids',
                                              'releases', 'tracks', 'usermeta'
                                          ])
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

    def _simplestring(self, mystr):
        if not mystr:
            return None
        if len(mystr) < 4:
            return 'THIS TEXT IS TOO SMALL SO IGNORE IT'
        return mystr.lower().translate(self.wstrans)

    def _read_acoustid_tuples(self, results):  # pylint: disable=too-many-branches, too-many-statements, too-many-locals
        fnstr = self._simplestring(self.acoustidmd['filename'])
        if 'artist' in self.acoustidmd and self.acoustidmd['artist']:
            fnstr = fnstr + self._simplestring(self.acoustidmd['artist'])
        if 'title' in self.acoustidmd and self.acoustidmd['title']:
            fnstr = fnstr + self._simplestring(self.acoustidmd['title'])

        lastscore = 0
        artistlist = []
        title = None
        rid = None

        logging.debug(results)

        for result in results:  # pylint: disable=too-many-nested-blocks
            acoustidid = result['id']
            score = result['score']
            if 'recordings' not in result:
                continue

            for recording in result['recordings']:
                score = result['score']
                if 'id' in recording:
                    rid = recording['id']
                if 'releases' not in recording:
                    logging.debug('Skipping acoustid record %s', recording)
                    continue

                releasecount = 0
                for release in recording['releases']:
                    releasecount += 1
                    if 'artists' in release:
                        for artist in release['artists']:
                            if 'name' in artist:
                                albumartist = artist['name']
                            elif isinstance(artist, str):
                                albumartist = artist
                            if albumartist == 'Various Artists':
                                score = score - .10
                            elif albumartist and self._simplestring(
                                    albumartist) in fnstr:
                                score = score + .20

                    title = release['mediums'][0]['tracks'][0]['title']
                    if title and self._simplestring(title) in fnstr:
                        score = score + .10
                    artistlist = []
                    for trackartist in release['mediums'][0]['tracks'][0][
                            'artists']:
                        if 'name' in trackartist:
                            artistlist.append(trackartist['name'])
                        elif isinstance(trackartist, str):
                            artistlist.append(trackartist)
                        if trackartist and self._simplestring(
                                trackartist) in fnstr:
                            score = score + .10

                    artist = ' & '.join(artistlist)

                score = score + (releasecount * 0.10)
                logging.debug(
                    'weighted score = %s, rid = %s, title = %s, artist = %s',
                    score, rid, title, artist)

                if score > lastscore:
                    self.acoustidmd['acoustidid'] = acoustidid
                    if artistlist:
                        self.acoustidmd['artist'] = ' & '.join(artistlist)
                    if title:
                        self.acoustidmd['title'] = title
                    if rid:
                        self.acoustidmd['musicbrainzrecordingid'] = rid
                    lastscore = score

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

    def recognize(self, metadata):  #pylint: disable=too-many-statements
        self.acoustidmd = metadata
        if not self.config.cparser.value('acoustidmb/enabled', type=bool):
            return None

        if 'musicbrainzrecordingid' not in self.acoustidmd:

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

            self._read_acoustid_tuples(results)

        if 'musicbrainzrecordingid' not in self.acoustidmd:
            logging.info(
                'acoustidmb: no musicbrainz rid %s. Returning everything else.',
                metadata['filename'])
            return self.acoustidmd

        musicbrainzlookup = self.musicbrainz.recordingid(
            self.acoustidmd['musicbrainzrecordingid'])
        if musicbrainzlookup:
            self.acoustidmd.update(musicbrainzlookup)
        return self.acoustidmd

    def providerinfo(self):  # pylint: disable=no-self-use
        ''' return list of what is provided by this recognition system '''
        return self.musicbrainz.providerinfo()

    def connect_settingsui(self, qwidget):
        ''' connect m3u button to filename picker'''
        self.qwidget = qwidget
        qwidget.fpcalcexe_button.clicked.connect(self.on_fpcalcexe_button)

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

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        if self.config.cparser.value('acoustidmb/enabled', type=bool):
            qwidget.acoustidmb_checkbox.setChecked(True)
        else:
            qwidget.acoustidmb_checkbox.setChecked(False)
        qwidget.apikey_lineedit.setText(
            self.config.cparser.value('acoustidmb/acoustidapikey'))
        qwidget.emailaddress_lineedit.setText(
            self.config.cparser.value('acoustidmb/emailaddress'))
        qwidget.fpcalcexe_lineedit.setText(
            self.config.cparser.value('acoustidmb/fpcalcexe'))

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''
        if qwidget.acoustidmb_checkbox.isChecked(
        ) and not qwidget.apikey_lineedit.text():
            raise PluginVerifyError(
                'Acoustid enabled, but no API Key provided.')

        if qwidget.acoustidmb_checkbox.isChecked(
        ) and not qwidget.emailaddress_lineedit.text():
            raise PluginVerifyError(
                'Acoustid enabled, but no email address provided.')

        if qwidget.acoustidmb_checkbox.isChecked(
        ) and not qwidget.fpcalcexe_lineedit.text():
            raise PluginVerifyError(
                'Acoustid enabled, but no fpcalc binary provided.')

        if qwidget.acoustidmb_checkbox.isChecked(
        ) and qwidget.fpcalcexe_lineedit.text():
            fpcalcexe = qwidget.fpcalcexe_lineedit.text()
            if not self._configure_fpcalc(fpcalcexe=fpcalcexe):
                raise PluginVerifyError(
                    'Acoustid enabled, but fpcalc is not executable.')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('acoustidmb/enabled',
                                     qwidget.acoustidmb_checkbox.isChecked())
        self.config.cparser.setValue('acoustidmb/acoustidapikey',
                                     qwidget.apikey_lineedit.text())
        self.config.cparser.setValue('acoustidmb/emailaddress',
                                     qwidget.emailaddress_lineedit.text())
        self.config.cparser.setValue('acoustidmb/fpcalcexe',
                                     qwidget.fpcalcexe_lineedit.text())

    def defaults(self, qsettings):
        qsettings.setValue('acoustidmb/enabled', False)
        qsettings.setValue('acoustidmb/acoustidapikey', None)
        qsettings.setValue('acoustidmb/emailaddress', None)
        qsettings.setValue('acoustidmb/fpcalcexe', None)


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
