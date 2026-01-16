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

def collect_all_nowplaying_modules():
    """Automatically discover and collect all nowplaying plugin modules"""
    # Get the nowplaying package directory relative to the current working directory
    nowplaying_dir = os.path.join(os.getcwd(), 'nowplaying')

    # Find all subdirectories that contain an __init__.py (are Python packages)
    plugin_packages = []
    if os.path.exists(nowplaying_dir):
        for item in os.listdir(nowplaying_dir):
            subdir_path = os.path.join(nowplaying_dir, item)
            init_file = os.path.join(subdir_path, '__init__.py')

            if os.path.isdir(subdir_path) and os.path.exists(init_file):
                # Skip non-plugin directories
                if item not in ['vendor', '__pycache__', 'htmlcov']:
                    plugin_packages.append(f'nowplaying.{item}')

    # Collect all submodules from discovered packages
    all_modules = []
    for package in plugin_packages:
        try:
            modules = collect_submodules(package)
            all_modules.extend(modules)
            print(f'Auto-collected {len(modules)} modules from {package}')
        except Exception as e:
            print(f'Warning: Could not collect modules from {package}: {e}')

    return all_modules

ALL_PLUGIN_MODULES = collect_all_nowplaying_modules()


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
        'company_name': 'WhatsNowPlaying',
        'file_description': 'WhatsNowPlaying',
        'internal_name': 'WhatsNowPlaying',
        'legal_copyright':
        f'{__VERSION__} (c) 2020-2021 Ely Miranda, (c) 2021-2026 Allen Wittenauer',
        'original_filename': 'WhatsNowPlaying.exe',
        'product_name': 'WhatsNowPlaying',
        'version': '.'.join(getsplitversion()[:3] + ['0'])
    }
    pyinstaller_versionfile.create_versionfile(**rawmetadata)


block_cipher = None

executables = {
    'WhatsNowPlaying': 'wnppyi.py',
}

for execname, execpy in executables.items():

    a = Analysis([execpy],
                 pathex=['.'],
                 binaries=[],
                 datas=[('nowplaying/resources/*', 'resources/'),
                        ('nowplaying/templates/*', 'templates/')],
                 hiddenimports=ALL_PLUGIN_MODULES,
                 hookspath=[('nowplaying/__pyinstaller')],
                 runtime_hooks=[],
                 excludes=[
                     'tkinter', '_tkinter', 'Tkinter',
                     'tcl', 'tk', '_tcl', '_tk',
                 ],
                 win_no_prefer_redirects=False,
                 win_private_assemblies=False,
                 cipher=block_cipher,
                 noarchive=False)

    # Splash screen disabled for folder mode
    # if sys.platform != 'darwin':
    #     splash = Splash('docs/images/meerkatdj_256x256.png',
    #                     binaries=a.binaries,
    #                     datas=a.datas,
    #                     text_pos=(10, 50),
    #                     text_size=12,
    #                     text_color='black')

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
                'CFBundleDisplayName': "What's Now Playing",
                'CFBundleName': 'WhatsNowPlaying',
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
            [],
            exclude_binaries=True,
            name=execname,
            debug=False,
            bootloader_ignore_signals=False,
            strip=False,
            upx=True,
            console=False,
            version=WINVERSFILE,
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
        os.unlink(WINVERSFILE)
