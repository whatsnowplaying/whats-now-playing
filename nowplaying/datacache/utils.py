"""Shared utilities for the datacache package."""

import re


def redact_url(url: str) -> str:
    """Sanitise a URL for logging by removing embedded credentials.

    Two patterns are redacted:
    - Query-param keys: api_key=, token=, apikey= and variants
    - Path-embedded numeric keys of 4+ digits, e.g. /json/523532/ (TheAudioDB)
    """
    url = re.sub(r"(?i)((?:api_?key|token|apikey)=)[^&\s]+", r"\1<redacted>", url)
    url = re.sub(r"(/(?:json|api)/)\d{4,}/", r"\1<redacted>/", url)
    return url
