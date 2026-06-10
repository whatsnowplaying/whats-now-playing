#!/usr/bin/env python3
"""TSAF binary format parser for djay Pro MediaLibrary databases.

djay Pro stores track metadata as TSAF-serialised blobs in a SQLite database.
This module handles all low-level parsing so that the input plugin itself can
stay focused on database access and plugin lifecycle.

TSAF binary format
==================
- 20-byte header: b"TSAF" + 16 bytes of version/count data
- Typed value stream: a value byte precedes its key; keys are always
  null-terminated UTF-8 strings prefixed with 0x08.

Type codes:
  0x00  end-of-object marker
  0x05  2-byte skip marker / field-count hint
  0x08  null-terminated UTF-8 string
  0x0a  int16 (2-byte-aligned) — seen in contentPacks (sortOrder)
  0x0b  array (4-byte-aligned int32 count, then typed elements); elements may
        be objects (0x2b), strings (0x08/0x21), or typed key-value pairs where
        any scalar type code is followed by its value bytes then 0x08+key
  0x0c  int32 (4-byte-aligned) — seen in contentPacks / historySessions
  0x0d  boolean False (implicit 0, zero-byte) — e.g. isStraightGrid; present on
        tracks with a constant-tempo beatgrid; absent when analysis was skipped
  0x0e  boolean True (implicit 1, zero-byte) — e.g. featured in contentPacks;
        completes the 0x0d/0x0e implicit boolean pair
  0x0f  uint8 value (e.g. deckNumber on macOS)
  0x11  uint32 (4-byte-aligned) — fileSize in contentPacks
  0x12  uint64 (8-byte-aligned) — inferred; handles fileSize > 4 GB
  0x13  float32 (4-byte-aligned) — macOS only
  0x14  float64 (8-byte-aligned)
  0x15  binary blob: 4-byte-aligned uint32 length, then raw bytes
        (macOS: CFURLBookmarkData stored in urlBookmarkData)
  0x1a  uint32 (4-byte-aligned) — colorIndex in mediaItemUserData
  0x21  string wrapper: skip 1 sub-type byte, read string, skip trailing 0x00
  0x2b  nested object whose fields merge into the parent
  0x2d  implicit integer 1 (zero-byte) — seen before deckNumber on macOS
  0x2e  implicit None (zero-byte) — keySignatureIndex not yet determined by djay
  0x30  timestamp float64 (8-byte-aligned)
"""

import logging
import struct
import sys
import urllib.parse

try:
    from mac_alias import Bookmark as _MacAliasBookmark  # type: ignore[import-untyped]
    from mac_alias.bookmark import kBookmarkPath as _kBookmarkPath  # type: ignore[import-untyped]

    _HAS_MAC_ALIAS = True
except ImportError:
    _MacAliasBookmark = None  # type: ignore[assignment,misc]
    _kBookmarkPath = None
    _HAS_MAC_ALIAS = False


# Sentinel returned by _read_typed_value for unrecognised type codes.
# Identity comparison (value is _TSAF_UNKNOWN) never accidentally matches a
# real parsed value, including None.
_TSAF_UNKNOWN = object()


def parse_tsaf(blob: bytes) -> dict:  # pylint: disable=too-many-branches,too-many-statements
    """Deserialise a TSAF binary blob from the djay Pro MediaLibrary database.

    Returns a flat dict of all fields found.  Nested 0x2b objects have
    their fields merged into the parent; 0x0b array elements are stored
    as lists (file:// strings are later resolved to a 'filename' key by
    parse_blob).
    """
    if len(blob) < 20 or blob[:4] != b"TSAF":
        return {}

    pos = 20  # skip 20-byte header

    def read_string() -> str:
        nonlocal pos
        try:
            end = blob.index(b"\x00", pos)
        except ValueError:
            end = len(blob)
        s = blob[pos:end].decode("utf-8", errors="replace")
        pos = end + 1 if end < len(blob) else len(blob)
        return s

    def read_float32() -> float:
        nonlocal pos
        rem = pos % 4
        if rem:
            pos += 4 - rem
        val = struct.unpack_from("<f", blob, pos)[0]
        pos += 4
        return val

    def read_float64() -> float:
        nonlocal pos
        rem = pos % 8
        if rem:
            pos += 8 - rem
        val = struct.unpack_from("<d", blob, pos)[0]
        pos += 8
        return val

    def read_aligned_int(width: int, fmt: str) -> int:
        nonlocal pos
        rem = pos % width
        if rem:
            pos += width - rem
        val = struct.unpack_from(fmt, blob, pos)[0]
        pos += width
        return val

    def _merge_list_into(target: dict, items: list) -> None:
        """Merge dict items from a keyless array into *target* (first-seen wins)."""
        for item in items:
            if isinstance(item, dict):
                for k, v in item.items():
                    if v is not None and k not in target:
                        target[k] = v

    def _read_typed_value(tc: int) -> object:
        """Read the value for a scalar type code; return _TSAF_UNKNOWN if unrecognised.

        Shared by read_array_element and parse_object so the type table stays
        in one place.  The 0x2b (nested object), 0x0b (array), and 0x21
        (string wrapper) types are structural and handled by their callers.
        """
        nonlocal pos
        value: object = _TSAF_UNKNOWN
        if tc == 0x08:
            value = read_string()
        elif tc == 0x0F:
            # uint8: single value byte, no alignment
            value = blob[pos] if pos < len(blob) else None
            pos += 1
        elif tc == 0x13:
            value = read_float32()
        elif tc in (0x14, 0x30):
            value = read_float64()
        elif tc == 0x0A:
            value = read_aligned_int(2, "<h")
        elif tc == 0x0C:
            value = read_aligned_int(4, "<i")
        elif tc in (0x11, 0x1A):
            value = read_aligned_int(4, "<I")
        elif tc == 0x12:
            value = read_aligned_int(8, "<Q")
        elif tc in (0x0D, 0x2D):
            value = 0
        elif tc == 0x0E:
            value = 1
        elif tc == 0x2E:
            value = None
        elif tc == 0x15:
            # Binary blob: length may be larger than remaining bytes if the
            # blob is truncated; clamp pos so subsequent fields aren't skipped.
            length = read_aligned_int(4, "<I")
            end = pos + length
            value = bytes(blob[pos:end])
            pos = min(end, len(blob))
        return value

    def read_array_element() -> object:
        nonlocal pos
        if pos >= len(blob):
            return None
        tc = blob[pos]
        pos += 1
        if tc == 0x2B:
            return parse_object()
        if tc == 0x21:
            if pos < len(blob):
                pos += 1  # skip sub-type byte
            s = read_string()
            if pos < len(blob) and blob[pos] == 0x00:
                pos += 1  # skip trailing null
            return s
        value = _read_typed_value(tc)
        if value is _TSAF_UNKNOWN:
            logging.warning("Unknown TSAF type 0x%02x in array at offset %d", tc, pos - 1)
            return None
        # Typed array elements may carry a key — return a dict for _merge_list_into
        if pos < len(blob) and blob[pos] == 0x08:
            pos += 1
            key = read_string()
            return {key: value}
        return value

    def parse_object() -> dict:  # pylint: disable=too-many-branches,too-many-statements
        nonlocal pos
        result: dict = {}

        # class name
        if pos >= len(blob) or blob[pos] != 0x08:
            return result
        pos += 1
        class_name = read_string()

        # Detect obj_id: a string immediately followed by 0x05 is an
        # object identity field, not a named field.
        #
        # ADCMediaItemTitleID uses its obj_id as the join key into the
        # location / analysis tables.  Capture it instead of discarding it.
        local_max: int | None = None
        if pos < len(blob) and blob[pos] == 0x08:
            save_pos = pos
            pos += 1
            obj_id = read_string()
            if pos < len(blob) and blob[pos] == 0x05:
                pos += 1
                local_max = blob[pos]
                pos += 1
                if class_name == "ADCMediaItemTitleID" and len(obj_id) == 32:
                    result["titleID"] = obj_id
            else:
                pos = save_pos  # not an obj_id – rewind

        fields_read = 0
        while pos < len(blob):
            if local_max is not None and fields_read >= local_max:
                break

            peek = blob[pos]

            if peek == 0x00:
                # Distinguish null-value (0x00 followed by key marker 0x08)
                # from end-of-object (0x00 followed by anything else).
                if pos + 1 < len(blob) and blob[pos + 1] == 0x08:
                    pos += 1  # null-value type — consume and fall through to key read
                    value = None
                    if pos < len(blob) and blob[pos] == 0x08:
                        pos += 1
                        key = read_string()
                        if key not in result:
                            result[key] = value
                        fields_read += 1
                    continue
                pos += 1  # end-of-object marker
                break

            if peek == 0x05:
                # 0x05 N is a field-count marker.  The value N sets (or
                # overrides) the loop limit for this object.  When two
                # consecutive markers appear (e.g. 05 01 05 02 in
                # localMediaItemLocations), the LAST one wins, which
                # correctly scopes the nested ADCMediaItemTitleID to 2
                # fields even when no UUID obj_id precedes them.
                local_max = blob[pos + 1] if pos + 1 < len(blob) else local_max
                pos += 2
                continue

            tc = blob[pos]
            pos += 1

            if tc == 0x2B:
                # Inline nested object: merge fields into parent
                sub = parse_object()
                result.update(sub)
                fields_read += 1
                continue  # no separate key
            if tc == 0x0B:
                # Array: 4-byte-aligned int32 count, then elements
                count = read_aligned_int(4, "<i")
                value: object = [read_array_element() for _ in range(count) if pos < len(blob)]
            elif tc == 0x21:
                if pos < len(blob):
                    pos += 1  # skip sub-type byte
                value = read_string()
                if pos < len(blob) and blob[pos] == 0x00:
                    pos += 1
            else:
                value = _read_typed_value(tc)
                if value is _TSAF_UNKNOWN:
                    # Unknown type: value size is unknowable so the cursor
                    # cannot be advanced safely.  Stop and return what was
                    # collected so far.  Log at WARNING so new type codes
                    # added by djay Pro updates are visible.
                    logging.warning(
                        "Unknown TSAF type 0x%02x at offset %d; stopping parse",
                        tc,
                        pos - 1,
                    )
                    break

            if pos < len(blob) and blob[pos] == 0x08:
                pos += 1
                key = read_string()
                if value is not None or key not in result:
                    result[key] = value
                fields_read += 1
            elif isinstance(value, list):
                # Array of objects with no following key: merge dict items
                # into the parent.  This handles localMediaItemLocations
                # where a 0x0b array of ADCMediaItemTitleID objects carries
                # title/artist but has no explicit key in the byte stream.
                _merge_list_into(result, value)
                fields_read += 1

        return result

    if pos >= len(blob) or blob[pos] != 0x2B:
        return {}
    pos += 1
    return parse_object()


# djay Pro keySignatureIndex → musical key name.
#
# Even indices are major keys (Camelot B ring); odd indices are their relative
# minor keys (Camelot A ring).  Each pair (2n, 2n+1) shares the same Camelot
# position.  The Camelot number is: (7 × (idx // 2) + 8) % 12, with 0 → 12.
# Sequence starts at Camelot 8 (Db/Bbm) and follows the circle of fifths.
#
# Verified: idx 5 = Cm (10A), idx 8 = F (12B), idx 11 = Ebm (7A),
#           idx 18 = Bb (11B).
KEY_SIGNATURE_MAP: dict[int, str] = {
    0: "Db",
    1: "Bbm",  # Camelot 8B / 8A
    2: "D",
    3: "Bm",  # Camelot 3B / 3A
    4: "Eb",
    5: "Cm",  # Camelot 10B / 10A
    6: "E",
    7: "C#m",  # Camelot 5B / 5A
    8: "F",
    9: "Dm",  # Camelot 12B / 12A
    10: "F#",
    11: "Ebm",  # Camelot 7B / 7A
    12: "G",
    13: "Em",  # Camelot 2B / 2A
    14: "Ab",
    15: "Fm",  # Camelot 9B / 9A
    16: "A",
    17: "F#m",  # Camelot 4B / 4A
    18: "Bb",
    19: "Gm",  # Camelot 11B / 11A
    20: "B",
    21: "Abm",  # Camelot 6B / 6A
    22: "C",
    23: "Am",  # Camelot 1B / 1A
}


def flatten_tsaf_raw(raw: dict) -> dict[str, object]:
    """Flatten a raw TSAF dict: expand list values into top-level keys.

    0x0b array values may contain dicts (whose keys are merged in) or
    file:// strings (stored under 'sourceURI').  Scalar values are kept
    as-is.  First-seen wins for duplicate keys.
    """
    result: dict[str, object] = {}
    for key, val in raw.items():
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    new = {k: v for k, v in item.items() if v is not None and k not in result}
                    result.update(new)
                elif isinstance(item, str) and item.startswith("file://"):
                    result.setdefault("sourceURI", item)
        elif val is not None:
            result.setdefault(key, val)  # first-seen wins for scalars too
    return result


def resolve_file_uri(uri: str) -> str | None:
    """Convert a file:// URI to a local filesystem path."""
    try:
        parsed_url = urllib.parse.urlparse(uri)
        path = urllib.parse.unquote(parsed_url.path)
        if not path or path == "/":
            return None
        if sys.platform == "win32" and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return path
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def resolve_bookmark(bookmark_data: bytes) -> str | None:
    """Resolve a macOS CFURLBookmarkData blob to a local file path.

    Requires mac_alias (mac-alias on PyPI).  Returns None when the
    library is unavailable or the bookmark cannot be decoded.
    """
    if not _HAS_MAC_ALIAS or _MacAliasBookmark is None:
        return None
    try:
        bm = _MacAliasBookmark.from_bytes(bookmark_data)
        components: object = bm.get(_kBookmarkPath, None)
        if isinstance(components, list) and components:
            return "/" + "/".join(str(c) for c in components)
        logging.debug("resolve_bookmark: no path components in bookmark")
    except Exception as err:  # pylint: disable=broad-exception-caught
        logging.debug("resolve_bookmark: failed to parse bookmark: %s", err)
    return None


def parse_blob(blob_data: bytes) -> dict[str, str | int | float | None]:  # pylint: disable=too-many-locals
    """Parse a TSAF blob and return a flat track-metadata dict."""
    try:
        flat = flatten_tsaf_raw(parse_tsaf(blob_data))

        uri = flat.get("sourceURI")
        file_path = resolve_file_uri(uri) if isinstance(uri, str) else None

        if file_path is None:
            bookmark = flat.get("urlBookmarkData")
            if isinstance(bookmark, bytes):
                file_path = resolve_bookmark(bookmark)
                if file_path is None:
                    logging.debug(
                        "parse_blob: urlBookmarkData present but resolve_bookmark returned None"
                        " for artist=%r title=%r",
                        flat.get("artist"),
                        flat.get("title"),
                    )

        duration_raw = flat.get("duration")
        duration: int | None = int(duration_raw) if isinstance(duration_raw, float) else None

        bpm_raw = flat.get("bpm")
        bpm: str | None = str(bpm_raw) if isinstance(bpm_raw, float) else None

        isrc_raw = flat.get("isrc")
        isrc: str | None = str(isrc_raw) if isinstance(isrc_raw, str) and isrc_raw else None

        deck_raw = flat.get("deckNumber")
        deck: str | None = str(int(deck_raw)) if isinstance(deck_raw, (int, float)) else None

        key_idx_raw = flat.get("keySignatureIndex")
        key: str | None = (
            KEY_SIGNATURE_MAP.get(int(key_idx_raw))
            if isinstance(key_idx_raw, (int, float))
            else None
        )

        starttime_raw = flat.get("startTime")
        starttime: float | None = (
            float(starttime_raw) if isinstance(starttime_raw, (int, float)) else None
        )

        title_id_raw = flat.get("titleID")
        title_id: str | None = (
            title_id_raw if isinstance(title_id_raw, str) and len(title_id_raw) == 32 else None
        )

        return {
            "artist": flat.get("artist") or None,  # type: ignore[return-value]
            "title": flat.get("title") or None,  # type: ignore[return-value]
            "album": flat.get("album") or None,  # type: ignore[return-value]
            "source": flat.get("originSourceID") or None,  # type: ignore[return-value]
            "filename": file_path,
            "bpm": bpm,
            "deck": deck,
            "duration": duration,
            "isrc": isrc,
            "key": key,
            "starttime": starttime,
            "title_id": title_id,
        }
    except Exception as err:  # pylint: disable=broad-exception-caught
        logging.debug("Failed to parse blob: %s", err)
        return {
            "artist": None,
            "title": None,
            "album": None,
            "source": None,
            "filename": None,
            "bpm": None,
            "duration": None,
            "isrc": None,
            "starttime": None,
        }
