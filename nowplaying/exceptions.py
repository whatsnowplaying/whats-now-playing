#!/usr/bin/env python3
"""Internal exceptions"""


class PluginVerifyError(Exception):
    """Exception raised when a plugin's verify_settingsui
    needs to fail"""

    def __init__(self, message: str | None = None):
        self.message = message
        super().__init__(self.message)


class ToxicContentError(Exception):
    """Content was refused because it is not what its data_type says it is.

    Raised rather than returned so a caller cannot quietly keep hold of the
    payload: whatever handed these bytes over should discard them, not just note
    that caching failed.  Distinct from an operational failure -- a lock timeout
    should not make a track lose its artwork, but a non-image posing as artwork
    should never reach a template or a response body.
    """

    def __init__(self, message: str | None = None):
        self.message = message
        super().__init__(self.message)
