#!/usr/bin/env python3
''' PyInstaller spec file '''

# pylint: disable=invalid-name

import datetime
import os
import platform
import sys

import pkg_resources
from pyinstaller_versionfile import create_version_file
import nowplaying.version

NUMERICDATE = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
VERSION = nowplaying.version.get_versions()['version']
WINVERSFILE = os.path.join('bincomponents', 'winvers.bin')


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

    versionparts = getsplitversion()
    version = '.'.join(versionparts[0:3] + ['0'])
    rawmetadata = {
        'CompanyName': 'NowPlaying',
        'FileDescription': 'Titling for DJs - https://github.com/aw-was-here/Now-Playing-Serato',
        'InternalName': 'NowPlaying',
        'LegalCopyright': f'{VERSION} (c) 2020-2021 Ely Miranda, (c) 2021 Allen Wittenauer',
        'OriginalFilename': 'NowPlaying.exe',
        'ProductName': 'Now Playing',
        'Version': version
    }
    metadata = create_version_file.MetaData(metadata_file='fake')
    metadata._metadata = rawmetadata # pylint: disable=protected-access
    metadata._render_version_file(outfile=WINVERSFILE) # pylint: disable=protected-access

def Entrypoint(dist, group, name, **kwargs):
    ''' Calculate the location of main() '''

    # get toplevel packages of distribution from metadata
    def get_toplevel(dist):
        distribution = pkg_resources.get_distribution(dist)
        if distribution.has_metadata('top_level.txt'):
            return list(distribution.get_metadata('top_level.txt').split())
        return []

    kwargs.setdefault('hiddenimports', [])
    packages = []
    for distribution in kwargs['hiddenimports']:
        packages += get_toplevel(distribution)

    kwargs.setdefault('pathex', [])
    # get the entry point
    ep = pkg_resources.get_entry_info(dist, group, name)
    # insert path of the egg at the verify front of the search path
    kwargs['pathex'] = [ep.dist.location] + kwargs['pathex']
    # script name must not be a valid module name to avoid name clashes on import
    script_path = os.path.join(workpath, name + '-script.py')  # pylint: disable=undefined-variable
    print("creating script for entry point", dist, group, name)
    with open(script_path, 'w') as fh:
        print("import", ep.module_name, file=fh)
        print("%s.%s()" % (ep.module_name, '.'.join(ep.attrs)), file=fh)
        for package in packages:
            print("import", package, file=fh)

    return Analysis([script_path] + kwargs.get('scripts', []), **kwargs)  # pylint: disable=undefined-variable


block_cipher = None

a = Entrypoint('NowPlaying',
               'console_scripts',
               'NowPlaying',
               pathex=['..'],
               binaries=[],
               datas=[('nowplaying/resources/*', 'resources/'),
                      ('nowplaying/templates/*', 'templates/')],
               hiddenimports=[],
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
        a.scripts, [],
        exclude_binaries=True,
        name='NowPlaying',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
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
