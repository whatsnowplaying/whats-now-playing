#!/usr/bin/env python3
''' test hostmeta '''

import nowplaying.hostmeta  # pylint: disable=import-error


def test_empty_db():
    ''' test getting ip info '''
    hostinfo = nowplaying.hostmeta.gethostmeta()
    assert hostinfo is not None
    assert hostinfo['hostname'] is not None
    assert hostinfo['hostfqdn'] is not None
    assert hostinfo['hostip'] is not None
