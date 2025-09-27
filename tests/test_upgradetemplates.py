#!/usr/bin/env python3
"""test m3u"""

import json
import logging
import os
import pathlib
import shutil
import tempfile

import pytest

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.config  # pylint: disable=import-error
import nowplaying.upgrades.templates  # pylint: disable=import-error
import nowplaying.utils.checksum  # pylint: disable=import-error


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
                open(srcfn, encoding="utf-8") as src,
                open(destfn, encoding="utf-8") as dest,
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
    num = 1
    if srctemplates[num] == "vendor":
        num = 2
    print(srctemplates[num])
    shutil.copyfile(
        os.path.join(srcdir, srctemplates[num]),
        os.path.join(destdir, os.path.basename(srctemplates[num])),
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
        with open(src_file_path, encoding="utf-8") as src_file:
            src_content = src_file.read()
        with open(oauth_file_path, encoding="utf-8") as dest_file:
            dest_content = dest_file.read()
        assert src_content == dest_content, f"Content mismatch for {expected_file}"


def test_template_version_identification_with_line_endings(getroot):
    """test that we can identify template versions regardless of line endings"""
    # Test the template files you added with potentially different line endings
    unix_file = os.path.join(getroot, "tests", "templates", "basic-web.htm")
    windows_file = os.path.join(getroot, "tests", "templates", "ws-mtv-cover-fade.htm")

    # Verify files exist
    assert os.path.exists(unix_file), f"Test file {unix_file} not found"
    assert os.path.exists(windows_file), f"Test file {windows_file} not found"

    # Calculate checksums using our normalized function
    unix_checksum = nowplaying.utils.checksum.checksum(unix_file)
    windows_checksum = nowplaying.utils.checksum.checksum(windows_file)

    # Verify checksums are valid SHA512 hashes
    assert isinstance(unix_checksum, str), "Unix file checksum should be a string"
    assert isinstance(windows_checksum, str), "Windows file checksum should be a string"
    assert len(unix_checksum) == 128, f"SHA512 should be 128 chars, got {len(unix_checksum)}"
    assert len(windows_checksum) == 128, f"SHA512 should be 128 chars, got {len(windows_checksum)}"

    # Read raw binary content to check for line ending differences
    with open(unix_file, "rb") as f:
        unix_raw = f.read()
    with open(windows_file, "rb") as f:
        windows_raw = f.read()

    # Determine if files have different line endings
    unix_has_crlf = b"\r\n" in unix_raw
    windows_has_crlf = b"\r\n" in windows_raw

    print(f"Unix file ({os.path.basename(unix_file)}) has CRLF: {unix_has_crlf}")
    print(f"Windows file ({os.path.basename(windows_file)}) has CRLF: {windows_has_crlf}")
    print(f"Unix checksum: {unix_checksum}")
    print(f"Windows checksum: {windows_checksum}")

    # Load the existing SHA database to see if we can match these checksums
    # This simulates the upgrade process trying to identify template versions
    shas_file = os.path.join(getroot, "nowplaying", "upgrades", "updateshas.json")
    if os.path.exists(shas_file):
        with open(shas_file, encoding="utf-8") as f:
            shas_data = json.load(f)

        # Look for matches in the SHA database
        unix_matches = []
        windows_matches = []

        for template_name, versions in shas_data.items():
            for version, sha in versions.items():
                if sha == unix_checksum:
                    unix_matches.append((template_name, version))
                if sha == windows_checksum:
                    windows_matches.append((template_name, version))

        print(f"Unix file matches: {unix_matches}")
        print(f"Windows file matches: {windows_matches}")

        # Test specific version identification based on known checksums
        # basic-web.htm should match version 4.1.0-rc3
        expected_unix_version = ("basic-web.htm", "4.1.0-rc3")
        assert expected_unix_version in unix_matches, (
            f"Expected {expected_unix_version} in unix_matches: {unix_matches}"
        )

        # ws-mtv-cover-fade.htm should match version 3.1.2
        expected_windows_version = ("ws-mtv-cover-fade.htm", "3.1.2")
        assert expected_windows_version in windows_matches, (
            f"Expected {expected_windows_version} in windows_matches: {windows_matches}"
        )

        # Assert the specific versions were identified correctly
        assert ("basic-web.htm", "4.1.0-rc3") in unix_matches, (
            "basic-web.htm should be identified as version 4.1.0-rc3"
        )
        assert ("ws-mtv-cover-fade.htm", "3.1.2") in windows_matches, (
            "ws-mtv-cover-fade.htm should be identified as version 3.1.2"
        )

        print(f"✓ Successfully identified basic-web.htm as version 4.1.0-rc3")
        print(f"✓ Successfully identified ws-mtv-cover-fade.htm as version 3.1.2")
        print(f"✓ Checksum normalization working correctly despite different line endings")
    else:
        # If no SHA database exists, just verify the checksums are different
        # (since these are different template files)
        assert unix_checksum != windows_checksum, (
            "These are different template files, so checksums should differ"
        )
