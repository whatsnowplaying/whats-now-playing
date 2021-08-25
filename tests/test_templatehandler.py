#!/usr/bin/env python3
''' test templatehandler '''

import os
import tempfile

import pytest

import nowplaying.utils  # pylint: disable=import-error


@pytest.fixture
def gettemplatehandler(getroot, bootstrap, request):
    ''' automated integration test '''
    config = bootstrap  # pylint: disable=unused-variable
    mark = request.node.get_closest_marker("templatesettings")
    if mark and 'template' in mark.kwargs:
        template = os.path.join(getroot, 'tests', 'templates',
                                mark.kwargs['template'])
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

        nowplaying.utils.writetxttrack(filename=filename,
                                       templatehandler=gettemplatehandler,
                                       metadata=metadata)
        with open(filename, 'r') as tempfn:
            content = tempfn.readlines()

        assert 'this is an artist' in content[0]
        assert 'this is the title' in content[1]


@pytest.mark.templatesettings(template='simple.txt')
def test_missingmeta(gettemplatehandler):  # pylint: disable=redefined-outer-name
    ''' empty metadata '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')

        metadata = {}

        nowplaying.utils.writetxttrack(filename=filename,
                                       templatehandler=gettemplatehandler,
                                       metadata=metadata)
        with open(filename, 'r') as tempfn:
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

        nowplaying.utils.writetxttrack(filename=filename,
                                       templatehandler=gettemplatehandler,
                                       metadata=metadata)
        with open(filename, 'r') as tempfn:
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

        nowplaying.utils.writetxttrack(filename=filename,
                                       templatehandler=gettemplatehandler,
                                       metadata=metadata)
        with open(filename, 'r') as tempfn:
            content = tempfn.readlines()

        assert 'No template found' in content[0]


def test_cleartemplate():  # pylint: disable=redefined-outer-name
    ''' try writing a text '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')
        nowplaying.utils.writetxttrack(filename=filename, clear=True)
        with open(filename, 'r') as tempfn:
            content = tempfn.readlines()

        assert not content


def test_justafile():  # pylint: disable=redefined-outer-name
    ''' try writing a text '''
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, 'test.txt')
        nowplaying.utils.writetxttrack(filename=filename)
        with open(filename, 'r') as tempfn:
            content = tempfn.readlines()

        assert content[0] == '{{ artist }} - {{ title }}'
