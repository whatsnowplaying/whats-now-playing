""" tools for the upgrade tests """

import contextlib
import os
import sys

import psutil

if sys.platform == 'darwin':
    import pwd


def reboot_macosx_prefs():
    ''' work around Mac OS X's preference caching '''
    if sys.platform == 'darwin':
        for process in psutil.process_iter():
            with contextlib.suppress(psutil.NoSuchProcess):  # Windows blows
                if 'cfprefsd' in process.name() and pwd.getpwuid(
                        os.getuid()).pw_name == process.username():
                    process.terminate()
                    process.wait()
