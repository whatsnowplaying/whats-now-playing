#!/usr/bin/env python3
"""helpers for resetting QSettings state between tests"""

import logging
import pathlib
import subprocess
import sys


def remove_prefs_domain(filename: str | pathlib.Path) -> None:
    """Remove a QSettings store, keeping macOS's cfprefsd cache in sync.

    On every platform this unlinks the settings file.  On macOS it first drops
    the domain from cfprefsd, which caches preference domains out of process:
    unlinking a plist behind its back desynchronizes the two, so a later
    setValue()/sync() will not recreate the file because cfprefsd believes that
    state is already on disk.  The suite used to repair that by killing
    cfprefsd, but launchd holds a killed job down for its ThrottleInterval --
    10 seconds by default -- so every repair cost ten seconds, and
    tests/upgrade/ paid it several times per test.

    The `defaults` step only makes sense for NativeFormat plists, where
    QSettings names the file "<domain>.plist" so the basename is the domain.
    Anything else -- an IniFormat .ini, a plain temp file -- is only unlinked.
    Guarding on the suffix keeps a wrong domain from being handed to `defaults`
    silently, which is how the predecessor to this helper managed to do nothing
    at all for thousands of invocations.
    """
    path = pathlib.Path(filename)
    if sys.platform == "darwin" and path.suffix == ".plist":
        # capture_output is deliberate rather than incidental: `defaults delete`
        # reports "Domain not found" on stderr for an already-absent domain,
        # which is the common case here, and letting it through floods the CI
        # log with thousands of lines.  Surface it at debug level instead.
        completed = subprocess.run(
            ["defaults", "delete", path.stem],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            logging.debug(
                "defaults delete %s returned %d: %s",
                path.stem,
                completed.returncode,
                completed.stderr.strip(),
            )
    if path.exists():
        path.unlink()
