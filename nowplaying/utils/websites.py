#!/usr/bin/env python3
"""merge artistwebsites lists, deduplicating by resource rather than string"""

import re

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def canonical_key(url: str) -> str:
    """Comparison key identifying the resource a URL points at."""
    key = _SCHEME.sub("", url.strip().lower())
    if key.startswith("www."):
        key = key[4:]
    return key.rstrip("/")


def merge_websites(*sources) -> list[str]:
    """Combine website lists, keeping one spelling per resource, https preferred."""
    chosen: dict[str, str] = {}
    for source in sources:
        for url in source or []:
            if not url or not isinstance(url, str):
                continue
            stripped = url.strip()
            key = canonical_key(stripped)
            if not key:
                continue
            current = chosen.get(key)
            if current is None or (
                current.startswith("http://") and stripped.startswith("https://")
            ):
                chosen[key] = stripped
    return list(chosen.values())
