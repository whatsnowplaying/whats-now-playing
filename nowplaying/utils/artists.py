#!/usr/bin/env python3
"""Utilities for artist name splitting and normalization"""

import re

# Artist collaboration delimiters for multi-artist string splitting
# Ordered by specificity: most specific first to avoid false splits on band names
HIGH_SPECIFICITY_DELIMITERS = [
    " presents ",
    " feat. ",
    " featuring ",
    " ft. ",
    " feat ",
    " vs. ",
    " versus ",
    " vs ",
]

MEDIUM_SPECIFICITY_DELIMITERS = [
    " with ",
    " w/ ",
    " x ",
    " × ",
]

LOW_SPECIFICITY_DELIMITERS = [
    " & ",
    " and ",
]

COLLABORATION_DELIMITERS_BY_PRIORITY = (
    HIGH_SPECIFICITY_DELIMITERS + MEDIUM_SPECIFICITY_DELIMITERS + LOW_SPECIFICITY_DELIMITERS
)


def split_artist_string(artist_string: str) -> list[str]:  # pylint: disable=too-many-locals
    """
    Split an artist string into individual artist names using collaboration delimiters.

    Uses positional detection to handle cases like "Artist1, Artist2 & Artist3" correctly
    by splitting on the comma (earlier position) rather than & (later position).
    Prioritizes more specific delimiters (feat., vs.) over ambiguous ones (&, and).
    """
    if not artist_string or not artist_string.strip():
        return [artist_string]

    delimiter_positions = []

    for delimiter in COLLABORATION_DELIMITERS_BY_PRIORITY:
        pattern = re.compile(r"\s+" + re.escape(delimiter.strip()) + r"\s+", re.IGNORECASE)
        for match in pattern.finditer(artist_string):
            delimiter_positions.append((match.start(), delimiter, match))

    if "," in artist_string:
        for i, char in enumerate(artist_string):
            if char == ",":
                delimiter_positions.append((i, " , ", None))

    if not delimiter_positions:
        return [artist_string]

    def sort_key(item):
        position, delimiter, _ = item
        if delimiter == " , ":
            priority = 7  # Between vs and with
        else:
            try:
                priority = COLLABORATION_DELIMITERS_BY_PRIORITY.index(delimiter)
            except ValueError:
                priority = 999
        return (priority, position)

    delimiter_positions.sort(key=sort_key)

    _, first_delimiter, match_obj = delimiter_positions[0]

    if first_delimiter == " , ":
        comma_pos = artist_string.find(",")
        if comma_pos != -1:
            parts = [
                artist_string[:comma_pos].strip(),
                artist_string[comma_pos + 1 :].strip(),
            ]
            parts = [p for p in parts if p]
            if len(parts) > 1 and all(len(p) >= 3 for p in parts):
                return parts
    else:
        if match_obj:
            split_start = match_obj.start()
            split_end = match_obj.end()
            part1 = artist_string[:split_start].strip()
            part2 = artist_string[split_end:].strip()
            if part1 and part2 and len(part1) >= 3 and len(part2) >= 3:
                return [part1, part2]

    return [artist_string]
