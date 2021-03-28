import os
import sys

def geticon():
    if sys.platform == 'win32':
        return 'windows.ico'
    elif sys.platform == 'darwin':
        return 'osx.icns'
    else:
        return None


def Entrypoint(dist, group, name, **kwargs):
    import pkg_resources

    # get toplevel packages of distribution from metadata
    def get_toplevel(dist):
        distribution = pkg_resources.get_distribution(dist)
        if distribution.has_metadata('top_level.txt'):
            return list(distribution.get_metadata('top_level.txt').split())
        else:
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
    script_path = os.path.join(workpath, name + '-script.py')
    print("creating script for entry point", dist, group, name)
    with open(script_path, 'w') as fh:
        print("import", ep.module_name, file=fh)
        print("%s.%s()" % (ep.module_name, '.'.join(ep.attrs)), file=fh)
        for package in packages:
            print("import", package, file=fh)

    return Analysis([script_path] + kwargs.get('scripts', []), **kwargs)


block_cipher = None

a = Entrypoint('NowPlaying',
               'console_scripts',
               'NowPlaying',
               pathex=['..'],
               binaries=[],
               datas=[('nowplaying/resources/icon.ico', 'resources/'),
                      ('nowplaying/templates/*', 'templates/')],
               hiddenimports=[],
               hookspath=[],
               runtime_hooks=[],
               excludes=[],
               win_no_prefer_redirects=False,
               win_private_assemblies=False,
               cipher=block_cipher,
               noarchive=False)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == 'darwin':
    exe = EXE(pyz,
              a.scripts, [],
              exclude_binaries=True,
              name='NowPlaying',
              debug=False,
              bootloader_ignore_signals=False,
              strip=False,
              upx=True,
              console=False,
              icon='nowplaying/resources/'+geticon())
    coll = COLLECT(exe,
                   a.binaries,
                   a.zipfiles,
                   a.datas,
                   strip=False,
                   upx=True,
                   upx_exclude=[],
                   name='NowPlaying')
    app = BUNDLE(coll,
                 name='NowPlaying.app',
                 icon='nowplaying/resources/'+geticon(),
                 bundle_identifier=None,
                 info_plist={'LSUIElement': True})
else:
    exe = EXE(pyz,
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
              icon='nowplaying/resources/'+geticon())
