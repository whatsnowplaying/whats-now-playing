#!/usr/bin/env python3
'''
   config file parsing/handling
'''

import logging
import os
import sys
import threading

# pylint: disable=no-name-in-module
from PyQt5.QtCore import QCoreApplication, QSettings, QStandardPaths, QThread


class ConfigFile:  # pylint: disable=too-many-instance-attributes
    ''' read and write to config.ini '''

    ## Qt doesn't appear to support re-entrant locks or mutexes so
    ## let's use boring old Python threading

    lock = threading.RLock()

    def __init__(self, bundledir=None, reset=False):

        logging.debug('attempting lock')
        ConfigFile.lock.acquire()
        logging.debug('locked')

        self.initialized = False
        self.templatedir = os.path.join(
            QStandardPaths.standardLocations(
                QStandardPaths.DocumentsLocation)[0],
            QCoreApplication.applicationName(), 'templates')
        self.bundledir = bundledir

        logging.info('Templates: %s', self.templatedir)
        logging.info('Bundle: %s', self.bundledir)

        self.libpath = os.path.join(
            QStandardPaths.standardLocations(QStandardPaths.MusicLocation)[0],
            "_Serato_")

        if sys.platform == "win32":
            self.qsettingsformat = QSettings.IniFormat
        else:
            self.qsettingsformat = QSettings.NativeFormat

        self.iconfile = self.find_icon_file()

        self.cparser = QSettings(self.qsettingsformat, QSettings.UserScope,
                                 QCoreApplication.organizationName(),
                                 QCoreApplication.applicationName())
        logging.info('configuration: %s', self.cparser.fileName())
        self.interval = float(10)
        self.delay = float(0)
        self.notif = False
        self.local = True
        self.mixmode = 'newest'
        self.paused = False
        self.httpenabled = False
        self.httpport = 8899
        self.url = None
        self.file = None
        self.txttemplate = os.path.join(self.templatedir, "basic.txt")
        self.httpenabled = False
        self.httpdir = None
        self.usinghttpdir = None
        self.htmltemplate = os.path.join(self.templatedir, "basic.htm")

        self.loglevel = 'DEBUG'

        # Tell Qt to match the above

        self.defaults()
        if reset:
            self.save()
        else:
            self.get()
        ConfigFile.lock.release()
        logging.debug('lock release')

    def reset(self):
        ''' forcibly go back to defaults '''
        logging.debug('by thread %u', QThread.currentThreadId())
        self.__init__(bundledir=self.bundledir, reset=True)

    def get(self):
        ''' refresh values '''

        logging.debug('attempting lock')
        ConfigFile.lock.acquire()
        logging.debug('locked')

        try:
            self.interval = self.cparser.value('settings/interval', type=float)
        except TypeError:
            pass

        try:
            self.loglevel = self.cparser.value('settings/loglevel')
        except TypeError:
            pass

        try:
            self.delay = self.cparser.value('settings/delay', type=float)
        except TypeError:
            pass

        try:
            self.notif = self.cparser.value('settings/notif', type=bool)
        except TypeError:
            pass

        try:
            self.local = self.cparser.value('serato/local', type=bool)
        except TypeError:
            pass

        self.libpath = self.cparser.value('serato/libpath')
        self.url = self.cparser.value('serato/url')
        if self.local:
            self.mixmode = self.cparser.value('serato/mixmode')
        else:
            self.mixmode = 'newest'
        self.file = self.cparser.value('textoutput/file')
        self.txttemplate = self.cparser.value('textoutput/txttemplate')

        try:
            self.httpenabled = self.cparser.value('weboutput/httpenabled',
                                                  type=bool)
        except TypeError:
            pass

        try:
            self.httpport = self.cparser.value('weboutput/httpport', type=int)
        except TypeError:
            pass

        self.httpdir = self.cparser.value('weboutput/httpdir')
        if self.httpdir and self.usinghttpdir is not self.httpdir:
            self.usinghttpdir = self.httpdir
        self.htmltemplate = self.cparser.value('weboutput/htmltemplate')

        try:
            self.initialized = self.cparser.value('settings/initialized',
                                                  type=bool)
        except TypeError:
            pass

        ConfigFile.lock.release()
        logging.debug('lock release')

    def defaults(self):
        ''' default values for things '''
        logging.debug('by thread %u', QThread.currentThreadId())

        settings = QSettings(self.qsettingsformat, QSettings.SystemScope,
                             QCoreApplication.organizationName(),
                             QCoreApplication.applicationName())

        settings.setValue('settings/delay', self.delay)
        settings.setValue('settings/handler', 'serato')
        settings.setValue('settings/initialized', False)
        settings.setValue('settings/interval', self.interval)
        settings.setValue('settings/loglevel', self.loglevel)
        settings.setValue('settings/notif', self.notif)
        settings.setValue('textoutput/file', self.file)
        settings.setValue('textoutput/txttemplate', self.txttemplate)
        settings.setValue('weboutput/htmltemplate', self.htmltemplate)
        settings.setValue('weboutput/httpdir', self.httpdir)
        settings.setValue('weboutput/httpenabled', self.httpenabled)
        settings.setValue('weboutput/httpport', self.httpport)

        settings.setValue('serato/libpath', self.libpath)
        settings.setValue('serato/local', self.local)
        settings.setValue('serato/mixmode', self.mixmode)
        settings.setValue('serato/url', self.url)

    # pylint: disable=too-many-locals, too-many-arguments
    def put(self, initialized, local, libpath, url, file, txttemplate,
            httpport, httpdir, httpenabled, htmltemplate, interval, delay,
            notif, loglevel):
        ''' Save the configuration file '''

        logging.debug('attempting lock')
        ConfigFile.lock.acquire()
        logging.debug('locked')

        self.delay = float(delay)
        self.file = file
        self.htmltemplate = htmltemplate
        self.httpdir = httpdir
        self.httpenabled = httpenabled
        self.httpport = int(httpport)
        self.initialized = initialized
        self.interval = float(interval)
        self.loglevel = loglevel
        self.notif = notif
        self.txttemplate = txttemplate
        self.usinghttpdir = self.httpdir

        # Serato

        self.libpath = libpath
        self.local = local
        self.url = url

        self.save()

        ConfigFile.lock.release()
        logging.debug('lock release')

    def save(self):
        ''' save the current set '''

        logging.debug('attempting lock')
        ConfigFile.lock.acquire()
        logging.debug('locked')

        self.cparser.setValue('settings/delay', self.delay)
        self.cparser.setValue('settings/handler', 'serato')
        self.cparser.setValue('settings/initialized', self.initialized)
        self.cparser.setValue('settings/interval', self.interval)
        self.cparser.setValue('settings/loglevel', self.loglevel)
        self.cparser.setValue('settings/notif', self.notif)
        self.cparser.setValue('textoutput/file', self.file)
        self.cparser.setValue('textoutput/txttemplate', self.txttemplate)
        self.cparser.setValue('weboutput/htmltemplate', self.htmltemplate)
        self.cparser.setValue('weboutput/httpdir', self.httpdir)
        self.cparser.setValue('weboutput/httpenabled', self.httpenabled)
        self.cparser.setValue('weboutput/httpport', self.httpport)

        self.cparser.setValue('serato/libpath', self.libpath)
        self.cparser.setValue('serato/local', self.local)
        if self.local:
            self.cparser.setValue('serato/mixmode', self.mixmode)
        self.cparser.setValue('serato/url', self.url)

        ConfigFile.lock.release()
        logging.debug('lock release')

    # pylint: disable=too-many-locals, too-many-arguments
    def setusinghttpdir(self, usinghttpdir):
        ''' Save the configuration file '''

        logging.debug('attempting lock')
        ConfigFile.lock.acquire()
        logging.debug('locked')
        logging.debug('setting the usinghttpdir to %s', usinghttpdir)
        self.usinghttpdir = usinghttpdir
        ConfigFile.lock.release()
        logging.debug('lock release')

    def find_icon_file(self):
        ''' try to find our icon '''

        for testdir in [
                self.bundledir,
                os.path.join(self.bundledir, 'bin'),
                os.path.join(self.bundledir, 'resources')
        ]:
            for testfilename in ['icon.ico', 'windows.ico']:
                testfile = os.path.join(testdir, testfilename)
                if os.path.exists(testfile):
                    logging.debug('iconfile at %s', testfile)
                    return testfile

        logging.error('Unable to find the icon file. Death only follows.')
        return None
