#!/usr/bin/env python3
"""test m3u"""

import base64
import gzip
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
from nowplaying.utils.checksum import EXCLUDED_FILES  # pylint: disable=import-error

# pylint: disable=line-too-long

# Compressed test template content for line ending tests
# basic-web.htm with LF endings (version 4.1.0-rc3)
BASIC_WEB_HTM_GZ = "H4sIAHLi5WgC/41TTXObMBC98ytUJZ7gAx+uW0+GCGZ67KmX/gFFWhmlIBFJpKEe/nsF2DjgQ6uDWO3bt2L3rcgnrpnrGkClq6siIMMHVVQdcwwKF4H3AOVFgPwiNTiKWEmNBZfj1onoEXuiayJ4beVbjg0IA7bEiGnlQPmgfYrPZCddBcXPYWfUcJJMjgm0rrvYw+LyDZ3m07Bqao5SZWjfvD8tgN+SuzJDu0OariEubVPRLkNKK1hCJchj6Xy6W5aoNPWIGQJWiC8qsvIPZOjL4w1tAAWtZeUvtFTZyIKR4hrUB7N55y5dWFX5TNmvo9Gt4hHTlTYZuhNCLC+6AGmaLgEH7y6Sivu+Z+jr5uZmknzoMrHMyMYha1iOBwltliRMc4hfXlswXcx0nUxmtI8P8S5+sbjwKUaaH5RkmouAPGvenXMOskme47k8fJX0tEFSoBFBm352k2YaiQydTme070nSLIiguOd+YE3JqHHSulW2b6NzTHfG/5GPJP63F025xt6H/nm0te/oNja+3i4UrWJOahVuV9Ldhw9XWR+2MQc/euHOq7SNBeXwXYWfh8PTf7AOM+tH69a03tsXPWcxJhEGVcZn/Bd10ME51wMAAA=="

# ws-mtv-cover-fade.htm with CRLF endings (version 3.1.2)
WS_MTV_COVER_FADE_HTM_GZ = "H4sIAHLi5WgC/6VWW2/rNgx+H7D/wKkbkqAndnLaZG0u3cN2il260wENMAzYiyLTsXpsy7OUpFmR/z5KTpw4jdMWM9DGEr+PpCiS5uibn+5/nPz1xyf4efL73c3XX40ik8T0CwCjCHlQvNpVgoaDiHiu0YzZ3ITtKwY7sZEmxpuJ/S94Hoz8YqOUxzL9AlGO4ZhFxmR64PvB1FMp7eMSp6FKjfaESnzhB9i7CgMxvb76eH3Nv++HQgQXoiOml9jjfdH5IeSJjFfj3/gUYwY5xmOmzSpGHSEaBmaV4ZgZfDK+0Jr5OyccqlzSQxZTw8mFHJ73tgESns9kOoBu9jSsCJYyMNEAPvY6nUNRhHIWGZK9FIWx4iSJMTQHArLf1vJfHMBF/wXLCovDDoAVx60ibPTaW7sXne+qUhuCto54oJYDuMye3N9Zxz1VpFCxygdwdnt7e0SFTANMyUC3on+9H8c0kwmfYV0U3x6QhD+VB+pev+AlMj0l3twOnxt11NWRX02BkRa5zAzoXOzyUqgAvcd/5pivXEYWr+0Lr+91vUfNbkiLozk1I39XJ6OpClb0WqoP5AJEzLUeszLTGMiA0nNbKWw/H/cJm5AWcKEWxCTLBKgQshvHsRieG6nNFjTyszqgs/0GHI+n8+QNuNhl5hHc1t3DcNsKhTEUNfrIF7zYr4TCJsk8FUaqFLShszWpTWglvqB5wJyicacEt9JWNec2j+/DHRqYa1AZpsCB2FDQj8EXPIelJp+oG8GfOH1wyFqTw92Z9p+lpo7m7I1L55stOOqgq7pUqxi9WM2aDbJO6xSFwaDRGh6jrE+ZTVBrW4E7y9DEBdVtvX17aNvWA06tfQy/Ptx/9jLb4AuiZ/ePe3Lg/FaJ5zKrlmLtyWRGpgIl5ok1IXLkBj/FaFdNRlLWqmGTzKM6JXbD2hq46vCzdDacco39yw8NOC+P47mCcZBCOjyh1RXcZ564nNyWXQ3+22bjrKzdRsuLZIDNWpdDOIxN7WU43eysKHTSS9/hJjlXG8wNvqjlDb7xN2ucVw2e273XlGw6x0ZLqaDYfpXsusQLrt19jVo0jkOq2z1Nrd5BgDFfNemz22l5IQ/wl7RYvFtFt1PquJ+b00rWgLHGd11no/G+23znvb0Bv39Vr8Mr13MCvv7ftXKys4lYaax01LqgU9Of5CswiobCTTMFmUIPtF0GuoZGE+1EJqjoyvdsnP7orD9AryY91gd768Oz2bbAyo8Msy4uacZSy2PdoXCDLe1k8vwMkdJGZrBeD+yCJpZM5YaW/lJrQ800Oeyfe9b35pZiXPE38wrNMHbs/w+LPi/iDgwAAA=="


@pytest.fixture
def test_templates_with_line_endings(tmp_path):
    """Create temporary test template files with specific line endings"""
    # Decompress and write basic-web.htm with LF endings
    unix_file = tmp_path / "basic-web.htm"
    unix_content = gzip.decompress(base64.b64decode(BASIC_WEB_HTM_GZ))
    unix_file.write_bytes(unix_content)

    # Decompress and write ws-mtv-cover-fade.htm with CRLF endings
    windows_file = tmp_path / "ws-mtv-cover-fade.htm"
    windows_content = gzip.decompress(base64.b64decode(WS_MTV_COVER_FADE_HTM_GZ))
    windows_file.write_bytes(windows_content)

    return {"unix": str(unix_file), "windows": str(windows_file)}


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

        # Skip files that are excluded from processing
        if filename in EXCLUDED_FILES:
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


def test_template_version_identification_with_line_endings(  # pylint: disable=too-many-locals,redefined-outer-name
    getroot, test_templates_with_line_endings
):
    """test that we can identify template versions regardless of line endings"""
    # Get test template files from fixture
    unix_file = test_templates_with_line_endings["unix"]
    windows_file = test_templates_with_line_endings["windows"]

    # Calculate checksums using our normalized function
    unix_checksum = nowplaying.utils.checksum.checksum(unix_file)
    windows_checksum = nowplaying.utils.checksum.checksum(windows_file)

    # Verify checksums are valid SHA512 hashes
    assert isinstance(unix_checksum, str), "Unix file checksum should be a string"
    assert isinstance(windows_checksum, str), "Windows file checksum should be a string"
    assert len(unix_checksum) == 128, f"SHA512 should be 128 chars, got {len(unix_checksum)}"
    assert len(windows_checksum) == 128, f"SHA512 should be 128 chars, got {len(windows_checksum)}"

    # Read raw binary content to check for line ending differences
    with open(unix_file, "rb") as unix_fh:
        unix_raw = unix_fh.read()
    with open(windows_file, "rb") as windows_fh:
        windows_raw = windows_fh.read()

    # Verify files have different line endings (for test validity)
    unix_has_crlf = b"\r\n" in unix_raw
    windows_has_crlf = b"\r\n" in windows_raw
    assert not unix_has_crlf, "Unix test file should not have CRLF line endings"
    assert windows_has_crlf, "Windows test file should have CRLF line endings"

    # Load the existing SHA database to see if we can match these checksums
    # This simulates the upgrade process trying to identify template versions
    shas_file = os.path.join(getroot, "nowplaying", "resources", "updateshas.json")
    if os.path.exists(shas_file):
        with open(shas_file, encoding="utf-8") as shas_fh:
            shas_data = json.load(shas_fh)

        # Look for matches in the SHA database
        unix_matches = []
        windows_matches = []

        for template_name, versions in shas_data.items():
            for version, sha in versions.items():
                if sha == unix_checksum:
                    unix_matches.append((template_name, version))
                if sha == windows_checksum:
                    windows_matches.append((template_name, version))

        # Verify specific version identification
        assert ("basic-web.htm", "4.1.0-rc3") in unix_matches, (
            f"basic-web.htm should be identified as version 4.1.0-rc3, got: {unix_matches}"
        )
        assert ("ws-mtv-cover-fade.htm", "3.1.2") in windows_matches, (
            f"ws-mtv-cover-fade.htm should be identified as version 3.1.2, got: {windows_matches}"
        )
    else:
        # If no SHA database exists, just verify the checksums are different
        # (since these are different template files)
        assert unix_checksum != windows_checksum, (
            "These are different template files, so checksums should differ"
        )
