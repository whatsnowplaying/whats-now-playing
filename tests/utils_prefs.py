#!/usr/bin/env python3
"""helpers for resetting QSettings state between tests"""

import logging
import pathlib
import subprocess
import sys


def remove_prefs_domain(filename: str | pathlib.Path) -> None:
    """Remove a QSettings store, keeping macOS's cfprefsd cache in sync.

    Everywhere: unlink the file.  On macOS, drop the domain from cfprefsd first.
    It caches preference domains out of process, so unlinking a plist behind its
    back leaves the two disagreeing and a later setValue()/sync() will not
    recreate the file.  Do not "fix" that by killing cfprefsd -- launchd holds a
    killed job down for its ThrottleInterval, ten seconds by default.

    The `defaults` step applies only to NativeFormat plists, where QSettings
    names the file "<domain>.plist" so the basename is the domain.  Anything
    else is only unlinked; passing `defaults` a name that is not a domain fails
    silently.
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
