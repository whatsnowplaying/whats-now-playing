#!/usr/bin/env python3
''' test m3u '''

import os
import pathlib
import logging
import shutil
import tempfile

import pytest

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.config  # pylint: disable=import-error


@pytest.fixture
def upgrade_bootstrap(getroot):
    ''' bootstrap a configuration '''
    with tempfile.TemporaryDirectory() as newpath:
        bundledir = os.path.join(getroot, 'nowplaying')
        logging.basicConfig(level=logging.DEBUG)
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
        config = nowplaying.config.ConfigFile(bundledir=bundledir,
                                              testmode=True)
        config.cparser.sync()
        old_cwd = os.getcwd()
        os.chdir(newpath)
        yield newpath, config
        os.chdir(old_cwd)
        config.cparser.clear()
        config.cparser.sync()
        if os.path.exists(config.cparser.fileName()):
            os.unlink(config.cparser.fileName())


def compare_content(srcdir, destdir, conflict=None):
    ''' compare src templates to what was copied '''
    srctemplates = os.listdir(srcdir)
    desttemplates = os.listdir(destdir)
    filelist = []
    for filename in srctemplates + desttemplates:
        basefn = os.path.basename(filename)
        filelist.append(basefn)

    filelist = sorted(set(filelist))

    for filename in filelist:
        srcfn = os.path.join(srcdir, filename)
        destfn = os.path.join(destdir, filename)

        if '.new' in filename:
            continue

        if conflict and os.path.basename(srcfn) == os.path.basename(conflict):
            newname = filename.replace('.txt', '.new')
            newname = newname.replace('.htm', '.new')
            newdestfn = os.path.join(destdir, newname)
            assert filename and list(open(srcfn)) != list(open(destfn)) #pylint: disable=consider-using-with, unspecified-encoding
            assert filename and list(open(srcfn)) == list(open(newdestfn)) #pylint: disable=consider-using-with, unspecified-encoding
        else:
            assert filename and list(open(srcfn)) == list(open(destfn)) #pylint: disable=consider-using-with, unspecified-encoding


def test_upgrade_blank(upgrade_bootstrap):  # pylint: disable=redefined-outer-name
    ''' check a blank dir '''
    (testpath, config) = upgrade_bootstrap
    bundledir = config.getbundledir()
    nowplaying.bootstrap.UpgradeTemplates(bundledir=bundledir,
                                          testdir=testpath)
    srcdir = os.path.join(bundledir, 'templates')
    destdir = os.path.join(testpath, 'testsuite', 'templates')
    compare_content(srcdir, destdir)


def test_upgrade_conflict(upgrade_bootstrap):  # pylint: disable=redefined-outer-name,too-many-locals
    ''' different content of standard template should create new '''
    (testpath, config) = upgrade_bootstrap
    bundledir = config.getbundledir()
    srcdir = os.path.join(bundledir, 'templates')
    destdir = os.path.join(testpath, 'testsuite', 'templates')
    srctemplates = os.listdir(srcdir)
    pathlib.Path(destdir).mkdir(parents=True, exist_ok=True)
    touchfile = os.path.join(destdir, os.path.basename(srctemplates[0]))
    pathlib.Path(touchfile).touch()
    nowplaying.bootstrap.UpgradeTemplates(bundledir=bundledir,
                                          testdir=testpath)
    compare_content(srcdir, destdir, touchfile)


def test_upgrade_same(upgrade_bootstrap):  # pylint: disable=redefined-outer-name,too-many-locals
    ''' if a file already exists it shouldn't get .new'd '''
    (testpath, config) = upgrade_bootstrap
    bundledir = config.getbundledir()
    srcdir = os.path.join(bundledir, 'templates')
    destdir = os.path.join(testpath, 'testsuite', 'templates')
    srctemplates = os.listdir(srcdir)
    pathlib.Path(destdir).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(os.path.join(srcdir, srctemplates[1]),
                    os.path.join(destdir, os.path.basename(srctemplates[1])))
    nowplaying.bootstrap.UpgradeTemplates(bundledir=bundledir,
                                          testdir=testpath)
    compare_content(srcdir, destdir)


def test_upgrade_old(upgrade_bootstrap, getroot):  # pylint: disable=redefined-outer-name,too-many-locals
    ''' custom .txt, .new from previous upgrade '''
    (testpath, config) = upgrade_bootstrap
    bundledir = config.getbundledir()
    srcdir = os.path.join(bundledir, 'templates')
    destdir = os.path.join(testpath, 'testsuite', 'templates')
    pathlib.Path(destdir).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        os.path.join(getroot, 'tests', 'templates', 'songquotes.txt'),
        os.path.join(destdir, 'songquotes.new'))
    touchfile = os.path.join(destdir, 'songquotes.txt')
    pathlib.Path(touchfile).touch()
    nowplaying.bootstrap.UpgradeTemplates(bundledir=bundledir,
                                          testdir=testpath)
    assert list(open(os.path.join(srcdir, 'songquotes.txt'))) == list( #pylint: disable=consider-using-with, unspecified-encoding
        open(os.path.join(destdir, 'songquotes.new'))) #pylint: disable=consider-using-with, unspecified-encoding
    compare_content(srcdir, destdir, conflict=touchfile)
