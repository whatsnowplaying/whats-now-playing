#!/usr/bin/env python3
'''
   config file parsing/handling
'''

import logging
import os
import pathlib
import re
import ssl
import sys
import time

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.artistextras
import nowplaying.inputs
import nowplaying.pluginimporter
import nowplaying.recognition
import nowplaying.utils
import nowplaying.version  # pylint: disable=no-name-in-module,import-error


class ConfigFile:  # pylint: disable=too-many-instance-attributes, too-many-public-methods
    ''' read and write to config.ini '''

    BUNDLEDIR = None

    def __init__(  # pylint: disable=too-many-arguments
            self,
            bundledir=None,
            logpath=None,
            reset=False,
            testmode=False,
            beam=False):
        self.version = nowplaying.version.__VERSION__  #pylint: disable=no-member
        self.beam = beam
        self.testmode = testmode
        self.logpath = logpath
        self.basedir = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
            QCoreApplication.applicationName())
        self.initialized = False
        if logpath:
            self.logpath = pathlib.Path(logpath)
        else:
            self.logpath = self.basedir.joinpath('logs', 'debug.log')

        self.templatedir = self.basedir.joinpath('templates')

        if not ConfigFile.BUNDLEDIR and bundledir:
            ConfigFile.BUNDLEDIR = pathlib.Path(bundledir)

        logging.info('Logpath: %s', self.logpath)
        logging.info('Templates: %s', self.templatedir)
        logging.info('Bundle: %s', ConfigFile.BUNDLEDIR)
        logging.debug('SSL_CERT_FILE=%s', os.environ.get('SSL_CERT_FILE'))
        logging.debug('SSL CA FILE=%s', ssl.get_default_verify_paths().cafile)

        if sys.platform == "win32":
            self.qsettingsformat = QSettings.IniFormat
        else:
            self.qsettingsformat = QSettings.NativeFormat

        self.cparser = QSettings(self.qsettingsformat, QSettings.UserScope,
                                 QCoreApplication.organizationName(),
                                 QCoreApplication.applicationName())
        logging.info('configuration: %s', self.cparser.fileName())
        self.notif = False
        self.txttemplate = str(self.templatedir.joinpath("basic-plain.txt"))
        self.loglevel = 'DEBUG'

        self.plugins = {}
        self.pluginobjs = {}

        self._force_set_statics()

        self._initial_plugins()

        self.defaults()
        if reset:
            self.cparser.clear()
            self._force_set_statics()
            self.save()
        else:
            self.get()

        self.iconfile = self.find_icon_file()
        self.uidir = self.find_ui_file()
        self.lastloaddate = None
        self.setlistdir = None
        self.striprelist = []

    def _force_set_statics(self):
        ''' make sure these are always set '''
        if self.testmode:
            self.cparser.setValue('testmode/enabled', True)

        if self.beam:
            self.cparser.setValue('control/beam', True)

    def reset(self):
        ''' forcibly go back to defaults '''
        logging.debug('config reset')
        self.__init__(bundledir=ConfigFile.BUNDLEDIR, reset=True)  # pylint: disable=unnecessary-dunder-call

    def get(self):
        ''' refresh values '''

        self.cparser.sync()
        try:
            self.loglevel = self.cparser.value('settings/loglevel')
        except TypeError:
            pass

        try:
            self.notif = self.cparser.value('settings/notif', type=bool)
        except TypeError:
            pass

        self.txttemplate = self.cparser.value('textoutput/txttemplate', defaultValue=None)

        try:
            self.initialized = self.cparser.value('settings/initialized', type=bool)
        except TypeError:
            pass

    def validate_source(self, plugin):
        ''' verify the source input '''
        return self.plugins['inputs'].get(f'nowplaying.inputs.{plugin}')

    def defaults(self):
        ''' default values for things '''
        logging.debug('set defaults')

        settings = QSettings(self.qsettingsformat, QSettings.SystemScope,
                             QCoreApplication.organizationName(),
                             QCoreApplication.applicationName())

        settings.setValue('artistextras/enabled', False)
        for field in ['banners', 'logos', 'thumbnails']:
            settings.setValue(f'artistextras/{field}', 2)

        settings.setValue('artistextras/fanart', 10)
        settings.setValue('artistextras/processes', 5)
        settings.setValue('artistextras/cachesize', 5)
        settings.setValue('artistextras/fanartdelay', 8)
        settings.setValue('artistextras/coverfornofanart', True)
        settings.setValue('artistextras/coverfornologos', False)
        settings.setValue('artistextras/coverfornothumbs', True)

        settings.setValue('recognition/replacetitle', False)
        settings.setValue('recognition/replaceartist', False)

        settings.setValue('setlist/enabled', False)

        settings.setValue('settings/delay', '1.0')
        settings.setValue('settings/initialized', False)
        settings.setValue('settings/loglevel', self.loglevel)
        settings.setValue('settings/notif', self.notif)
        settings.setValue('settings/stripextras', False)

        settings.setValue('textoutput/file', None)
        settings.setValue('textoutput/txttemplate', self.txttemplate)
        settings.setValue('textoutput/clearonstartup', True)
        settings.setValue('textoutput/fileappend', False)

        settings.setValue('obsws/enabled', False)
        settings.setValue('obsws/host', 'localhost')
        settings.setValue('obsws/port', '4455')
        settings.setValue('obsws/secret', '')
        settings.setValue('obsws/source', '')
        settings.setValue('obsws/template', str(self.templatedir.joinpath("basic-plain.txt")))

        settings.setValue('weboutput/htmltemplate', str(self.templatedir.joinpath("basic-web.htm")))
        settings.setValue('weboutput/artistbannertemplate',
                          str(self.templatedir.joinpath("ws-artistbanner-nofade.htm")))
        settings.setValue('weboutput/artistlogotemplate',
                          str(self.templatedir.joinpath("ws-artistlogo-nofade.htm")))
        settings.setValue('weboutput/artistthumbtemplate',
                          str(self.templatedir.joinpath("ws-artistthumb-nofade.htm")))
        settings.setValue('weboutput/artistfanarttemplate',
                          str(self.templatedir.joinpath("ws-artistfanart-nofade.htm")))
        settings.setValue('weboutput/gifwordstemplate',
                          str(self.templatedir.joinpath("ws-gifwords-fade.htm")))
        settings.setValue('weboutput/requestertemplate',
                          str(self.templatedir.joinpath("ws-requests.htm")))
        settings.setValue('weboutput/httpenabled', True)
        settings.setValue('weboutput/httpport', '8899')
        settings.setValue('weboutput/once', True)

        settings.setValue('twitchbot/enabled', False)

        settings.setValue('quirks/pollingobserver', False)
        settings.setValue('quirks/filesubst', False)
        settings.setValue('quirks/slashmode', 'nochange')

        self._defaults_plugins(settings)

    def _initial_plugins(self):

        self.plugins['inputs'] = nowplaying.pluginimporter.import_plugins(nowplaying.inputs)
        if self.beam and self.plugins['inputs']['nowplaying.inputs.beam']:
            del self.plugins['inputs']['nowplaying.inputs.beam']
        self.pluginobjs['inputs'] = {}
        self.plugins['recognition'] = nowplaying.pluginimporter.import_plugins(
            nowplaying.recognition)
        self.pluginobjs['recognition'] = {}

        if not self.beam:
            self.plugins['artistextras'] = nowplaying.pluginimporter.import_plugins(
                nowplaying.artistextras)
            self.pluginobjs['artistextras'] = {}

    def _defaults_plugins(self, settings):
        ''' configure the defaults for plugins '''
        self.pluginobjs = {}
        for plugintype, plugtypelist in self.plugins.items():
            self.pluginobjs[plugintype] = {}
            removelist = []
            for key in plugtypelist:
                self.pluginobjs[plugintype][key] = self.plugins[plugintype][key].Plugin(
                    config=self, qsettings=settings)
                if self.testmode or self.pluginobjs[plugintype][key].available:
                    self.pluginobjs[plugintype][key].defaults(settings)
                else:
                    removelist.append(key)
            for key in removelist:
                del self.pluginobjs[plugintype][key]
                del self.plugins[plugintype][key]

    def plugins_connect_settingsui(self, qtwidgets, uihelp):
        ''' configure the defaults for plugins '''
        # qtwidgets = list of qtwidgets, identified as [plugintype_pluginname]
        for plugintype, plugtypelist in self.plugins.items():
            for key in plugtypelist:
                widgetkey = key.split('.')[-1]
                self.pluginobjs[plugintype][key].connect_settingsui(
                    qtwidgets[f'{plugintype}_{widgetkey}'], uihelp)

    def plugins_load_settingsui(self, qtwidgets):
        ''' configure the defaults for plugins '''
        for plugintype, plugtypelist in self.plugins.items():
            for key in plugtypelist:
                widgetkey = key.split('.')[-1]
                self.pluginobjs[plugintype][key].load_settingsui(
                    qtwidgets[f'{plugintype}_{widgetkey}'])

    def plugins_verify_settingsui(self, inputname, qtwidgets):
        ''' configure the defaults for plugins '''
        for plugintype, plugtypelist in self.plugins.items():
            for key in plugtypelist:
                widgetkey = key.split('.')[-1]
                if (widgetkey == inputname and plugintype == 'inputs') or (plugintype != 'inputs'):
                    self.pluginobjs[plugintype][key].verify_settingsui(
                        qtwidgets[f'{plugintype}_{widgetkey}'])

    def plugins_save_settingsui(self, qtwidgets):
        ''' configure the defaults for input plugins '''
        for plugintype, plugtypelist in self.plugins.items():
            for key in plugtypelist:
                widgetkey = key.split('.')[-1]
                self.pluginobjs[plugintype][key].save_settingsui(
                    qtwidgets[f'{plugintype}_{widgetkey}'])

    def plugins_description(self, plugintype, plugin, qtwidget):
        ''' configure the defaults for input plugins '''
        self.pluginobjs[plugintype][f'nowplaying.{plugintype}.{plugin}'].desc_settingsui(qtwidget)

    # pylint: disable=too-many-arguments
    def put(self, initialized, notif, loglevel):
        ''' Save the configuration file '''

        self.initialized = initialized
        self.loglevel = loglevel
        self.notif = notif

        self.save()

    def save(self):
        ''' save the current set '''

        self.cparser.setValue('settings/initialized', self.initialized)
        self.cparser.setValue('settings/lastsavedate', time.strftime("%Y%m%d%H%M%S"))
        self.cparser.setValue('settings/loglevel', self.loglevel)
        self.cparser.setValue('settings/notif', self.notif)

        self.cparser.sync()

    def find_icon_file(self):
        ''' try to find our icon '''

        if not ConfigFile.BUNDLEDIR:
            logging.error('bundledir not set in config')
            return None

        for testdir in [
                ConfigFile.BUNDLEDIR,
                ConfigFile.BUNDLEDIR.joinpath('bin'),
                ConfigFile.BUNDLEDIR.joinpath('resources')
        ]:
            for testfilename in ['icon.ico', 'windows.ico']:
                testfile = testdir.joinpath(testfilename)
                if testfile.exists():
                    logging.debug('iconfile at %s', testfile)
                    return testfile

        if not self.testmode:
            self.testmode = self.cparser.value('testmode/enabled')

        if not self.testmode:
            logging.error('Unable to find the icon file. Death only follows.')
        return None

    def find_ui_file(self):
        ''' try to find our icon '''

        if not ConfigFile.BUNDLEDIR:
            logging.error('bundledir not set in config')
            return None

        for testdir in [
                ConfigFile.BUNDLEDIR,
                ConfigFile.BUNDLEDIR.joinpath('bin'),
                ConfigFile.BUNDLEDIR.joinpath('resources')
        ]:
            testfile = testdir.joinpath('settings_ui.ui')
            if testfile.exists():
                logging.debug('ui file at %s', testfile)
                return testdir

        if not self.testmode:
            self.testmode = self.cparser.value('testmode/enabled')

        if not self.testmode:
            logging.error('Unable to find the ui dir. Death only follows.')
        return None

    def pause(self):
        ''' Pause system '''
        self.cparser.setValue('control/paused', True)
        logging.warning('NowPlaying is currently paused.')

    def unpause(self):
        ''' unpause system '''
        self.cparser.setValue('control/paused', False)
        logging.warning('NowPlaying is no longer paused.')

    def getpause(self):
        ''' Get the pause status '''
        return self.cparser.value('control/paused', type=bool)

    def validmixmodes(self):
        ''' get valid mixmodes '''
        plugin = self.cparser.value('settings/input')
        inputplugin = self.plugins['inputs'][f'nowplaying.inputs.{plugin}'].Plugin(config=self)
        return inputplugin.validmixmodes()

    def setmixmode(self, mixmode):
        ''' set the mixmode by calling the plugin '''

        plugin = self.cparser.value('settings/input')
        inputplugin = self.plugins['inputs'][f'nowplaying.inputs.{plugin}'].Plugin(config=self)
        return inputplugin.setmixmode(mixmode)

    def getmixmode(self):
        ''' get current mix mode '''
        plugin = self.cparser.value('settings/input')
        inputplugin = self.plugins['inputs'][f'nowplaying.inputs.{plugin}'].Plugin(config=self)
        return inputplugin.getmixmode()

    @staticmethod
    def getbundledir():
        ''' get the bundle dir '''
        return ConfigFile.BUNDLEDIR

    def getsetlistdir(self):
        ''' get the setlist directory '''
        if not self.setlistdir:
            self.setlistdir = os.path.join(
                QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
                QCoreApplication.applicationName(), 'setlists')
        return self.setlistdir

    def getregexlist(self):
        ''' get the regex title filter '''
        if not self.striprelist or self.lastloaddate < self.cparser.value('settings/lastsavedate'):
            try:
                self.striprelist = [
                    re.compile(self.cparser.value(configitem))
                    for configitem in self.cparser.allKeys() if 'regex_filter/' in configitem
                ]
                self.lastloaddate = self.cparser.value('settings/lastsavedate')
            except re.error as error:
                logging.error('Filter error with \'%s\': %s', error.pattern, error.msg)
        return self.striprelist
