#!/usr/bin/env python3
''' test bootstrap '''

import nowplaying.bootstrap  # pylint: disable=import-error


def test_verify_python_version(qtbot):
    ''' just a dumb test for version check '''
    fred = qtbot  # pylint: disable=unused-variable

    assert nowplaying.bootstrap.verify_python_version()
