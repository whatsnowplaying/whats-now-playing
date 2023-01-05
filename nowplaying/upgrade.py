#!/usr/bin/env python3
''' all things upgrade '''

import hashlib
import json
import logging
import pathlib
import shutil
import sys
import time

import pkg_resources

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QMessageBox  # pylint: disable=no-name-in-module

import nowplaying.twitch.chat
import nowplaying.version


class UpgradeConfig:
    ''' methods to upgrade from old configs to new configs '''

    def __init__(self, testdir=None):

        if sys.platform == "win32":
            self.qsettingsformat = QSettings.IniFormat
        else:
            self.qsettingsformat = QSettings.NativeFormat

        self.testdir = testdir
        self.copy_old_2_new()
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

    def copy_old_2_new(self):
        ''' copy old config file name to new config file name '''

        othersettings = QSettings(self.qsettingsformat, QSettings.UserScope,
                                  'com.github.em1ran', 'NowPlaying')
        othersettingsfn = pathlib.Path(othersettings.fileName())
        if not othersettingsfn.exists():
            return

        config = self._getconfig()
        configfn = pathlib.Path(config.fileName())
        if configfn.exists():
            logging.debug(
                'new style config %s already exists; skipping em1ran copy',
                configfn)
            return

        logging.debug(
            'Upgrading from old em1ran config to whatsnowplaying config')
        configfn.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(othersettingsfn, configfn)
        config.sync()

    def upgrade(self):
        ''' variable re-mapping '''
        config = self._getconfig()
        config.sync()

        mapping = {
            'settings/interval': 'serato/interval',
            'settings/handler': 'settings/input',
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

        try:
            oldversstr = config.value('settings/configversion',
                                      defaultValue='2.0.0')
        except TypeError:
            oldversstr = '2.0.0'

        thisverstr = nowplaying.version.get_versions()['version']
        oldversion = pkg_resources.parse_version(oldversstr)
        thisversion = pkg_resources.parse_version(thisverstr)

        if oldversion == thisversion:
            logging.debug('equivalent config file versions')
            return

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
                logging.debug('Setting %s to %s', newkey, oldval)
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
    myupgrade = UpgradeConfig()  #pylint: disable=unused-variable
    myupgrade = UpgradeTemplates(bundledir=bundledir)
