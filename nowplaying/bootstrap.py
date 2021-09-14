#!/usr/bin/env python3
''' bootstrap the app '''

import hashlib
import json
import logging
import logging.handlers
import os
import pathlib
import shutil
import sys
import time

import pkg_resources

from PySide2.QtCore import QCoreApplication, QSettings, QStandardPaths, Qt  # pylint: disable=no-name-in-module

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
        backupdir = os.path.join(docpath, QCoreApplication.applicationName(),
                                 'configbackup')

        logging.info('Making a backup of config prior to upgrade: %s',
                     backupdir)
        try:
            pathlib.Path(backupdir).mkdir(parents=True, exist_ok=True)
            backup = os.path.join(backupdir, f'{datestr}-config.bak')
            shutil.copyfile(source, backup)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('Failed to make a backup: %s', error)
            sys.exit(0)

    def copy_old_2_new(self):
        ''' copy old config file name to new config file name '''

        othersettings = QSettings(self.qsettingsformat, QSettings.UserScope,
                                  'com.github.em1ran', 'NowPlaying')
        if not os.path.exists(othersettings.fileName()):
            return

        config = self._getconfig()
        if os.path.exists(config.fileName()):
            logging.debug(
                'new style config %s already exists; skipping em1ran copy',
                config.fileName())
            return

        logging.debug(
            'Upgrading from old em1ran config to whatsnowplaying config')
        pathlib.Path(os.path.dirname(config.fileName())).mkdir(parents=True,
                                                               exist_ok=True)
        shutil.copyfile(othersettings.fileName(), config.fileName())
        config.sync()

    def upgrade(self):
        ''' variable re-mapping '''
        config = self._getconfig()
        config.sync()

        mapping = {
            'settings/interval': 'serato/interval',
            'settings/handler': 'settings/input'
        }
        source = config.fileName()

        if not os.path.exists(source):
            logging.debug('new install!')
            return

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

        rawconfig = QSettings(source, self.qsettingsformat)

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
        self.bundledir = bundledir
        self.apptemplatedir = os.path.join(self.bundledir, 'templates')
        if testdir:
            self.usertemplatedir = os.path.join(
                testdir, QCoreApplication.applicationName(), 'templates')
        else:  # pragma: no cover
            self.usertemplatedir = os.path.join(
                QStandardPaths.standardLocations(
                    QStandardPaths.DocumentsLocation)[0],
                QCoreApplication.applicationName(), 'templates')
        pathlib.Path(self.usertemplatedir).mkdir(parents=True, exist_ok=True)
        self.alert = False
        self.copied = []
        self.oldshas = {}

        self.setup_templates()

        if self.alert:
            self.trigger_alert()

    def checksum(self, filename):  # pylint: disable=no-self-use
        ''' generate sha512 . See also build-update-sha.py '''
        hashfunc = hashlib.sha512()
        with open(filename, 'rb') as fileh:
            while chunk := fileh.read(128 * hashfunc.block_size):
                hashfunc.update(chunk)
        return hashfunc.hexdigest()

    def preload(self):
        ''' preload the known hashes for bundled templates '''
        shafile = os.path.join(self.bundledir, 'resources', 'updateshas.json')
        if os.path.exists(shafile):
            with open(shafile, 'r') as fhin:
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
            filename = os.path.basename(apppath)
            userpath = os.path.join(self.usertemplatedir, filename)

            if not os.path.exists(userpath):
                shutil.copyfile(apppath, userpath)
                logging.info('Added %s to %s', filename, self.usertemplatedir)
                continue

            apphash = self.checksum(apppath)
            userhash = self.checksum(userpath)

            if apphash == userhash:
                continue

            version = self.check_preload(filename, userhash)
            if version:
                os.unlink(userpath)
                shutil.copyfile(apppath, userpath)
                logging.info('Replaced %s from %s with %s', filename, version,
                             self.usertemplatedir)
                continue

            destpath = str(userpath).replace('.txt', '.new')
            destpath = destpath.replace('.htm', '.new')
            if os.path.exists(destpath):
                userhash = self.checksum(destpath)
                if apphash == userhash:
                    continue
                os.unlink(destpath)

            self.alert = True
            logging.info('New version of %s copied to %s', filename, destpath)
            shutil.copyfile(apppath, destpath)
            self.copied.append(filename)

    def trigger_alert(self):  # pylint: disable=no-self-use
        ''' throw a pop-up to let the user know '''
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat
        cparser = QSettings(qsettingsformat, QSettings.UserScope,
                            QCoreApplication.organizationName(),
                            QCoreApplication.applicationName())
        cparser.setValue('settings/newtemplates', True)


def set_qt_names(app=None, appname='NowPlaying'):
    ''' bootstrap Qt for configuration '''
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    if not app:
        app = QCoreApplication.instance()
    if not app:
        app = QCoreApplication()
    app.setOrganizationDomain('com.github.whatsnowplaying')
    app.setOrganizationName('whatsnowplaying')
    app.setApplicationName(appname)


def upgrade(bundledir=None):
    ''' do an upgrade of an existing install '''
    logging.debug('Called upgrade')
    myupgrade = UpgradeConfig()  #pylint: disable=unused-variable
    myupgrade = UpgradeTemplates(bundledir=bundledir)


def setuplogging(logpath=None):
    ''' configure logging '''
    besuretorotate = False

    if os.path.exists(logpath):
        besuretorotate = True

    logfhandler = logging.handlers.RotatingFileHandler(filename=logpath,
                                                       backupCount=10,
                                                       encoding='utf-8')
    if besuretorotate:
        logfhandler.doRollover()

    # this loglevel should eventually be tied into config
    # but for now, hard-set at info
    logging.basicConfig(
        format=
        '%(asctime)s %(process)d %(threadName)s %(module)s:%(funcName)s:%(lineno)d '
        + '%(levelname)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z',
        handlers=[logfhandler],
        level=logging.DEBUG)
    logging.info('starting up v%s',
                 nowplaying.version.get_versions()['version'])
