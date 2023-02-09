#!/usr/bin/env python3

import json
import pathlib

import pytest

import nowplaying.upgrade  # pylint: disable=import-error


@pytest.fixture
def getreleasedata(getroot):
    ''' automated integration test '''
    releasedata = pathlib.Path(getroot).joinpath('tests', 'upgrade',
                                                 'releasedata.json')
    with open(releasedata, 'r', encoding='utf-8') as fhin:
        data = json.load(fhin)
    return data


def test_simpletest():  # pylint: disable=redefined-outer-name
    upbin = nowplaying.upgrade.UpgradeBinary(testmode=True)
    assert upbin.myversion.chunk['major'] is not None
    assert upbin.myversion.chunk['minor'] is not None
    assert upbin.myversion.chunk['micro'] is not None


def test_simpleveroverride():  # pylint: disable=redefined-outer-name
    upbin = nowplaying.upgrade.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgrade.Version('0.0.0')

    assert upbin.myversion.chunk['major'] == 0
    assert upbin.myversion.chunk['minor'] == 0
    assert upbin.myversion.chunk['micro'] == 0


def test_version_1():
    ver1 = nowplaying.upgrade.Version('3.1.3')
    ver2 = nowplaying.upgrade.Version('3.1.3-rc1')

    assert ver1 > ver2
    assert not (ver1 < ver2)


def test_version_2():
    ver1 = nowplaying.upgrade.Version('3.1.3')
    ver2 = nowplaying.upgrade.Version('4.0.0')

    assert ver1 < ver2
    assert not (ver1 > ver2)


def test_version_3():
    ver1 = nowplaying.upgrade.Version('3.1.3')
    ver2 = nowplaying.upgrade.Version('4.0.0-rc1')

    assert ver1 < ver2
    assert not (ver1 > ver2)


def test_version_4():
    ver1 = nowplaying.upgrade.Version('4.0.0-rc1')
    ver2 = nowplaying.upgrade.Version('4.0.0-rc2')

    assert ver1 < ver2
    assert not (ver1 > ver2)


def test_real_getversion():
    upbin = nowplaying.upgrade.UpgradeBinary()
    assert upbin.stable
    assert upbin.stabledata['tag_name']
    assert upbin.stabledata['html_url']


def test_fake_getversion_1(getreleasedata):
    releasedata = getreleasedata
    upbin = nowplaying.upgrade.UpgradeBinary(testmode=True)
    upbin.get_versions(releasedata)
    assert str(upbin.stable) == '3.1.3'
    assert str(upbin.prerelease) == '4.0.0-rc5'


def test_fake_getversion_2(getreleasedata):
    releasedata = getreleasedata
    upbin = nowplaying.upgrade.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgrade.Version('0.0.0')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data['tag_name'] == '3.1.3'
    assert data[
        'html_url'] == "https://github.com/whatsnowplaying/whats-now-playing/releases/tag/3.1.3"


def test_fake_getversion_3(getreleasedata):
    releasedata = getreleasedata
    upbin = nowplaying.upgrade.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgrade.Version('3.1.2')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data['tag_name'] == '3.1.3'
    assert data[
        'html_url'] == "https://github.com/whatsnowplaying/whats-now-playing/releases/tag/3.1.3"


def test_fake_getversion_4(getreleasedata):
    releasedata = getreleasedata
    upbin = nowplaying.upgrade.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgrade.Version('4.0.0')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data is None


def test_fake_getversion_5(getreleasedata):
    releasedata = getreleasedata
    upbin = nowplaying.upgrade.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgrade.Version('4.0.0-rc1')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data['tag_name'] == '4.0.0-rc5'
    assert data[
        'html_url'] == "https://github.com/whatsnowplaying/whats-now-playing/releases/tag/4.0.0-rc5"


def test_fake_getversion_6(getreleasedata):
    releasedata = getreleasedata
    upbin = nowplaying.upgrade.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgrade.Version('3.0.0-rc6')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data['tag_name'] == '4.0.0-rc5'
    assert data[
        'html_url'] == "https://github.com/whatsnowplaying/whats-now-playing/releases/tag/4.0.0-rc5"
