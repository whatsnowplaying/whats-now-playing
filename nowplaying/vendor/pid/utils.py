import os
import sys
import tempfile


def effective_access(*args, **kwargs):
    if 'effective_ids' not in kwargs:
        try:
            kwargs['effective_ids'] = os.access in os.supports_effective_ids
        except AttributeError:
            pass

    return os.access(*args, **kwargs)


def determine_pid_directory():
    if sys.platform == "win32":
        if 'APPDATA' in os.environ:
            paths = [os.environ['APPDATA']]
        else:
            paths = [os.path.expanduser('~\\AppData\\Roaming')]
    else:
        uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()  # pylint: disable=no-member

        paths = [f"/run/user/{uid}/", f"/var/run/user/{uid}/", "/run/", "/var/run/", os.path.expanduser('~')]

    for path in paths:
        if effective_access(os.path.realpath(path), os.W_OK | os.X_OK):
            return path

    return tempfile.gettempdir()
