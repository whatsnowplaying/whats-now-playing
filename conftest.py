#!/usr/bin/env python3
''' pytest fixtures '''

import os
import logging
import pytest

import nowplaying.bootstrap
import nowplaying.config


@pytest.fixture
def bootstrap():
    ''' bootstrap a configuration '''
    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names(appname='testsuite')
    config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)
    config.cparser.sync()
    yield config
    config.cparser.clear()
    if os.path.exists(config.cparser.fileName()):
        os.unlink(config.cparser.fileName())


@pytest.fixture
def getroot(pytestconfig):
    ''' get the base of the source tree '''
    return pytestconfig.rootpath
