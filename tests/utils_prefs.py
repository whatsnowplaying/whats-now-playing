#!/usr/bin/env python3
"""helpers for resetting QSettings state between tests"""

import pathlib
import subprocess
import sys


def remove_prefs_domain(filename: str | pathlib.Path) -> None:
    """Remove a QSettings store, keeping macOS's cfprefsd cache in sync.

    macOS caches preference domains in a separate process, cfprefsd.  Unlinking
    a plist directly desynchronizes the two: cfprefsd still believes it holds
    that domain, so a later setValue()/sync() will not recreate the file.  The
    suite used to repair that by killing cfprefsd, but launchd holds a killed
    job down for its ThrottleInterval -- 10 seconds by default -- so every
    repair cost ten seconds, and tests/upgrade/ paid it several times per test.

    Deleting through `defaults` drops the domain from cfprefsd first, after
    which unlinking cannot desynchronize anything and no restart is needed.
    """
    path = pathlib.Path(filename)
    if sys.platform == "darwin":
        # A plist's basename is its preference domain.
        subprocess.run(["defaults", "delete", path.stem], check=False, capture_output=True)
    if path.exists():
        path.unlink()
