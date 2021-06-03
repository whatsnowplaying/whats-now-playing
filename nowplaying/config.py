#!/usr/bin/env python3
'''
   config file parsing/handling
'''

import multiprocessing
import logging
import os
import sys

from PySide2.QtCore import QCoreApplication, QSettings, QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.inputs
import nowplaying.utils
import nowplaying.version


class ConfigFile:  # pylint: disable=too-many-instance-attributes
    ''' read and write to config.ini '''

    ## Qt doesn't appear to support re-entrant locks or mutexes so
    ## let's use boring old Python threading

    BUNDLEDIR = None
    LOCK = multiprocessing.RLock()
    PAUSED = False

    def __init__(self, bundledir=None, reset=False):

        ConfigFile.LOCK.acquire()

        self.initialized = False
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

        self.iconfile = self.find_icon_file()
        self.uidir = self.find_ui_file()

        self.cparser = QSettings(self.qsettingsformat, QSettings.UserScope,
                                 QCoreApplication.organizationName(),
                                 QCoreApplication.applicationName())
        logging.info('configuration: %s', self.cparser.fileName())
        self.notif = False
        ConfigFile.PAUSED = False
        self.file = None
        self.txttemplate = os.path.join(self.templatedir, "basic-plain.txt")
        self.loglevel = 'DEBUG'

        self.input_plugins = nowplaying.utils.import_plugins(nowplaying.inputs)
        self.input_pluginobjs = None

        self.defaults()
        if reset:
            self.cparser.clear()
            self.save()
        else:
            self.get()

        ConfigFile.LOCK.release()

    def reset(self):
        ''' forcibly go back to defaults '''
        logging.debug('config reset')
        self.__init__(bundledir=ConfigFile.BUNDLEDIR, reset=True)

    def get(self):
        ''' refresh values '''

        ConfigFile.LOCK.acquire()
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

        ConfigFile.LOCK.release()

    def defaults(self):
        ''' default values for things '''
        logging.debug('set defaults')

        settings = QSettings(self.qsettingsformat, QSettings.SystemScope,
                             QCoreApplication.organizationName(),
                             QCoreApplication.applicationName())

        settings.setValue('settings/delay', '1.0')
        settings.setValue('settings/input', 'serato')
        settings.setValue('settings/initialized', False)
        settings.setValue('settings/loglevel', self.loglevel)
        settings.setValue('settings/notif', self.notif)
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
        settings.setValue('weboutput/httpenabled', False)
        settings.setValue('weboutput/httpport', '8899')
        settings.setValue('weboutput/once', True)

        settings.setValue('twitchbot/enabled', False)

        self._defaults_input_plugins(settings)

    def _defaults_input_plugins(self, settings):
        ''' configure the defaults for input plugins '''
        self.input_pluginobjs = {}
        for key in self.input_plugins:
            self.input_pluginobjs[key] = self.input_plugins[key].Plugin(
                config=self, qsettings=settings)
            self.input_pluginobjs[key].defaults(settings)

    def plugins_connect_settingsui(self, qtwidgets):
        ''' configure the defaults for input plugins '''
        for key in self.input_pluginobjs:
            widgetkey = key.split('.')[-1]
            self.input_pluginobjs[key].connect_settingsui(qtwidgets[widgetkey])

    def plugins_load_settingsui(self, qtwidgets):
        ''' configure the defaults for input plugins '''
        for key in self.input_pluginobjs:
            widgetkey = key.split('.')[-1]
            self.input_pluginobjs[key].load_settingsui(qtwidgets[widgetkey])

    def plugins_verify_settingsui(self, inputname, qtwidgets):
        ''' configure the defaults for input plugins '''
        for key in self.input_pluginobjs:
            widgetkey = key.split('.')[-1]
            if widgetkey == inputname:
                self.input_pluginobjs[key].connect_settingsui(
                    qtwidgets[inputname])

    def plugins_save_settingsui(self, qtwidgets):
        ''' configure the defaults for input plugins '''
        for key in self.input_pluginobjs:
            widgetkey = key.split('.')[-1]
            self.input_pluginobjs[key].save_settingsui(qtwidgets[widgetkey])

    def plugins_description(self, plugin, qtwidget):
        ''' configure the defaults for input plugins '''
        self.input_pluginobjs[f'nowplaying.inputs.{plugin}'].desc_settingsui(
            qtwidget)

    # pylint: disable=too-many-arguments
    def put(self, initialized, file, txttemplate, notif, loglevel):
        ''' Save the configuration file '''

        ConfigFile.LOCK.acquire()

        self.file = file
        self.initialized = initialized
        self.loglevel = loglevel
        self.notif = notif
        self.txttemplate = txttemplate

        self.save()

        ConfigFile.LOCK.release()

    def save(self):
        ''' save the current set '''

        ConfigFile.LOCK.acquire()

        self.cparser.setValue('settings/initialized', self.initialized)
        self.cparser.setValue('settings/loglevel', self.loglevel)
        self.cparser.setValue('settings/notif', self.notif)
        self.cparser.setValue('textoutput/file', self.file)
        self.cparser.setValue('textoutput/txttemplate', self.txttemplate)
        self.cparser.sync()

        ConfigFile.LOCK.release()

    def find_icon_file(self):  # pylint: disable=no-self-use
        ''' try to find our icon '''

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

        logging.error('Unable to find the icon file. Death only follows.')
        return None

    def find_ui_file(self):  # pylint: disable=no-self-use
        ''' try to find our icon '''

        for testdir in [
                ConfigFile.BUNDLEDIR,
                os.path.join(ConfigFile.BUNDLEDIR, 'bin'),
                os.path.join(ConfigFile.BUNDLEDIR, 'resources')
        ]:
            testfile = os.path.join(testdir, 'settings_ui.ui')
            if os.path.exists(testfile):
                logging.debug('ui file at %s', testfile)
                return testdir

        logging.error('Unable to find the ui dir. Death only follows.')
        return None

    def pause(self):  # pylint: disable=no-self-use
        ''' Pause system '''
        ConfigFile.PAUSED = True

    def unpause(self):  # pylint: disable=no-self-use
        ''' unpause system '''
        ConfigFile.PAUSED = False

    def getpause(self):  # pylint: disable=no-self-use
        ''' Get the pause status '''
        return ConfigFile.PAUSED

    def validmixmodes(self):  # pylint: disable=no-self-use
        ''' unpause system '''
        plugin = self.cparser.value('settings/input')
        inputplugin = self.input_plugins[f'nowplaying.inputs.{plugin}'].Plugin(
        )
        return inputplugin.getmixmode()

    def setmixmode(self, mixmode):  # pylint: disable=no-self-use
        ''' set the mixmode by calling the plugin '''

        plugin = self.cparser.value('settings/input')
        inputplugin = self.input_plugins[f'nowplaying.inputs.{plugin}'].Plugin(
        )
        return inputplugin.setmixmode(mixmode)

    def getmixmode(self):  # pylint: disable=no-self-use
        ''' unpause system '''
        plugin = self.cparser.value('settings/input')
        inputplugin = self.input_plugins[f'nowplaying.inputs.{plugin}'].Plugin(
        )
        return inputplugin.getmixmode()

    def getbundledir(self):  # pylint: disable=no-self-use
        ''' get the bundle dir '''
        return ConfigFile.BUNDLEDIR
