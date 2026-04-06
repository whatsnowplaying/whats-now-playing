#!/usr/bin/env python3
"""Utility helpers for working with TrackMetadata dicts."""

import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nowplaying.types import TrackMetadata


def get_best_year(metadata: "TrackMetadata") -> int | None:
    """Return the most authoritative release year from metadata as an integer.

    Checks originalyear first (set by tinytag when the original release year
    differs from the remaster date), then date, then year.  All three fields
    may hold a full date string (YYYY-MM-DD) or just a year (YYYY); only the
    four-digit year portion is returned.
    """
    for field in ("originalyear", "date", "year"):
        if raw := metadata.get(field):
            with contextlib.suppress(ValueError, TypeError):
                return int(str(raw).split("-", maxsplit=1)[0])
    return None
