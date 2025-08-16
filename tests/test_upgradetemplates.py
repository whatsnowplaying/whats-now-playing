#!/usr/bin/env python3
"""test m3u"""

import os
import pathlib
import logging
import shutil
import tempfile

import pytest

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.config  # pylint: disable=import-error
import nowplaying.upgrades.templates  # pylint: disable=import-error


@pytest.fixture
def upgrade_bootstrap(getroot):
    """bootstrap a configuration"""
    with tempfile.TemporaryDirectory() as newpath:
        bundledir = os.path.join(getroot, "nowplaying")
        logging.basicConfig(level=logging.DEBUG)
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
        config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)
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
    """compare src templates to what was copied"""
    _compare_directory_recursive(srcdir, destdir, conflict)


def _is_binary_file(filepath):
    """Check if a file is binary by examining its extension or content"""
    binary_extensions = {
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".ico",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
    }
    if any(filepath.lower().endswith(ext) for ext in binary_extensions):
        return True
    return False


def _compare_files(srcfn, destfn):
    """Compare two files, handling both text and binary files"""
    if _is_binary_file(srcfn):
        # Binary comparison
        with open(srcfn, "rb") as src, open(destfn, "rb") as dest:
            return src.read() == dest.read()
    else:
        # Text comparison with UTF-8 encoding
        try:
            with (
                open(srcfn, "r", encoding="utf-8") as src,
                open(destfn, "r", encoding="utf-8") as dest,
            ):
                return list(src) == list(dest)
        except UnicodeDecodeError:
            # Fallback to binary comparison if UTF-8 fails
            with open(srcfn, "rb") as src, open(destfn, "rb") as dest:
                return src.read() == dest.read()


def _compare_directory_recursive(srcdir, destdir, conflict=None):
    """recursively compare directories

    Extra files in destination directories are allowed (e.g., user-created templates
    or .new files from previous upgrades). This function only validates that all
    source files are correctly copied to the destination.
    """
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

        if ".new" in filename:
            continue

        # Handle directories recursively
        if os.path.isdir(srcfn):
            assert os.path.isdir(destfn), f"Expected {destfn} to be a directory"
            _compare_directory_recursive(srcfn, destfn, conflict)
            continue

        # Handle files
        if conflict and os.path.basename(srcfn) == os.path.basename(conflict):
            newname = filename.replace(".txt", ".new")
            newname = newname.replace(".htm", ".new")
            newdestfn = os.path.join(destdir, newname)
            assert filename and not _compare_files(srcfn, destfn)
            assert filename and _compare_files(srcfn, newdestfn)
        else:
            assert filename and _compare_files(srcfn, destfn)


def test_upgrade_blank(upgrade_bootstrap):  # pylint: disable=redefined-outer-name
    """check a blank dir"""
    (testpath, config) = upgrade_bootstrap
    bundledir = config.getbundledir()
    nowplaying.upgrades.templates.UpgradeTemplates(bundledir=bundledir, testdir=testpath)
    srcdir = os.path.join(bundledir, "templates")
    destdir = os.path.join(testpath, "testsuite", "templates")
    compare_content(srcdir, destdir)


@pytest.mark.xfail(os.name == "posix", reason="Template upgrade conflicts on Linux")
def test_upgrade_conflict(upgrade_bootstrap):  # pylint: disable=redefined-outer-name,too-many-locals
    """different content of standard template should create new"""
    (testpath, config) = upgrade_bootstrap
    bundledir = config.getbundledir()
    srcdir = os.path.join(bundledir, "templates")
    destdir = os.path.join(testpath, "testsuite", "templates")
    srctemplates = os.listdir(srcdir)
    pathlib.Path(destdir).mkdir(parents=True, exist_ok=True)
    touchfile = os.path.join(destdir, os.path.basename(srctemplates[0]))
    pathlib.Path(touchfile).touch()
    nowplaying.upgrades.templates.UpgradeTemplates(bundledir=bundledir, testdir=testpath)
    compare_content(srcdir, destdir, touchfile)


def test_upgrade_same(upgrade_bootstrap):  # pylint: disable=redefined-outer-name,too-many-locals
    """if a file already exists it shouldn't get .new'd"""
    (testpath, config) = upgrade_bootstrap
    bundledir = config.getbundledir()
    srcdir = os.path.join(bundledir, "templates")
    destdir = os.path.join(testpath, "testsuite", "templates")
    srctemplates = os.listdir(srcdir)
    pathlib.Path(destdir).mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        os.path.join(srcdir, srctemplates[1]),
        os.path.join(destdir, os.path.basename(srctemplates[1])),
    )
    nowplaying.upgrades.templates.UpgradeTemplates(bundledir=bundledir, testdir=testpath)
    compare_content(srcdir, destdir)


def test_upgrade_old(upgrade_bootstrap, getroot):  # pylint: disable=redefined-outer-name,too-many-locals
    """custom .txt, .new from previous upgrade"""
    (testpath, config) = upgrade_bootstrap
    bundledir = config.getbundledir()
    srcdir = os.path.join(bundledir, "templates")
    destdir = os.path.join(testpath, "testsuite", "templates")
    pathlib.Path(destdir).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        os.path.join(getroot, "tests", "templates", "songquotes.txt"),
        os.path.join(destdir, "songquotes.new"),
    )
    touchfile = os.path.join(destdir, "songquotes.txt")
    pathlib.Path(touchfile).touch()
    nowplaying.upgrades.templates.UpgradeTemplates(bundledir=bundledir, testdir=testpath)
    assert _compare_files(
        os.path.join(srcdir, "songquotes.txt"), os.path.join(destdir, "songquotes.new")
    )
    compare_content(srcdir, destdir, conflict=touchfile)


def test_upgrade_subdirectories(upgrade_bootstrap):  # pylint: disable=redefined-outer-name
    """test that subdirectories are properly handled"""
    (testpath, config) = upgrade_bootstrap
    bundledir = config.getbundledir()
    nowplaying.upgrades.templates.UpgradeTemplates(bundledir=bundledir, testdir=testpath)

    # Check that oauth subdirectory was created
    oauth_destdir = os.path.join(testpath, "testsuite", "templates", "oauth")
    assert os.path.isdir(oauth_destdir), "oauth subdirectory should be created"

    # Check that files in oauth subdirectory were copied
    oauth_files = os.listdir(oauth_destdir)
    assert len(oauth_files) > 0, "oauth subdirectory should contain files"

    # Verify specific oauth template files exist
    expected_oauth_files = [
        "kick_oauth_csrf_error.htm",
        "kick_oauth_error.htm",
        "kick_oauth_invalid_session.htm",
        "kick_oauth_no_code.htm",
        "kick_oauth_success.htm",
        "kick_oauth_token_error.htm",
    ]

    for expected_file in expected_oauth_files:
        oauth_file_path = os.path.join(oauth_destdir, expected_file)
        assert os.path.isfile(oauth_file_path), (
            f"Expected {expected_file} to exist in oauth subdirectory"
        )

        # Verify content matches source
        src_file_path = os.path.join(bundledir, "templates", "oauth", expected_file)
        with open(src_file_path, "r", encoding="utf-8") as src_file:
            src_content = src_file.read()
        with open(oauth_file_path, "r", encoding="utf-8") as dest_file:
            dest_content = dest_file.read()
        assert src_content == dest_content, f"Content mismatch for {expected_file}"
