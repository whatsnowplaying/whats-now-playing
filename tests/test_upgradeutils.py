#!/usr/bin/env python3
''' test the upgrade binary features '''

import json
import pathlib

import pytest

import nowplaying.upgradeutils  # pylint: disable=import-error


@pytest.fixture
def getreleasedata(getroot):
    ''' automated integration test '''
    releasedata = pathlib.Path(getroot).joinpath('tests', 'upgrade', 'releasedata.json')
    with open(releasedata, 'r', encoding='utf-8') as fhin:
        data = json.load(fhin)
    return data


def test_simpletest():
    ''' detect current version '''
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    assert upbin.myversion.chunk['major'] is not None
    assert upbin.myversion.chunk['minor'] is not None
    assert upbin.myversion.chunk['micro'] is not None


def test_simpleveroverride():
    ''' override the detected version '''
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgradeutils.Version('0.0.0')

    assert upbin.myversion.chunk['major'] == 0
    assert upbin.myversion.chunk['minor'] == 0
    assert upbin.myversion.chunk['micro'] == 0


def test_version_1():
    ''' regular vs rc '''
    ver1 = nowplaying.upgradeutils.Version('3.1.3')
    ver2 = nowplaying.upgradeutils.Version('3.1.3-rc1')

    assert ver1 > ver2
    assert ver1 >= ver2


def test_version_2():
    ''' major comparison '''
    ver1 = nowplaying.upgradeutils.Version('3.1.3')
    ver2 = nowplaying.upgradeutils.Version('4.0.0')

    assert ver1 < ver2
    assert ver1 <= ver2


def test_version_3():
    ''' major vs major w/rc '''
    ver1 = nowplaying.upgradeutils.Version('3.1.3')
    ver2 = nowplaying.upgradeutils.Version('4.0.0-rc1')

    assert ver1 < ver2
    assert ver1 <= ver2


def test_version_4():
    ''' rc vs rc '''
    ver1 = nowplaying.upgradeutils.Version('4.0.0-rc1')
    ver2 = nowplaying.upgradeutils.Version('4.0.0-rc2')

    assert ver1 < ver2
    assert ver1 <= ver2


def test_version_equality():
    ''' test equality operators '''
    ver1 = nowplaying.upgradeutils.Version('3.1.3')
    ver2 = nowplaying.upgradeutils.Version('3.1.3')
    ver3 = nowplaying.upgradeutils.Version('3.1.4')

    # Test equality
    assert ver1 == ver2
    assert ver1 != ver3

    # Test inequality
    assert ver1 != ver3
    assert ver1 == ver2


def test_version_greater_than_equal():
    ''' test greater than or equal operators '''
    ver1 = nowplaying.upgradeutils.Version('3.1.3')
    ver2 = nowplaying.upgradeutils.Version('3.1.3')
    ver3 = nowplaying.upgradeutils.Version('3.1.2')
    ver4 = nowplaying.upgradeutils.Version('3.1.4')

    # Test greater than or equal (equal case)
    assert ver1 >= ver2
    assert ver2 >= ver1

    # Test greater than or equal (greater case)
    assert ver1 >= ver3
    assert ver3 < ver1

    # Test greater than or equal (less case)
    assert ver1 < ver4
    assert ver4 >= ver1


def test_version_less_than_equal():
    ''' test less than or equal operators '''
    ver1 = nowplaying.upgradeutils.Version('3.1.3')
    ver2 = nowplaying.upgradeutils.Version('3.1.3')
    ver3 = nowplaying.upgradeutils.Version('3.1.2')
    ver4 = nowplaying.upgradeutils.Version('3.1.4')

    # Test less than or equal (equal case)
    assert ver1 <= ver2
    assert ver2 <= ver1

    # Test less than or equal (less case)
    assert ver3 <= ver1
    assert ver1 > ver3

    # Test less than or equal (greater case)
    assert ver1 <= ver4
    assert ver4 > ver1


def test_version_greater_than():
    ''' test greater than operator '''
    ver1 = nowplaying.upgradeutils.Version('3.1.3')
    ver2 = nowplaying.upgradeutils.Version('3.1.2')
    ver3 = nowplaying.upgradeutils.Version('3.1.3')
    ver4 = nowplaying.upgradeutils.Version('3.1.4')

    # Test greater than
    assert ver1 > ver2
    assert ver2 <= ver1

    # Test not greater than (equal)
    assert ver1 <= ver3
    assert ver3 <= ver1

    # Test not greater than (less)
    assert ver1 <= ver4
    assert ver4 > ver1


def test_version_equality_with_rc():
    ''' test equality with release candidates '''
    ver1 = nowplaying.upgradeutils.Version('3.1.3-rc1')
    ver2 = nowplaying.upgradeutils.Version('3.1.3-rc1')
    ver3 = nowplaying.upgradeutils.Version('3.1.3-rc2')
    ver4 = nowplaying.upgradeutils.Version('3.1.3')

    # Test equality with rc
    assert ver1 == ver2
    assert ver1 != ver3
    assert ver1 != ver4


def test_version_equality_with_non_version():
    ''' test equality with non-Version objects '''
    ver1 = nowplaying.upgradeutils.Version('3.1.3')

    # Test equality with non-Version objects
    assert ver1 != "3.1.3"
    assert ver1 != 3.13
    assert ver1 is not None


@pytest.mark.xfail(reason="API limit exceeded may happen")
def test_real_getversion():
    ''' fetch from github '''
    upbin = nowplaying.upgradeutils.UpgradeBinary()
    assert upbin.stable
    assert upbin.stabledata['tag_name']
    assert upbin.stabledata['html_url']


def test_fake_getversion_1(getreleasedata):  # pylint: disable=redefined-outer-name
    ''' test reading static release data '''
    releasedata = getreleasedata
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    upbin.get_versions(releasedata)
    assert str(upbin.stable) == '3.1.3'
    assert str(upbin.prerelease) == '4.0.0-rc5'


def test_fake_getversion_2(getreleasedata):  # pylint: disable=redefined-outer-name
    ''' given a stable version, do we get the stable version upgrade '''
    releasedata = getreleasedata
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgradeutils.Version('0.0.0')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data['tag_name'] == '3.1.3'
    assert data[
        'html_url'] == "https://github.com/whatsnowplaying/whats-now-playing/releases/tag/3.1.3"


def test_fake_getversion_3(getreleasedata):  # pylint: disable=redefined-outer-name
    ''' test micro version '''
    releasedata = getreleasedata
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgradeutils.Version('3.1.2')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data['tag_name'] == '3.1.3'
    assert data[
        'html_url'] == "https://github.com/whatsnowplaying/whats-now-playing/releases/tag/3.1.3"


def test_fake_getversion_4(getreleasedata):  # pylint: disable=redefined-outer-name
    ''' test newer stable than release '''
    releasedata = getreleasedata
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgradeutils.Version('4.0.0')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data is None


def test_fake_getversion_5(getreleasedata):  # pylint: disable=redefined-outer-name
    ''' test old rc '''
    releasedata = getreleasedata
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgradeutils.Version('4.0.0-rc1')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data['tag_name'] == '4.0.0-rc5'
    assert data[
        'html_url'] == "https://github.com/whatsnowplaying/whats-now-playing/releases/tag/4.0.0-rc5"


def test_fake_getversion_6(getreleasedata):  # pylint: disable=redefined-outer-name
    ''' test really old major rc '''
    releasedata = getreleasedata
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgradeutils.Version('3.0.0-rc6')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data['tag_name'] == '4.0.0-rc5'
    assert data[
        'html_url'] == "https://github.com/whatsnowplaying/whats-now-playing/releases/tag/4.0.0-rc5"


def test_fake_getversion_7(getreleasedata):  # pylint: disable=redefined-outer-name
    ''' test same version '''
    releasedata = getreleasedata
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    upbin.myversion = nowplaying.upgradeutils.Version('3.1.3')

    upbin.get_versions(releasedata)
    data = upbin.get_upgrade_data()
    assert data is None


def test_fake_getversion_failuretest1():
    ''' test same version '''
    upbin = nowplaying.upgradeutils.UpgradeBinary(testmode=True)
    data = upbin.get_upgrade_data()
    assert data is None
