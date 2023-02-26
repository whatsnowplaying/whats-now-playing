#!/usr/bin/env python3
''' all things upgrade '''

import copy
import hashlib
import json
import logging
import pathlib
import re
import shutil
import sys
import time
import traceback
import webbrowser

import requests

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QDialog, QMessageBox, QDialogButtonBox, QVBoxLayout, QLabel  # pylint: disable=no-name-in-module

import nowplaying.trackrequests
import nowplaying.twitch.chat
import nowplaying.version

# regex that support's git describe --tags as well as many semver-type strings
# based upon the now deprecated distutils version code
VERSION_REGEX = re.compile(
    r'''
        ^
        (?P<major>0|[1-9]\d*)
        \.
        (?P<minor>0|[1-9]\d*)
        \.
        (?P<micro>0|[1-9]\d*)
        (?:-rc(?P<rc>(?:0|\d*)))?
        (?:[-+](?P<commitnum>
            (?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)
            (?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*
        ))?
        (?:-(?P<identifier>
            [0-9a-zA-Z-]+
            (?:\.[0-9a-zA-Z-]+)*
        ))?
        $
        ''',
    re.VERBOSE,
)


class Version:
    ''' process a version'''

    def __init__(self, version):
        self.textversion = version
        vermatch = VERSION_REGEX.match(version.replace('.dirty', ''))
        if not vermatch:
            raise ValueError
        self.pre = False
        self.chunk = vermatch.groupdict()
        self._calculate()

    def _calculate(self):
        olddict = copy.copy(self.chunk)
        for key, value in olddict.items():
            if value and value.isdigit():
                self.chunk[key] = int(value)

        if self.chunk.get('rc') or self.chunk.get('commitnum'):
            self.pre = True

    def is_prerelease(self):
        ''' if a pre-release, return True '''
        return self.pre

    def __str__(self):
        return self.textversion

    def __lt__(self, other):
        ''' version compare
            do the easy stuff, major > minor > micro '''
        for key in ["major", "minor", "micro"]:
            if self.chunk.get(key) == other.chunk.get(key):
                continue
            return self.chunk.get(key) < other.chunk.get(key)

        # rc < no rc
        if self.chunk.get('rc') and not other.chunk.get('rc'):
            return True

        if (self.chunk.get('rc') and other.chunk.get('rc')
                and self.chunk.get('rc') != other.chunk.get('rc')):
            return self.chunk.get('rc') < other.chunk.get('rc')

        # but commitnum > no commitnum at this point
        if self.chunk.get('commitnum') and not other.chunk.get('commitnum'):
            return False

        if (self.chunk.get('commitnum') and other.chunk.get('commitnum') and
                self.chunk.get('commitnum') != other.chunk.get('commitnum')):
            return self.chunk.get('commitnum') < other.chunk.get('commitnum')

        return False


class UpgradeBinary:
    ''' routines to determine if the binary is out of date '''

    def __init__(self, testmode=False):
        self.myversion = Version(nowplaying.version.get_versions()['version'])
        self.prerelease = Version('0.0.0-rc0')
        self.stable = Version('0.0.0')
        self.predata = None
        self.stabledata = None
        if not testmode:
            self.get_versions()

    def get_versions(self, testdata=None):
        ''' ask github about current versions '''
        try:
            if not testdata:
                req = requests.get(
                    'https://api.github.com/repos/whatsnowplaying/whats-now-playing/releases',
                    timeout=100)
                req.raise_for_status()
                jsonreldata = req.json()
            else:
                jsonreldata = testdata

            for rel in jsonreldata:
                if not isinstance(rel, dict):
                    logging.error(rel)
                    break

                if rel.get('draft'):
                    continue

                tagname = Version(rel['tag_name'])
                if rel.get('prerelease'):
                    if self.prerelease < tagname:
                        self.prerelease = tagname
                        self.predata = rel
                elif self.stable < tagname:
                    self.stable = tagname
                    self.stabledata = rel

            if self.stable > self.prerelease:
                self.prerelease = self.stable
                self.predata = self.stabledata

        except:  # pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)

    def get_upgrade_data(self):
        ''' compare our version to fetched version data '''
        if self.myversion.is_prerelease():
            if self.myversion < self.prerelease:
                return self.predata
        elif self.myversion < self.stable:
            return self.stabledata
        return None

    def ask_ugprade(self):
        ''' ask user about upgrade '''
        data = self.get_upgrade_data()
        if not data:
            return

        dialog = UpgradeDialog()
        dialog.fill_it_in(self.myversion, data['tag_name'])
        if dialog.exec():
            webbrowser.open(data['html_url'])
            logging.info('User wants to upgrade; exiting')
            sys.exit(0)


class UpgradeDialog(QDialog):  # pylint: disable=too-few-public-methods
    ''' Qt Dialog for asking the user to ugprade '''

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Version Available!")
        dialogbuttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        self.buttonbox = QDialogButtonBox(dialogbuttons)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)
        self.layout = QVBoxLayout()

    def fill_it_in(self, oldversion, newversion):
        ''' fill in the upgrade versions and message '''
        messages = [
            f'Your version: {oldversion}', f'New version: {newversion}',
            'Download new version?'
        ]

        for msg in messages:
            message = QLabel(msg)
            self.layout.addWidget(message)
        self.layout.addWidget(self.buttonbox)
        self.setLayout(self.layout)


class UpgradeConfig:
    ''' methods to upgrade from old configs to new configs '''

    def __init__(self, testdir=None):

        if sys.platform == "win32":
            self.qsettingsformat = QSettings.IniFormat
        else:
            self.qsettingsformat = QSettings.NativeFormat

        self.testdir = testdir
        self.upgrade()

    def _getconfig(self):
        return QSettings(self.qsettingsformat, QSettings.UserScope,
                         QCoreApplication.organizationName(),
                         QCoreApplication.applicationName())

    def backup_config(self):
        ''' back up the old config '''
        config = self._getconfig()
        source = config.fileName()
        datestr = time.strftime("%Y%m%d-%H%M%S")
        if self.testdir:
            docpath = self.testdir
        else:  # pragma: no cover
            docpath = QStandardPaths.standardLocations(
                QStandardPaths.DocumentsLocation)[0]
        backupdir = pathlib.Path(docpath).joinpath(
            QCoreApplication.applicationName(), 'configbackup')

        logging.info('Making a backup of config prior to upgrade: %s',
                     backupdir)
        try:
            pathlib.Path(backupdir).mkdir(parents=True, exist_ok=True)
            backup = backupdir.joinpath(f'{datestr}-config.bak')
            shutil.copyfile(source, backup)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('Failed to make a backup: %s', error)
            sys.exit(0)

    def upgrade(self):
        ''' variable re-mapping '''
        config = self._getconfig()
        config.sync()

        mapping = {
            'acoustidmb/emailaddress': 'musicbrainz/emailaddress',
            'acoustidmb/enabled': 'musicbrainz/enabled',
            'twitchbot/enabled': 'twitchbot/chat',
            'twitchbot/token': 'twitchbot/chattoken',
        }
        sourcepath = pathlib.Path(config.fileName())

        if not sourcepath.exists():
            logging.debug('new install!')
            return

        # these got moved in 3.1.0
        npsqldb = pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.CacheLocation)[0]).joinpath('npsql.db')
        npsqldb.unlink(missing_ok=True)
        webdb = pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.CacheLocation)[0]).joinpath('web.db')
        webdb.unlink(missing_ok=True)

        oldversstr = config.value('settings/configversion',
                                  defaultValue='3.0.0')

        thisverstr = nowplaying.version.get_versions()['version']
        oldversion = Version(oldversstr)
        thisversion = Version(thisverstr)

        if oldversion == thisversion:
            logging.debug('equivalent config file versions')
            return

        # only save requests if the versions are the same
        # otherwise nuke it
        nowplaying.trackrequests.Requests(upgrade=True)

        if oldversion > thisversion:
            logging.warning('Running an older version with a newer config...')
            return

        self.backup_config()

        logging.info('Upgrading config from %s to %s', oldversstr, thisverstr)

        rawconfig = QSettings(str(sourcepath), self.qsettingsformat)

        if oldversstr in {'3.1.0', '3.1.1'}:
            upgrade_filters(config=rawconfig)

        if int(oldversstr[0]) < 4 and config.value('settings/input') == 'm3u':
            upgrade_m3u(config=rawconfig, testdir=self.testdir)

        for oldkey, newkey in mapping.items():
            logging.debug('processing %s - %s', oldkey, newkey)
            try:
                newval = rawconfig.value(newkey)
            except:  # pylint: disable=bare-except
                pass

            if newval:
                logging.debug('%s already has value %s', newkey, newval)
                continue

            try:
                oldval = rawconfig.value(oldkey)
            except:  # pylint: disable=bare-except
                logging.debug('%s vs %s: skipped, no new value', oldkey,
                              newkey)
                continue

            if oldval:
                logging.debug('Setting %s from %s', newkey, oldkey)
                config.setValue(newkey, oldval)
            else:
                logging.debug('%s does not exist', oldkey)

        config.setValue('settings/configversion', thisverstr)
        config.sync()


class UpgradeTemplates():
    ''' Upgrade templates '''

    def __init__(self, bundledir=None, testdir=None):
        self.bundledir = pathlib.Path(bundledir)
        self.apptemplatedir = self.bundledir.joinpath('templates')
        self.testdir = testdir
        if testdir:
            self.usertemplatedir = pathlib.Path(testdir).joinpath(
                QCoreApplication.applicationName(), 'templates')
        else:  # pragma: no cover
            self.usertemplatedir = pathlib.Path(
                QStandardPaths.standardLocations(
                    QStandardPaths.DocumentsLocation)[0],
                QCoreApplication.applicationName()).joinpath('templates')
        self.usertemplatedir.mkdir(parents=True, exist_ok=True)
        self.alert = False
        self.copied = []
        self.oldshas = {}

        self.setup_templates()

        if self.alert and not self.testdir:
            msgbox = QMessageBox()
            msgbox.setText('Updated templates have been placed.')
            msgbox.setModal(True)
            msgbox.setWindowTitle("What's Now Playing Templates")
            msgbox.show()
            msgbox.exec()

    def preload(self):
        ''' preload the known hashes for bundled templates '''
        shafile = self.bundledir.joinpath('resources', 'updateshas.json')
        if shafile.exists():
            with open(shafile, encoding='utf-8') as fhin:
                self.oldshas = json.loads(fhin.read())

    def check_preload(self, filename, userhash):
        ''' check if the given file matches a known hash '''
        found = None
        hexdigest = None
        if filename in self.oldshas:
            for version, hexdigest in self.oldshas[filename].items():
                if userhash == hexdigest:
                    found = version
        logging.debug('filename = %s, found = %s userhash = %s hexdigest = %s',
                      filename, found, userhash, hexdigest)
        return found

    def setup_templates(self):
        ''' copy templates to either existing or as a new one '''

        self.preload()

        for apppath in pathlib.Path(self.apptemplatedir).iterdir():
            userpath = self.usertemplatedir.joinpath(apppath.name)

            if not userpath.exists():
                shutil.copyfile(apppath, userpath)
                logging.info('Added %s to %s', apppath.name,
                             self.usertemplatedir)
                continue

            apphash = checksum(apppath)
            userhash = checksum(userpath)

            if apphash == userhash:
                continue

            if version := self.check_preload(apppath.name, userhash):
                userpath.unlink()
                shutil.copyfile(apppath, userpath)
                logging.info('Replaced %s from %s with %s', apppath.name,
                             version, self.usertemplatedir)
                continue

            destpath = str(userpath).replace('.txt', '.new')
            destpath = pathlib.Path(destpath.replace('.htm', '.new'))
            if destpath.exists():
                userhash = checksum(destpath)
                if apphash == userhash:
                    continue
                destpath.unlink()

            self.alert = True
            logging.info('New version of %s copied to %s', apppath.name,
                         destpath)
            shutil.copyfile(apppath, destpath)
            self.copied.append(apppath.name)


def upgrade_m3u(config, testdir=None):
    ''' convert m3u to virtualdj and maybe other stuff in the future? '''
    if 'VirtualDJ' in config.value('m3u/directory'):
        historypath = pathlib.Path(config.value('m3u/directory'))
        config.setValue('virtualdj/history', config.value('m3u/directory'))
        config.setValue('virtualdj/playlists',
                        str(historypath.parent.joinpath('Playlists')))
        config.setValue('settings/input', 'virtualdj')
        if not testdir:
            msgbox = QMessageBox()
            msgbox.setText('M3U has been converted to VirtualDJ.')
            msgbox.show()
            msgbox.exec()


def upgrade_filters(config):
    ''' setup the recommended filters '''
    if config.value('settings/stripextras',
                    type=bool) and not config.value('regex_filter/0'):
        stripworldlist = ['clean', 'dirty', 'explicit', 'official music video']
        joinlist = '|'.join(stripworldlist)
        config.setValue('regex_filter/0', f' \\((?i:{joinlist})\\)')
        config.setValue('regex_filter/1', f' - (?i:{joinlist}$)')
        config.setValue('regex_filter/2', f' \\[(?i:{joinlist})\\]')


def checksum(filename):
    ''' generate sha512 . See also build-update-sha.py '''
    hashfunc = hashlib.sha512()
    with open(filename, 'rb') as fileh:
        while chunk := fileh.read(128 * hashfunc.block_size):
            hashfunc.update(chunk)
    return hashfunc.hexdigest()


def upgrade(bundledir=None):
    ''' do an upgrade of an existing install '''
    logging.debug('Called upgrade')

    try:
        UpgradeBinary().ask_ugprade()
    except Exception as error:  # pylint: disable=broad-except
        logging.error(error)

    myupgrade = UpgradeConfig()  #pylint: disable=unused-variable
    myupgrade = UpgradeTemplates(bundledir=bundledir)
