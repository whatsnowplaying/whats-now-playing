#!/usr/bin/env python3
''' test templatehandler '''

import os
import tempfile

import pytest

import nowplaying.utils  # pylint: disable=import-error
import nowplaying.textoutput  # pylint: disable=import-error,no-member


@pytest.fixture
def gettemplatehandler(getroot, bootstrap, request):
    ''' automated integration test '''
    config = bootstrap  # pylint: disable=unused-variable
    mark = request.node.get_closest_marker("templatesettings")
    if mark and 'template' in mark.kwargs:
        template = os.path.join(getroot, 'tests', 'templates', mark.kwargs['template'])
    else:
        template = None
    return nowplaying.utils.TemplateHandler(filename=template)


@pytest.mark.templatesettings(template='simple.txt')
def test_writingmeta(gettemplatehandler):  # pylint: disable=redefined-outer-name
    ''' try writing a text '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')

        metadata = {
            'artist': 'this is an artist',
            'title': 'this is the title',
        }

        nowplaying.textoutput.writetxttrack(filename=filename,  # pylint: disable=no-member
                                            templatehandler=gettemplatehandler,
                                            metadata=metadata)
        with open(filename) as tempfn:  # pylint: disable=unspecified-encoding
            content = tempfn.readlines()

        assert 'this is an artist' in content[0]
        assert 'this is the title' in content[1]


@pytest.mark.templatesettings(template='simple.txt')
def test_missingmeta(gettemplatehandler):  # pylint: disable=redefined-outer-name
    ''' empty metadata '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')

        metadata = {}

        nowplaying.textoutput.writetxttrack(filename=filename,  # pylint: disable=no-member
                                            templatehandler=gettemplatehandler,
                                            metadata=metadata)
        with open(filename) as tempfn:  # pylint: disable=unspecified-encoding
            content = tempfn.readlines()

        assert content[0].strip() == ''


@pytest.mark.templatesettings(template='missing.txt')
def test_missingtemplate(gettemplatehandler):  # pylint: disable=redefined-outer-name
    ''' template is missing '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')

        metadata = {
            'artist': 'this is an artist',
            'title': 'this is the title',
        }

        nowplaying.textoutput.writetxttrack(filename=filename,  # pylint: disable=no-member
                                            templatehandler=gettemplatehandler,
                                            metadata=metadata)
        with open(filename) as tempfn:  # pylint: disable=unspecified-encoding
            content = tempfn.readlines()

        assert 'No template found' in content[0]


def test_missingfilename(gettemplatehandler):  # pylint: disable=redefined-outer-name
    ''' no template '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')

        metadata = {
            'artist': 'this is an artist',
            'title': 'this is the title',
        }

        nowplaying.textoutput.writetxttrack(filename=filename,  # pylint: disable=no-member
                                            templatehandler=gettemplatehandler,
                                            metadata=metadata)
        with open(filename) as tempfn:  # pylint: disable=unspecified-encoding
            content = tempfn.readlines()

        assert 'No template found' in content[0]


def test_cleartemplate():  # pylint: disable=redefined-outer-name
    ''' try writing a text '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')
        nowplaying.textoutput.writetxttrack(filename=filename, clear=True)  # pylint: disable=no-member
        with open(filename) as tempfn:  # pylint: disable=unspecified-encoding
            content = tempfn.readlines()

        assert not content


def test_justafile():  # pylint: disable=redefined-outer-name
    ''' try writing a text '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')
        nowplaying.textoutput.writetxttrack(filename=filename)  # pylint: disable=no-member
        with open(filename) as tempfn:  # pylint: disable=unspecified-encoding
            content = tempfn.readlines()

        assert content[0] == '{{ artist }} - {{ title }}'


@pytest.mark.templatesettings(template='tracktest.txt')
@pytest.mark.parametrize(
    "track_value,disc_value,expected_track,expected_disc",
    [
        ('0', '0', True, True),  # Track 0 and disc 0 should show
        ('1', '1', True, True),  # Track 1 and disc 1 should show
        ('', '', False, False),  # Empty strings should not show
        (None, None, False, False),  # None values should not show
    ])
def test_track_disc_handling(  # pylint: disable=redefined-outer-name
                             gettemplatehandler, track_value, disc_value, expected_track,
                             expected_disc):
    ''' test track and disc number handling with various values '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')

        metadata = {}
        if track_value is not None:
            metadata['track'] = track_value
        if disc_value is not None:
            metadata['disc'] = disc_value

        nowplaying.textoutput.writetxttrack(filename=filename,  # pylint: disable=no-member
                                            templatehandler=gettemplatehandler,
                                            metadata=metadata)
        with open(filename) as tempfn:  # pylint: disable=unspecified-encoding
            content = tempfn.read()

        if expected_track:
            assert f'Track: {track_value}' in content
        else:
            assert 'Track:' not in content

        if expected_disc:
            assert f'Disc: {disc_value}' in content
        else:
            assert 'Disc:' not in content
