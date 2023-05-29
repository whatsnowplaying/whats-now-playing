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


def test_songsubst1(bootstrap):
    ''' test file name substition1 '''
    config = bootstrap
    config.cparser.setValue('quirks/filesubst', True)
    config.cparser.setValue('quirks/filesubstin', '/songs')
    config.cparser.setValue('quirks/filesubstout', '/newlocation')
    location = nowplaying.utils.songpathsubst(config, '/songs/mysong')
    assert location == '/newlocation/mysong'


def test_songsubst2forward(bootstrap):
    ''' test file name substition1 '''
    config = bootstrap
    config.cparser.setValue('quirks/filesubst', True)
    config.cparser.setValue('quirks/slashmode', 'toback')
    location = nowplaying.utils.songpathsubst(config, '/songs/myband/mysong')
    assert location == '\\songs\\myband\\mysong'


def test_songsubst2backward(bootstrap):
    ''' test file name substition1 '''
    config = bootstrap
    config.cparser.setValue('quirks/filesubst', True)
    config.cparser.setValue('quirks/slashmode', 'toforward')
    location = nowplaying.utils.songpathsubst(config, '\\songs\\myband\\mysong')
    assert location == '/songs/myband/mysong'


def test_songsubst_tounix(bootstrap):
    ''' test file name substition1 '''
    config = bootstrap
    config.cparser.setValue('quirks/filesubst', True)
    config.cparser.setValue('quirks/filesubstin', 'Z:/Music')
    config.cparser.setValue('quirks/filesubstout', '/Music')
    config.cparser.setValue('quirks/slashmode', 'toforward')
    location = nowplaying.utils.songpathsubst(config, 'Z:\\Music\\Band\\Song')
    assert location == '/Music/Band/Song'


def test_songsubst_towindows(bootstrap):
    ''' test file name substition1 '''
    config = bootstrap
    config.cparser.setValue('quirks/filesubst', True)
    config.cparser.setValue('quirks/filesubstin', '\\Music')
    config.cparser.setValue('quirks/filesubstout', 'Z:\\Music')
    config.cparser.setValue('quirks/slashmode', 'toback')
    location = nowplaying.utils.songpathsubst(config, '/Music/Band/Song')
    assert location == 'Z:\\Music\\Band\\Song'


def test_basicstrip_explicitdash():
    ''' automated integration test '''
    metadata = {'title': 'Test - Explicit'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Test - Explicit'
    assert title == 'Test'


def test_basicstrip_dirtydash():
    ''' automated integration test '''
    metadata = {'title': 'Test - Dirty'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Test - Dirty'
    assert title == 'Test'


def test_basicstrip_cleandash():
    ''' automated integration test '''
    metadata = {'title': 'Test - Clean'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Test - Clean'
    assert title == 'Test'


def test_basicstrip_noclean():
    ''' automated integration test '''
    metadata = {'title': 'Clean'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Clean'
    assert title == 'Clean'


def test_basicstrip_cleanparens():
    ''' automated integration test '''
    metadata = {'title': 'Test (Clean)'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Test (Clean)'
    assert title == 'Test'


def test_basicstrip_cleansquareb():
    ''' automated integration test '''
    metadata = {'title': 'Test [Clean]'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Test [Clean]'
    assert title == 'Test'


def test_basicstrip_cleanextraparens():
    ''' automated integration test '''
    metadata = {'title': 'Test (Clean) (Single Mix)'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Test (Clean) (Single Mix)'
    assert title == 'Test (Single Mix)'


def test_basicstrip_ovm1():
    ''' automated integration test '''
    metadata = {'title': 'Test (Clean) (Official Music Video)'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Test (Clean) (Official Music Video)'
    assert title == 'Test'


def test_basicstrip_ovm2():
    ''' automated integration test '''
    metadata = {'title': 'Test (Clean) [official music video]'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Test (Clean) [official music video]'
    assert title == 'Test'


def test_basicstrip_ovm3():
    ''' automated integration test '''
    metadata = {'title': 'Clean [official music video]'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Clean [official music video]'
    assert title == 'Clean'


def test_basicstrip_doubleclean():
    ''' automated integration test '''
    metadata = {'title': 'Clean - Clean'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Clean - Clean'
    assert title == 'Clean'


def test_basicstrip_ovm4():
    ''' automated integration test '''
    metadata = {'title': 'Clean - Official Music Video'}
    title = nowplaying.utils.titlestripper_basic(title=metadata['title'])
    assert metadata['title'] == 'Clean - Official Music Video'
    assert title == 'Clean'


def test_image2png(getroot):
    ''' check png image conversion '''
    filename = getroot.joinpath('tests', 'images', '1x1.jpg')
    with open(filename, 'rb') as fhin:
        image = fhin.read()

    pngdata = nowplaying.utils.image2png(image)

    pngdata2 = nowplaying.utils.image2png(pngdata)
    assert pngdata.startswith(b'\211PNG\r\n\032\n')
    assert pngdata2 == pngdata


def test_image2avif(getroot):
    ''' check png image conversion '''
    filename = getroot.joinpath('tests', 'images', '1x1.jpg')
    with open(filename, 'rb') as fhin:
        image = fhin.read()

    avifdata = nowplaying.utils.image2avif(image)
    avifdata2 = nowplaying.utils.image2avif(avifdata)
    assert avifdata.startswith(b'\x00\x00\x00 ftypavif')
    assert avifdata2 == avifdata
