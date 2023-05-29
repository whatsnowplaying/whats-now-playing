#!/usr/bin/env python3
''' handle frozen entry points '''

import os
import ssl
import sys
import typing as t


def frozen_init(bundledir: t.Optional[str]) -> str:
    ''' do some frozen handling '''

    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        if not bundledir:
            bundledir: str = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
        #
        # Under PyInstaller, always use our CA File
        #
        # See https://github.com/pyinstaller/pyinstaller/issues/7229 and related issues
        #
        if ssl.get_default_verify_paths().cafile is None:
            os.environ['SSL_CERT_FILE'] = os.path.join(
                sys._MEIPASS,  # pylint: disable=protected-access
                'certifi',
                'cacert.pem')
    if not bundledir:
        bundledir: str = os.path.abspath(os.path.dirname(__file__))
    return bundledir
