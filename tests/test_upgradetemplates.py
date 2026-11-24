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
import nowplaying.utils.templatepaths  # pylint: disable=import-error

# pylint: disable=line-too-long

# Compressed test template content for line ending tests
# basic-web.htm with LF endings (version 4.1.0-rc3)
BASIC_WEB_HTM_GZ = "H4sIAHLi5WgC/41TTXObMBC98ytUJZ7gAx+uW0+GCGZ67KmX/gFFWhmlIBFJpKEe/nsF2DjgQ6uDWO3bt2L3rcgnrpnrGkClq6siIMMHVVQdcwwKF4H3AOVFgPwiNTiKWEmNBZfj1onoEXuiayJ4beVbjg0IA7bEiGnlQPmgfYrPZCddBcXPYWfUcJJMjgm0rrvYw+LyDZ3m07Bqao5SZWjfvD8tgN+SuzJDu0OariEubVPRLkNKK1hCJchj6Xy6W5aoNPWIGQJWiC8qsvIPZOjL4w1tAAWtZeUvtFTZyIKR4hrUB7N55y5dWFX5TNmvo9Gt4hHTlTYZuhNCLC+6AGmaLgEH7y6Sivu+Z+jr5uZmknzoMrHMyMYha1iOBwltliRMc4hfXlswXcx0nUxmtI8P8S5+sbjwKUaaH5RkmouAPGvenXMOskme47k8fJX0tEFSoBFBm352k2YaiQydTme070nSLIiguOd+YE3JqHHSulW2b6NzTHfG/5GPJP63F025xt6H/nm0te/oNja+3i4UrWJOahVuV9Ldhw9XWR+2MQc/euHOq7SNBeXwXYWfh8PTf7AOM+tH69a03tsXPWcxJhEGVcZn/Bd10ME51wMAAA=="  # pragma: allowlist secret

# ws-basicblack.htm with LF endings (version 4.1.0-rc3): ledger-matched retired stock
WS_BASICBLACK_HTM_GZ = "H4sIAAAAAAAC/51VUW/TMBB+7684DKitRJONsQllaV8ACaHBkFYJ8eg6l9ZbEgf72qxM/e/Ydds1abZO+CGx7+777nN8vsSvPl9/Gv/++QW+jr9fjTrxjPJs1LFv5MmoA3bEORIHMePaIA3ZnNLBR7ZxkaQMR2P3FFwncegN3mlouZ27EQhVEJcFanjYGd3IuZ7KIoLT8v6y5kgzxSmCDFOqO4TKlI5gknFxV/cQ3tOANC9MqnQewbwsUQtusB6WWRmDGcrpzPKfn7x99K46j4LXm2mITe0mBkb+xQjOLg4EO2fKc5ktI2BfMVsgScFZOz3XJA09zf/+w3/zx+Hex4+N0LIkMFoM2YyoNFEYCpVgcPtnjnppDyYP/XRwFlwEp8GtYSNLsYbZmgh9MXTiiUqW9u1ZE7kAkXFjhmx3sgxkMmS0rQf2ePpxuTffg65j92AusXXvBYflcRb/KT3NZv4kz8Ze+zS0LNEKsMUT3vIF99Y99em8ECRVAYYsfa/CiVHiDukG9QL1lRLcefuNswxDuEKCuQFVYgEcLA48sBa34BoqA0MosIJfOLlZhzyZ5bJTQ1cmUMU6wXCns9eU4m9NYVSGQaamva7NZ9cFCsKk26+X2aotQ47G8CnuJ8EFFtSWyW3IdY2E284xhG831z+C0vUPDwmcvZGzKXAL95ewJVim0AxqUeLGmx577WurH7j2dpx7i9qUUhPmzS24FWBm8KUyut0Xp24NXR0/NJEpg8fqwpbpWC+BFGjc1ATIAs7BuGViDgD2PzCWOao59Z4lXsc+e2EO9/TOtuOTk8OCbGmgrgLY7rowp7mSRaKqphavgVWu7z08wEwZkiWsVpFb2H5YKk12GVbGkEaes35LP901w00TtF1x/av8BzcyAOBCBwAA"  # pragma: allowlist secret


@pytest.fixture
def test_templates_with_line_endings(tmp_path: pathlib.Path) -> dict[str, str]:
    """Create temporary test template files with specific line endings"""
    unix_file = tmp_path / "basic-web.htm"
    unix_file.write_bytes(gzip.decompress(base64.b64decode(BASIC_WEB_HTM_GZ)))

    windows_file = tmp_path / "ws-basicblack.htm"
    windows_file.write_bytes(
        gzip.decompress(base64.b64decode(WS_BASICBLACK_HTM_GZ)).replace(b"\n", b"\r\n")
    )

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


def _migrate(
    config: nowplaying.config.ConfigFile, testpath: str
) -> nowplaying.upgrades.templates.TemplateDirMigration:
    return nowplaying.upgrades.templates.TemplateDirMigration(
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
    stock_src = pathlib.Path(config.getbundledir()) / "templates" / "twitch" / "track.txt"
    shutil.copyfile(stock_src, templatedir / "twitchbot_track.txt")
    _migrate(config, testpath)
    archive = templatedir.with_name(nowplaying.upgrades.templates.ARCHIVE_NAME)
    assert (archive / "twitchbot_track.txt").exists(), "original must be archived"
    assert not (templatedir / "twitchbot_track.txt").exists()
    assert not (templatedir / "twitch" / "twitchbot_track.txt").exists()


@pytest.mark.parametrize(
    "filename,expected_subpath",
    [
        ("twitchbot_custom.txt", "twitch/custom.txt"),
        ("kickbot_custom.txt", "kick/custom.txt"),
        ("setlist-custom.txt", "plain/setlist-custom.txt"),
        ("myoverlay.htm", "web/myoverlay.htm"),
        ("mynotes.txt", "plain/mynotes.txt"),
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
        ".ws-basicblack.htm.swp",
        "twitchbot_track.txt~",
    ],
)
def test_migration_skips_junk(  # pylint: disable=redefined-outer-name
    upgrade_bootstrap: tuple[str, nowplaying.config.ConfigFile], relpath: str
) -> None:
    """.new conflict files and editor leftovers are not carried"""
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
    assert (templatedir / "plain" / "mynotes.txt").exists()


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
    assert (templatedir / "twitch" / "custom.txt").exists()


def test_migration_repoints_retired_stock(  # pylint: disable=redefined-outer-name
    upgrade_bootstrap: tuple[str, nowplaying.config.ConfigFile],
) -> None:
    """unmodified retired stock is dropped and config keys repoint to the successor"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    old_path = templatedir / "ws-basicblack.htm"
    old_path.write_bytes(gzip.decompress(base64.b64decode(WS_BASICBLACK_HTM_GZ)))
    config.cparser.setValue("weboutput/htmltemplate", str(old_path))
    config.cparser.sync()

    _migrate(config, testpath)

    config.cparser.sync()
    assert config.cparser.value("weboutput/htmltemplate") == "ws-basic-text.htm"
    assert not (templatedir / "web" / "ws-basicblack.htm").exists()


@pytest.mark.parametrize("custom", [False, True])
def test_migration_vendor_carries_only_unbundled(  # pylint: disable=redefined-outer-name
    upgrade_bootstrap: tuple[str, nowplaying.config.ConfigFile],
    tmp_path: pathlib.Path,
    custom: bool,
) -> None:
    """vendor files the bundle lacks are carried silently; bundle-shipped ones are not"""
    (testpath, _config) = upgrade_bootstrap
    bundledir = tmp_path / "bundle"
    (bundledir / "templates" / "vendor").mkdir(parents=True)
    (bundledir / "templates" / "vendor" / "jquery.min.js").write_text("bundled")
    templatedir = _templatedir(testpath)
    (templatedir / "vendor").mkdir(parents=True)
    (templatedir / "vendor" / "userfont.woff2").write_bytes(b"user font")
    (templatedir / "vendor" / "jquery.min.js").write_text("old copy")
    if custom:
        (templatedir / "myoverlay.htm").write_text("<html>my overlay</html>")

    migration = nowplaying.upgrades.templates.TemplateDirMigration(
        bundledir=bundledir, testdir=testpath
    )

    assert (templatedir / "vendor" / "userfont.woff2").read_bytes() == b"user font"
    assert not (templatedir / "vendor" / "jquery.min.js").exists()
    assert migration.kept == [str(pathlib.Path("vendor", "userfont.woff2"))]
    # the notice fires only for customized files, never for a vendor carry
    assert migration.carried == (["myoverlay.htm"] if custom else [])


@pytest.mark.parametrize(
    "oldname,expected",
    [
        ("ws-cover-title-artist.htm", "ws-generic-dj.htm"),
        ("ws-basicblack.htm", "ws-basic-text.htm"),
        ("ws-frosted-glass.htm", "ws-frosted-glass.htm"),
    ],
)
def test_migration_repoints_retired_by_name(  # pylint: disable=redefined-outer-name
    upgrade_bootstrap: tuple[str, nowplaying.config.ConfigFile], oldname: str, expected: str
) -> None:
    """a bare reference to a retired name that no longer ships is repointed"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    (templatedir / "mynotes.txt").write_text("user content")
    config.cparser.setValue("weboutput/htmltemplate", oldname)
    config.cparser.sync()

    _migrate(config, testpath)

    config.cparser.sync()
    assert config.cparser.value("weboutput/htmltemplate") == expected


def test_migration_keeps_reference_to_modified_retired(  # pylint: disable=redefined-outer-name
    upgrade_bootstrap: tuple[str, nowplaying.config.ConfigFile], monkeypatch: pytest.MonkeyPatch
) -> None:
    """a customized ws-basicblack.htm is carried, stays referenced, and still resolves"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    old_path = templatedir / "ws-basicblack.htm"
    old_path.write_text("<html>my heavily customized overlay</html>")
    config.cparser.setValue("weboutput/htmltemplate", str(old_path))
    config.cparser.sync()

    migration = _migrate(config, testpath)

    config.cparser.sync()
    value = config.cparser.value("weboutput/htmltemplate")
    assert value == str(old_path)
    carried = templatedir / "web" / "ws-basicblack.htm"
    assert carried.exists()
    assert migration.carried == ["ws-basicblack.htm"]
    monkeypatch.setattr(config, "templatedir", templatedir)
    resolved = nowplaying.utils.templatepaths.resolve_configured(config, value)
    assert resolved is not None
    assert resolved.resolve() == carried.resolve()


def test_migration_archive_failure_aborts_cleanly(  # pylint: disable=redefined-outer-name
    upgrade_bootstrap, monkeypatch
):
    """a locked directory (rename failure) must not crash startup or lose data"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    keeper = templatedir / "twitchbot_custom.txt"
    keeper.write_text("user content")

    def _locked(_operation, **_kwargs):
        raise OSError("simulated Windows sharing violation")

    monkeypatch.setattr(
        nowplaying.upgrades.templates.nowplaying.utils.sqlite, "retry_file_operation", _locked
    )
    _migrate(config, testpath)

    assert keeper.exists(), "old layout must remain intact"
    assert not (templatedir / nowplaying.upgrades.templates.LAYOUT_MARKER).exists(), (
        "marker must not be written so the migration retries next launch"
    )


def test_migration_midrun_failure_rolls_back(  # pylint: disable=redefined-outer-name
    upgrade_bootstrap, monkeypatch
):
    """a failure after archiving restores the original layout"""
    (testpath, config) = upgrade_bootstrap
    templatedir = _templatedir(testpath)
    templatedir.mkdir(parents=True)
    keeper = templatedir / "twitchbot_custom.txt"
    keeper.write_text("user content")

    def _boom(_self, _archive):
        raise OSError("simulated failure during carry")

    monkeypatch.setattr(
        nowplaying.upgrades.templates.TemplateDirMigration, "_carry_user_content", _boom
    )
    _migrate(config, testpath)

    assert keeper.exists(), "rollback must restore the original layout"
    assert not (templatedir / nowplaying.upgrades.templates.LAYOUT_MARKER).exists()
    assert not templatedir.with_name(nowplaying.upgrades.templates.ARCHIVE_NAME).exists(), (
        "archive must be renamed back on rollback"
    )


def test_template_version_identification_with_line_endings(  # pylint: disable=redefined-outer-name
    test_templates_with_line_endings: dict[str, str], getroot: pathlib.Path
) -> None:
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
