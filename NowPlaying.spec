#!/usr/bin/env python3
''' PyInstaller spec file '''

# pylint: disable=invalid-name

import datetime
import os
import platform
import sys

from PyInstaller.utils.hooks import collect_submodules

sys.path.insert(0, os.path.abspath('.'))

from nowplaying.version import __VERSION__
import pyinstaller_versionfile

NUMERICDATE = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
WINVERSFILE = os.path.join('bincomponents', 'winvers.bin')

ARTEXTRAS_MODULES = collect_submodules('nowplaying.artistextras')
INPUT_MODULES = collect_submodules('nowplaying.inputs')
RECOGNITION_MODULES = collect_submodules('nowplaying.recognition')


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
    cleanversion = __VERSION__.replace('+', '.')
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
    short = '.'.join(getsplitversion()[:3])
    print(f'CFBundleShortVersionString = {short}')
    return short


def osxcopyright():
    ''' put actual version in copyright so users
        Get Info in Finder to get it '''
    return __VERSION__


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
        'file_description': 'NowPlaying',
        'internal_name': 'NowPlaying',
        'legal_copyright':
        f'{__VERSION__} (c) 2020-2021 Ely Miranda, (c) 2021-2023 Allen Wittenauer',
        'original_filename': 'NowPlaying.exe',
        'product_name': 'Now Playing',
        'version': '.'.join(getsplitversion()[:3] + ['0'])
    }
    pyinstaller_versionfile.create_versionfile(**rawmetadata)


block_cipher = None

executables = {
    'NowPlaying': 'nppyi.py',
    #BEAM    'NowPlayingBeam': 'beam.py',
}

for execname, execpy in executables.items():

    a = Analysis([execpy],
                 pathex=['.'],
                 binaries=[],
                 datas=[('nowplaying/resources/*', 'resources/'),
                        ('nowplaying/templates/*', 'templates/')],
                 hiddenimports=ARTEXTRAS_MODULES + INPUT_MODULES +
                 RECOGNITION_MODULES,
                 hookspath=[('nowplaying/__pyinstaller')],
                 runtime_hooks=[],
                 excludes=[],
                 win_no_prefer_redirects=False,
                 win_private_assemblies=False,
                 cipher=block_cipher,
                 noarchive=False)

    if sys.platform != 'darwin':
        splash = Splash('docs/images/meerkatdj_256x256.png',
                        binaries=a.binaries,
                        datas=a.datas,
                        text_pos=(10, 50),
                        text_size=12,
                        text_color='black')

    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # pylint: disable=undefined-variable

    if sys.platform == 'darwin':
        exe = EXE(  # pylint: disable=undefined-variable
            pyz,
            a.scripts,
            [],
            exclude_binaries=True,
            name=execname,
            debug=False,
            bootloader_ignore_signals=False,
            strip=False,
            upx=True,
            #console=False,
            icon=f'bincomponents/{geticon()}')
        coll = COLLECT(  # pylint: disable=undefined-variable
            exe,
            a.binaries,
            a.zipfiles,
            a.datas,
            strip=False,
            upx=True,
            upx_exclude=[],
            name=execname)
        app = BUNDLE( # pylint: disable=undefined-variable
            coll,
            name=f'{execname}.app',
            icon=f'bincomponents/{geticon()}',
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
            name=execname,
            debug=False,
            bootloader_ignore_signals=False,
            strip=False,
            upx=True,
            upx_exclude=[],
            runtime_tmpdir=None,
            console=False,
            version=WINVERSFILE,
            icon=f'bincomponents/{geticon()}')
        os.unlink(WINVERSFILE)
