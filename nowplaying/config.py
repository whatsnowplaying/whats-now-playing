#!/usr/bin/env python3
'''
   config file parsing/handling
'''

import logging
import os
import re
import sys
import time

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.artistextras
import nowplaying.inputs
import nowplaying.recognition
import nowplaying.utils
import nowplaying.version


class ConfigFile:  # pylint: disable=too-many-instance-attributes, too-many-public-methods
    ''' read and write to config.ini '''

    ## Qt doesn't appear to support re-entrant locks or mutexes so
    ## let's use boring old Python threading

    BUNDLEDIR = None
    PAUSED = False

    def __init__(self,
                 bundledir=None,
                 logpath=None,
                 reset=False,
                 testmode=False):

        self.testmode = testmode
        self.logpath = logpath
        self.initialized = False
        if logpath:
            self.logpath = logpath
        else:
            self.logpath = os.path.join(
                QStandardPaths.standardLocations(
                    QStandardPaths.DocumentsLocation)[0],
                QCoreApplication.applicationName(), 'logs', 'debug.log')

        self.templatedir = os.path.join(
            QStandardPaths.standardLocations(
                QStandardPaths.DocumentsLocation)[0],
            QCoreApplication.applicationName(), 'templates')

        if not ConfigFile.BUNDLEDIR and bundledir:
            ConfigFile.BUNDLEDIR = bundledir

        logging.info('Templates: %s', self.templatedir)
        logging.info('Bundle: %s', ConfigFile.BUNDLEDIR)

        if sys.platform == "win32":
            self.qsettingsformat = QSettings.IniFormat
        else:
            self.qsettingsformat = QSettings.NativeFormat

        self.cparser = QSettings(self.qsettingsformat, QSettings.UserScope,
                                 QCoreApplication.organizationName(),
                                 QCoreApplication.applicationName())
        logging.info('configuration: %s', self.cparser.fileName())
        self.notif = False
        ConfigFile.PAUSED = False
        self.file = None
        self.txttemplate = os.path.join(self.templatedir, "basic-plain.txt")
        self.loglevel = 'DEBUG'

        self.plugins = {}
        self.pluginobjs = {}

        if self.testmode:
            self.cparser.setValue('testmode/enabled', True)

        self._initial_plugins()

        self.defaults()
        if reset:
            self.cparser.clear()
            self.save()
        else:
            self.get()

        self.iconfile = self.find_icon_file()
        self.uidir = self.find_ui_file()
        self.lastloaddate = None
        self.striprelist = []

    def reset(self):
        ''' forcibly go back to defaults '''
        logging.debug('config reset')
        self.__init__(bundledir=ConfigFile.BUNDLEDIR, reset=True)

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

        self.file = self.cparser.value('textoutput/file')
        self.txttemplate = self.cparser.value('textoutput/txttemplate')

        try:
            self.initialized = self.cparser.value('settings/initialized',
                                                  type=bool)
        except TypeError:
            pass

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
        settings.setValue('settings/input', 'serato')
        settings.setValue('settings/loglevel', self.loglevel)
        settings.setValue('settings/notif', self.notif)
        settings.setValue('settings/stripextras', False)

        settings.setValue('textoutput/file', self.file)
        settings.setValue('textoutput/txttemplate', self.txttemplate)

        settings.setValue('obsws/enabled', False)
        settings.setValue('obsws/freetype2', True)
        settings.setValue('obsws/host', 'localhost')
        settings.setValue('obsws/port', '4444')
        settings.setValue('obsws/secret', '')
        settings.setValue('obsws/source', '')
        settings.setValue('obsws/template',
                          os.path.join(self.templatedir, "basic-plain.txt"))

        settings.setValue('weboutput/htmltemplate',
                          os.path.join(self.templatedir, "basic-web.htm"))
        settings.setValue(
            'weboutput/artistbannertemplate',
            os.path.join(self.templatedir, "ws-artistbanner-nofade.htm"))
        settings.setValue(
            'weboutput/artistlogotemplate',
            os.path.join(self.templatedir, "ws-artistlogo-nofade.htm"))
        settings.setValue(
            'weboutput/artistthumbtemplate',
            os.path.join(self.templatedir, "ws-artistthumb-nofade.htm"))
        settings.setValue(
            'weboutput/artistfanarttemplate',
            os.path.join(self.templatedir, "ws-artistfanart-nofade.htm"))
        settings.setValue('weboutput/httpenabled', False)
        settings.setValue('weboutput/httpport', '8899')
        settings.setValue('weboutput/once', True)

        settings.setValue('twitchbot/enabled', False)

        settings.setValue('quirks/pollingobserver', False)
        settings.setValue('quirks/filesubst', False)
        settings.setValue('quirks/slashmode', 'nochange')

        self._defaults_plugins(settings)

    def _initial_plugins(self):

        self.plugins['inputs'] = nowplaying.utils.import_plugins(
            nowplaying.inputs)
        self.pluginobjs['inputs'] = {}
        self.plugins['recognition'] = nowplaying.utils.import_plugins(
            nowplaying.recognition)
        self.pluginobjs['recognition'] = {}

        self.plugins['artistextras'] = nowplaying.utils.import_plugins(
            nowplaying.artistextras)
        self.pluginobjs['artistextras'] = {}

    def _defaults_plugins(self, settings):
        ''' configure the defaults for input plugins '''
        self.pluginobjs = {}
        for plugintype, plugtypelist in self.plugins.items():
            self.pluginobjs[plugintype] = {}
            for key in plugtypelist:
                self.pluginobjs[plugintype][key] = self.plugins[plugintype][
                    key].Plugin(config=self, qsettings=settings)
                self.pluginobjs[plugintype][key].defaults(settings)

    def plugins_connect_settingsui(self, qtwidgets):
        ''' configure the defaults for plugins '''
        # qtwidgets = list of qtwidgets, identified as [plugintype_pluginname]
        for plugintype, plugtypelist in self.plugins.items():
            for key in plugtypelist:
                widgetkey = key.split('.')[-1]
                self.pluginobjs[plugintype][key].connect_settingsui(
                    qtwidgets[f'{plugintype}_{widgetkey}'])

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
                if (widgetkey == inputname and plugintype
                        == 'inputs') or (plugintype != 'inputs'):
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
        self.pluginobjs[plugintype][
            f'nowplaying.{plugintype}.{plugin}'].desc_settingsui(qtwidget)

    # pylint: disable=too-many-arguments
    def put(self, initialized, file, txttemplate, notif, loglevel):
        ''' Save the configuration file '''

        self.file = file
        self.initialized = initialized
        self.loglevel = loglevel
        self.notif = notif
        self.txttemplate = txttemplate

        self.save()

    def save(self):
        ''' save the current set '''

        self.cparser.setValue('settings/initialized', self.initialized)
        self.cparser.setValue('settings/lastsavedate',
                              time.strftime("%Y%m%d%H%M%S"))
        self.cparser.setValue('settings/loglevel', self.loglevel)
        self.cparser.setValue('settings/notif', self.notif)
        self.cparser.setValue('textoutput/file', self.file)
        self.cparser.setValue('textoutput/txttemplate', self.txttemplate)

        self.cparser.sync()

    def find_icon_file(self):  # pylint: disable=no-self-use
        ''' try to find our icon '''

        if not ConfigFile.BUNDLEDIR:
            logging.error('bundledir not set in config')
            return None

        for testdir in [
                ConfigFile.BUNDLEDIR,
                os.path.join(ConfigFile.BUNDLEDIR, 'bin'),
                os.path.join(ConfigFile.BUNDLEDIR, 'resources')
        ]:
            for testfilename in ['icon.ico', 'windows.ico']:
                testfile = os.path.join(testdir, testfilename)
                if os.path.exists(testfile):
                    logging.debug('iconfile at %s', testfile)
                    return testfile

        if not self.testmode:
            self.testmode = self.cparser.value('testmode/enabled')

        if not self.testmode:
            logging.error('Unable to find the icon file. Death only follows.')
        return None

    def find_ui_file(self):  # pylint: disable=no-self-use
        ''' try to find our icon '''

        if not ConfigFile.BUNDLEDIR:
            logging.error('bundledir not set in config')
            return None

        for testdir in [
                ConfigFile.BUNDLEDIR,
                os.path.join(ConfigFile.BUNDLEDIR, 'bin'),
                os.path.join(ConfigFile.BUNDLEDIR, 'resources')
        ]:
            testfile = os.path.join(testdir, 'settings_ui.ui')
            if os.path.exists(testfile):
                logging.debug('ui file at %s', testfile)
                return testdir

        if not self.testmode:
            self.testmode = self.cparser.value('testmode/enabled')

        if not self.testmode:
            logging.error('Unable to find the ui dir. Death only follows.')
        return None

    def pause(self):  # pylint: disable=no-self-use
        ''' Pause system '''
        ConfigFile.PAUSED = True
        logging.warning('NowPlaying is currently paused.')

    def unpause(self):  # pylint: disable=no-self-use
        ''' unpause system '''
        ConfigFile.PAUSED = False
        logging.warning('NowPlaying is no longer paused.')

    def getpause(self):  # pylint: disable=no-self-use
        ''' Get the pause status '''
        return ConfigFile.PAUSED

    def validmixmodes(self):  # pylint: disable=no-self-use
        ''' unpause system '''
        plugin = self.cparser.value('settings/input')
        inputplugin = self.plugins['inputs'][
            f'nowplaying.inputs.{plugin}'].Plugin(config=self)
        return inputplugin.validmixmodes()

    def setmixmode(self, mixmode):  # pylint: disable=no-self-use
        ''' set the mixmode by calling the plugin '''

        plugin = self.cparser.value('settings/input')
        inputplugin = self.plugins['inputs'][
            f'nowplaying.inputs.{plugin}'].Plugin(config=self)
        return inputplugin.setmixmode(mixmode)

    def getmixmode(self):  # pylint: disable=no-self-use
        ''' unpause system '''
        plugin = self.cparser.value('settings/input')
        inputplugin = self.plugins['inputs'][
            f'nowplaying.inputs.{plugin}'].Plugin(config=self)
        return inputplugin.getmixmode()

    def getbundledir(self):  # pylint: disable=no-self-use
        ''' get the bundle dir '''
        return ConfigFile.BUNDLEDIR

    def getsetlistdir(self):  # pylint: disable=no-self-use
        ''' get the setlist directory '''
        return os.path.join(
            QStandardPaths.standardLocations(
                QStandardPaths.DocumentsLocation)[0],
            QCoreApplication.applicationName(), 'setlists')

    def getregexlist(self):
        ''' get the regex title filter '''
        if not self.striprelist or self.lastloaddate < self.cparser.value(
                'settings/lastsavedate'):
            try:
                self.striprelist = [
                    re.compile(self.cparser.value(configitem))
                    for configitem in self.cparser.allKeys()
                    if 'regex_filter/' in configitem
                ]
                self.lastloaddate = self.cparser.value('settings/lastsavedate')
            except re.error as error:
                logging.error('Filter error with \'%s\': %s', error.pattern,
                              error.msg)
        return self.striprelist
