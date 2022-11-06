#!/usr/bin/env python3
''' misc nowplaying.config tests '''

import pathlib

from PySide6.QtCore import QCoreApplication, QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.config  # pylint: disable=import-error


def test_reset1(bootstrap):
    ''' test config.reset '''
    config = bootstrap
    config.cparser.setValue('fake/setting', True)
    assert config.cparser.value('fake/setting')
    config.reset()
    assert not config.cparser.value('fake/setting')


def test_reset2(getroot):
    ''' test config.reset via init '''
    bundledir = pathlib.Path(getroot).joinpath('nowplaying')
    nowplaying.bootstrap.set_qt_names(appname='testsuite')
    config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('fake/setting', True)
    config.cparser.sync()
    assert config.cparser.value('fake/setting')
    del config
    config = nowplaying.config.ConfigFile(bundledir=bundledir,
                                          reset=True,
                                          testmode=True)
    assert not config.cparser.value('fake/setting')


def test_put(bootstrap):
    ''' test config.put / config.save '''
    config = bootstrap
    config.cparser.setValue('settings/initialized', False)
    config.cparser.setValue('settings/loglevel', 'invalid1')
    config.cparser.setValue('settings/notif', True)
    config.cparser.setValue('textoutput/file', 'invalid2')
    config.cparser.setValue('textoutput/txttemplate', 'invalid3')

    config.put(initialized=True,
               file='real1',
               txttemplate='real2',
               notif=True,
               loglevel='DEBUG')
    del config
    config = bootstrap

    assert config.cparser.value('settings/initialized')
    assert config.cparser.value('settings/loglevel') == 'DEBUG'
    assert config.cparser.value('settings/notif')
    assert config.cparser.value('textoutput/file') == 'real1'
    assert config.cparser.value('textoutput/txttemplate') == 'real2'


def test_get1(bootstrap):
    ''' test basic config.get '''
    config = bootstrap

    assert not config.file
    assert not config.initialized
    assert config.loglevel == 'DEBUG'
    assert not config.notif
    assert config.txttemplate == str(
        pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.DocumentsLocation)[0],
            QCoreApplication.applicationName()).joinpath(
                'templates', 'basic-plain.txt'))

    config.cparser.setValue('settings/initialized', True)
    config.cparser.setValue('settings/loglevel', 'invalid1')
    config.cparser.setValue('settings/notif', True)
    config.cparser.setValue('textoutput/file', 'invalid2')
    config.cparser.setValue('textoutput/txttemplate', 'invalid3')

    config.get()

    assert config.file == 'invalid2'
    assert config.initialized
    assert config.loglevel == 'invalid1'
    assert config.notif
    assert config.txttemplate == 'invalid3'


def test_bundledir(getroot, bootstrap):
    ''' test config.getbundledir '''
    bundledir = pathlib.Path(getroot).joinpath('nowplaying')
    config = bootstrap
    assert bundledir == config.getbundledir()
