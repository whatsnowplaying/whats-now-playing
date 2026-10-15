#!/usr/bin/env python3
"""merge artistwebsites lists, deduplicating by resource rather than string"""

import re

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_AUTHORITY_END = re.compile(r"[/?#]")


def canonical_key(url: str) -> str:
    """Comparison key identifying the resource a URL points at.

    Only the host folds case; paths are case-sensitive, and wikidata puts a
    capital in one (/wiki/Q175195).
    """
    key = _SCHEME.sub("", url.strip())
    end = _AUTHORITY_END.search(key)
    cut = end.start() if end else len(key)
    host = key[:cut].lower()
    if host.startswith("www."):
        host = host[4:]
    return (host + key[cut:]).rstrip("/")


def _is_https(url: str) -> bool:
    return url[:8].lower() == "https://"


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
            if current is None or (not _is_https(current) and _is_https(stripped)):
                chosen[key] = stripped
    return list(chosen.values())
