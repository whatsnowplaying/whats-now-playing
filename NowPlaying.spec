#!/usr/bin/env python3
''' PyInstaller spec file '''

# pylint: disable=invalid-name

import datetime
import os
import platform
import sys


from PyInstaller.utils.hooks import collect_submodules

sys.path.insert(0, os.path.abspath('.'))


import pyinstaller_versionfile
import nowplaying.version

NUMERICDATE = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
VERSION = nowplaying.version.get_versions()['version']
WINVERSFILE = os.path.join('bincomponents', 'winvers.bin')

INPUT_MODULES = collect_submodules('nowplaying.inputs')

def geticon():
    ''' get the icon for this platform '''
    if sys.platform == 'win32':
        return 'windows.ico'

    if sys.platform == 'darwin':
        return 'osx.icns'

    # go ahead and return the windows icon
    # and hope for the best
    return 'windows.ico'


def getsplitversion():
    ''' os x has weird rules about version numbers sooo... '''
    cleanversion = VERSION.replace('+', '.')
    versionparts = cleanversion.split('.')
    try:
        versionparts.remove('dirty')
    except ValueError:
        pass
    if 'v' in versionparts[0]:
        versionparts[0] = versionparts[0][1:]
    if '-' in versionparts[2]:
        versionparts[2] = versionparts[2].split('-')[0]
    if len(versionparts) > 5:
        versionparts[5] = int(versionparts[5][1:], 16)
    return versionparts


def getcfbundleversion():
    ''' MAJOR.MINOR.MICRO.DATE.(cleaned up git describe in decimal) '''
    versionparts = getsplitversion()
    if len(versionparts) > 3:
        vers = '.'.join([NUMERICDATE] + versionparts[4:])
    else:
        vers = '.'.join([NUMERICDATE])
    print(f'CFBundleVersion = {vers}')
    return vers


def getcfbundleshortversionstring():
    ''' MAJOR.MINOR.MICRO '''
    short = '.'.join(getsplitversion()[0:3])
    print(f'CFBundleShortVersionString = {short}')
    return short


def osxcopyright():
    ''' put actual version in copyright so users
        Get Info in Finder to get it '''
    return VERSION


def osxminimumversion():
    ''' Prevent running binaries on incompatible
        versions '''
    return platform.mac_ver()[0]


def windows_version_file():
    ''' create a windows version file
        version field: MAJOR.MINOR.MICRO.0
        copyright: actual version
        '''

    rawmetadata = {
        'output_file': WINVERSFILE,
        'company_name': 'NowPlaying',
        'file_description':
        'Titling for DJs - https://github.com/aw-was-here/Now-Playing-Serato',
        'internal_name': 'NowPlaying',
        'legal_copyright':
        f'{VERSION} (c) 2020-2021 Ely Miranda, (c) 2021 Allen Wittenauer',
        'original_filename': 'NowPlaying.exe',
        'product_name': 'Now Playing',
        'version': '.'.join(getsplitversion()[0:3] + ['0'])
    }
    pyinstaller_versionfile.create_versionfile(**rawmetadata)


block_cipher = None

a = Analysis(['nppyi.py'],
             pathex=['.'],
             binaries=[],
             datas=[('nowplaying/resources/*', 'resources/'),
                    ('nowplaying/templates/*', 'templates/')],
             hiddenimports=INPUT_MODULES,
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # pylint: disable=undefined-variable

if sys.platform == 'darwin':
    exe = EXE(  # pylint: disable=undefined-variable
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='NowPlaying',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        #console=False,
        icon='bincomponents/' + geticon())
    coll = COLLECT(  # pylint: disable=undefined-variable
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='NowPlaying')
    app = BUNDLE( # pylint: disable=undefined-variable
        coll,
        name='NowPlaying.app',
        icon='bincomponents/' + geticon(),
        bundle_identifier=None,
        info_plist={
            'CFBundleDisplayName': 'NowPlaying',
            'CFBundleName': 'NowPlaying',
            'CFBundleShortVersionString': getcfbundleshortversionstring(),
            'CFBundleVersion': getcfbundleversion(),
            'LSMinimumSystemVersion': osxminimumversion(),
            'LSUIElement': True,
            'NSHumanReadableCopyright': osxcopyright()
        })

else:
    windows_version_file()
    exe = EXE(  # pylint: disable=undefined-variable
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas, [],
        name='NowPlaying',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        version=WINVERSFILE,
        icon='bincomponents/' + geticon())
    os.unlink(WINVERSFILE)
