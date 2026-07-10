#!/usr/bin/env python3
"""tests for the 6.0 templates directory migration"""

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

# pylint: disable=line-too-long

# Compressed test template content for line ending tests
# basic-web.htm with LF endings (version 4.1.0-rc3)
BASIC_WEB_HTM_GZ = "H4sIAHLi5WgC/41TTXObMBC98ytUJZ7gAx+uW0+GCGZ67KmX/gFFWhmlIBFJpKEe/nsF2DjgQ6uDWO3bt2L3rcgnrpnrGkClq6siIMMHVVQdcwwKF4H3AOVFgPwiNTiKWEmNBZfj1onoEXuiayJ4beVbjg0IA7bEiGnlQPmgfYrPZCddBcXPYWfUcJJMjgm0rrvYw+LyDZ3m07Bqao5SZWjfvD8tgN+SuzJDu0OariEubVPRLkNKK1hCJchj6Xy6W5aoNPWIGQJWiC8qsvIPZOjL4w1tAAWtZeUvtFTZyIKR4hrUB7N55y5dWFX5TNmvo9Gt4hHTlTYZuhNCLC+6AGmaLgEH7y6Sivu+Z+jr5uZmknzoMrHMyMYha1iOBwltliRMc4hfXlswXcx0nUxmtI8P8S5+sbjwKUaaH5RkmouAPGvenXMOskme47k8fJX0tEFSoBFBm352k2YaiQydTme070nSLIiguOd+YE3JqHHSulW2b6NzTHfG/5GPJP63F025xt6H/nm0te/oNja+3i4UrWJOahVuV9Ldhw9XWR+2MQc/euHOq7SNBeXwXYWfh8PTf7AOM+tH69a03tsXPWcxJhEGVcZn/Bd10ME51wMAAA=="  # pragma: allowlist secret

# ws-mtv-cover-fade.htm with CRLF endings (version 3.1.2)
WS_MTV_COVER_FADE_HTM_GZ = "H4sIAHLi5WgC/6VWW2/rNgx+H7D/wKkbkqAndnLaZG0u3cN2il260wENMAzYiyLTsXpsy7OUpFmR/z5KTpw4jdMWM9DGEr+PpCiS5uibn+5/nPz1xyf4efL73c3XX40ik8T0CwCjCHlQvNpVgoaDiHiu0YzZ3ITtKwY7sZEmxpuJ/S94Hoz8YqOUxzL9AlGO4ZhFxmR64PvB1FMp7eMSp6FKjfaESnzhB9i7CgMxvb76eH3Nv++HQgQXoiOml9jjfdH5IeSJjFfj3/gUYwY5xmOmzSpGHSEaBmaV4ZgZfDK+0Jr5OyccqlzSQxZTw8mFHJ73tgESns9kOoBu9jSsCJYyMNEAPvY6nUNRhHIWGZK9FIWx4iSJMTQHArLf1vJfHMBF/wXLCovDDoAVx60ibPTaW7sXne+qUhuCto54oJYDuMye3N9Zxz1VpFCxygdwdnt7e0SFTANMyUC3on+9H8c0kwmfYV0U3x6QhD+VB+pev+AlMj0l3twOnxt11NWRX02BkRa5zAzoXOzyUqgAvcd/5pivXEYWr+0Lr+91vUfNbkiLozk1I39XJ6OpClb0WqoP5AJEzLUeszLTGMiA0nNbKWw/H/cJm5AWcKEWxCTLBKgQshvHsRieG6nNFjTyszqgs/0GHI+n8+QNuNhl5hHc1t3DcNsKhTEUNfrIF7zYr4TCJsk8FUaqFLShszWpTWglvqB5wJyicacEt9JWNec2j+/DHRqYa1AZpsCB2FDQj8EXPIelJp+oG8GfOH1wyFqTw92Z9p+lpo7m7I1L55stOOqgq7pUqxi9WM2aDbJO6xSFwaDRGh6jrE+ZTVBrW4E7y9DEBdVtvX17aNvWA06tfQy/Ptx/9jLb4AuiZ/ePe3Lg/FaJ5zKrlmLtyWRGpgIl5ok1IXLkBj/FaFdNRlLWqmGTzKM6JXbD2hq46vCzdDacco39yw8NOC+P47mCcZBCOjyh1RXcZ564nNyWXQ3+22bjrKzdRsuLZIDNWpdDOIxN7WU43eysKHTSS9/hJjlXG8wNvqjlDb7xN2ucVw2e273XlGw6x0ZLqaDYfpXsusQLrt19jVo0jkOq2z1Nrd5BgDFfNemz22l5IQ/wl7RYvFtFt1PquJ+b00rWgLHGd11no/G+23znvb0Bv39Vr8Mr13MCvv7ftXKys4lYaax01LqgU9Of5CswiobCTTMFmUIPtF0GuoZGE+1EJqjoyvdsnP7orD9AryY91gd768Oz2bbAyo8Msy4uacZSy2PdoXCDLe1k8vwMkdJGZrBeD+yCJpZM5YaW/lJrQ800Oeyfe9b35pZiXPE38wrNMHbs/w+LPi/iDgwAAA=="  # pragma: allowlist secret


@pytest.fixture
def test_templates_with_line_endings(tmp_path):
    """Create temporary test template files with specific line endings"""
    unix_file = tmp_path / "basic-web.htm"
    unix_file.write_bytes(gzip.decompress(base64.b64decode(BASIC_WEB_HTM_GZ)))

    windows_file = tmp_path / "ws-mtv-cover-fade.htm"
    windows_file.write_bytes(gzip.decompress(base64.b64decode(WS_MTV_COVER_FADE_HTM_GZ)))

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


def _templatedir(testpath) -> pathlib.Path:
    return pathlib.Path(testpath) / "testsuite" / "templates"


def _migrate(config, testpath) -> None:
    nowplaying.upgrades.templates.TemplateDirMigration(
        bundledir=config.getbundledir(), testdir=testpath
    )


def test_migration_fresh(upgrade_bootstrap):  # pylint: disable=redefined-outer-name
    """no old dir: structure and marker created, nothing archived"""
    (testpath, config) = upgrade_bootstrap
    _migrate(config, testpath)
    templatedir = _templatedir(testpath)
    assert (templatedir / nowplaying.upgrades.templates.LAYOUT_MARKER).exists()
    for subdir in nowplaying.upgrades.templates.SUBDIRS:
        assert (templatedir / subdir).is_dir()
    assert not templatedir.with_name(nowplaying.upgrades.templates.ARCHIVE_NAME).exists()


def test_migration_marker_skips(upgrade_bootstrap):  # pylint: disable=redefined-outer-name
    """already-migrated dir is left alone"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    (templatedir / nowplaying.upgrades.templates.LAYOUT_MARKER).write_text("6")
    keeper = templatedir / "twitchbot_custom.txt"
    keeper.write_text("my custom announce")
    _migrate(config, testpath)
    assert keeper.exists(), "already-migrated content must not move"
    assert not templatedir.with_name(nowplaying.upgrades.templates.ARCHIVE_NAME).exists()


def test_migration_stock_dropped(upgrade_bootstrap):  # pylint: disable=redefined-outer-name
    """an untouched stock copy is archived but not carried forward"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    stock_src = pathlib.Path(config.getbundledir()) / "templates" / "twitchbot_track.txt"
    shutil.copyfile(stock_src, templatedir / "twitchbot_track.txt")
    _migrate(config, testpath)
    archive = templatedir.with_name(nowplaying.upgrades.templates.ARCHIVE_NAME)
    assert (archive / "twitchbot_track.txt").exists(), "original must be archived"
    assert not (templatedir / "twitchbot_track.txt").exists()
    assert not (templatedir / "twitch" / "twitchbot_track.txt").exists()


@pytest.mark.parametrize(
    "filename,expected_subpath",
    [
        ("twitchbot_custom.txt", "twitch/twitchbot_custom.txt"),
        ("kickbot_custom.txt", "kick/kickbot_custom.txt"),
        ("setlist-custom.txt", "setlist/setlist-custom.txt"),
        ("myoverlay.htm", "web/myoverlay.htm"),
        ("mynotes.txt", "mynotes.txt"),
    ],
)
def test_migration_custom_carried(  # pylint: disable=redefined-outer-name
    upgrade_bootstrap, filename, expected_subpath
):
    """user files are carried into the new layout, classified by name"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    (templatedir / filename).write_text("user content that matches no ledger hash")
    _migrate(config, testpath)
    dest = templatedir / expected_subpath
    assert dest.exists(), f"{filename} should be carried to {expected_subpath}"
    assert dest.read_text() == "user content that matches no ledger hash"


@pytest.mark.parametrize(
    "relpath",
    [
        "twitchbot_track.txt.new",
        "vendor/jquery.min.js",
        ".ws-mtv.htm.swp",
        "twitchbot_track.txt~",
    ],
)
def test_migration_skips_junk(upgrade_bootstrap, relpath):  # pylint: disable=redefined-outer-name
    """.new conflict files and vendor content are not carried"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    target = templatedir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("leftover")
    _migrate(config, testpath)
    assert not list(_templatedir(testpath).rglob(pathlib.Path(relpath).name)), (
        f"{relpath} should not be carried into the new layout"
    )


@pytest.mark.parametrize(
    "relpath",
    [
        "guessgame/custom-board.htm",
        "synced/my-named-template.htm",
    ],
)
def test_migration_subdir_preserved(  # pylint: disable=redefined-outer-name
    upgrade_bootstrap, relpath
):
    """customized subdirectory content keeps its relative location"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    target = templatedir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("customized subdir content")
    _migrate(config, testpath)
    assert (_templatedir(testpath) / relpath).exists()


def test_migration_archive_collision(upgrade_bootstrap):  # pylint: disable=redefined-outer-name
    """a leftover archive from an earlier run gets a numbered suffix"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    (templatedir / "mynotes.txt").write_text("user content")
    stale_archive = templatedir.with_name(nowplaying.upgrades.templates.ARCHIVE_NAME)
    stale_archive.mkdir(parents=True)
    _migrate(config, testpath)
    assert stale_archive.with_name(f"{nowplaying.upgrades.templates.ARCHIVE_NAME}-2").exists(), (
        "second archive should get a numbered suffix"
    )
    assert (templatedir / "mynotes.txt").exists()


def test_migration_idempotent(upgrade_bootstrap):  # pylint: disable=redefined-outer-name
    """running twice must not archive or move anything the second time"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    (templatedir / "twitchbot_custom.txt").write_text("user content")
    _migrate(config, testpath)
    _migrate(config, testpath)
    archive_base = templatedir.with_name(nowplaying.upgrades.templates.ARCHIVE_NAME)
    assert archive_base.exists()
    assert not archive_base.with_name(
        f"{nowplaying.upgrades.templates.ARCHIVE_NAME}-2"
    ).exists(), "second run must not create another archive"
    assert (templatedir / "twitch" / "twitchbot_custom.txt").exists()


def test_template_version_identification_with_line_endings(  # pylint: disable=redefined-outer-name
    test_templates_with_line_endings, getroot
):
    """ledger hashes must match regardless of line endings (Unix vs Windows)"""
    unix_file = test_templates_with_line_endings["unix"]
    windows_file = test_templates_with_line_endings["windows"]

    unix_checksum = nowplaying.utils.checksum.checksum(unix_file)
    windows_checksum = nowplaying.utils.checksum.checksum(windows_file)

    assert isinstance(unix_checksum, str), "Unix file checksum should be a string"
    assert isinstance(windows_checksum, str), "Windows file checksum should be a string"
    assert len(unix_checksum) == 128, f"SHA512 should be 128 chars, got {len(unix_checksum)}"
    assert len(windows_checksum) == 128, f"SHA512 should be 128 chars, got {len(windows_checksum)}"

    shasfile = pathlib.Path(getroot) / "nowplaying" / "resources" / "updateshas.json"
    assert shasfile.exists(), "ledger must ship with 6.0 to power the migration"
    shas = json.loads(shasfile.read_text(encoding="utf-8"))

    unix_found = windows_found = False
    for versions in shas.values():
        for sha in versions.values():
            if sha == unix_checksum:
                unix_found = True
            if sha == windows_checksum:
                windows_found = True
    assert unix_found, "LF-ending template should match a ledger hash"
    assert windows_found, "CRLF-ending template should match a ledger hash"
