#!/usr/bin/env python3
''' versioneer doesn't work for pyinstaller+windows for some reason so
    this code is a hack to work around it '''

import os
import nowplaying.version


def main():
    ''' hack '''
    official = nowplaying.version.get_versions()
    filename = os.path.join('nowplaying', 'version.py')
    os.unlink(filename)

    routine = f'''
def get_versions():
    return {{"version": "{official['version']}",
                         "full-revisionid": "{official['full-revisionid']}",
                         "error": None,
                         "dirty": {official['dirty']},
                "date": "{official['date']}"}}

  '''

    with open(filename, 'w') as fileh:
        fileh.write(routine)


if __name__ == "__main__":
    main()
