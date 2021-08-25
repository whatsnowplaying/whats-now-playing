#!/usr/bin/env python3
''' pytest fixtures '''

import os
import logging
import pytest

import nowplaying.bootstrap
import nowplaying.config


@pytest.fixture
def getroot(pytestconfig):
    ''' get the base of the source tree '''
    return pytestconfig.rootpath


@pytest.fixture
def bootstrap(getroot):  # pylint: disable=redefined-outer-name
    ''' bootstrap a configuration '''
    bundledir = os.path.join(getroot, 'nowplaying')
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names(appname='testsuite')
    config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)
    config.cparser.sync()
    yield config
    config.cparser.clear()
    config.cparser.sync()
    if os.path.exists(config.cparser.fileName()):
        os.unlink(config.cparser.fileName())
