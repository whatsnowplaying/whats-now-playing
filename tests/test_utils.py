#!/usr/bin/env python3
''' test utils not covered elsewhere '''

import nowplaying.utils  # pylint: disable=import-error


def results(expected, metadata):
    ''' take a metadata result and compare to expected '''
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]
    assert metadata == {}


def test_getmoremetadata_brokenmd():
    ''' test getmoremetadata when based garbage '''

    assert not nowplaying.utils.getmoremetadata()

    metadatain = {'filename': 'filenamedoesnotexist'}

    metadataout = nowplaying.utils.getmoremetadata(metadatain.copy())
    results(metadatain, metadataout)
