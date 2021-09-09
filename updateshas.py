#!/usr/bin/env python3
''' build a new upgradetable.py '''

import hashlib
import json
import os
import pathlib
import sys
import subprocess


def checksum(filename):  # pylint: disable=no-self-use
    ''' generate sha512 '''
    hashfunc = hashlib.sha512()
    with open(filename, 'rb') as fileh:
        while chunk := fileh.read(128 * hashfunc.block_size):
            hashfunc.update(chunk)
    return hashfunc.hexdigest()


def main():
    ''' build a new file '''

    shafile = sys.argv[1]
    oldshas = {}

    if os.path.exists(shafile):
        with open(shafile) as fhin:
            oldshas = json.loads(fhin.read())

    for version in sys.argv[2:]:
        subprocess.check_call(['git', 'checkout', '--force', version])
        for apppath in pathlib.Path(os.path.join('nowplaying',
                                                 'templates')).iterdir():
            filename = os.path.basename(apppath)
            if filename not in oldshas:
                oldshas[filename] = {}
            hexd = checksum(apppath)
            try:
                for vers, sha in oldshas[filename].items():  # pylint: disable=unused-variable
                    if sha == hexd:
                        raise ValueError
            except ValueError:
                continue

            oldshas[filename][version] = hexd
    with open(shafile, 'w') as fhout:
        fhout.write(json.dumps(oldshas, indent=2))


if __name__ == '__main__':
    main()
