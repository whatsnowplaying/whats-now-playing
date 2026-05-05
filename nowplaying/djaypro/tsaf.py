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
  0x0b  array (4-byte-aligned int32 count, then typed elements)
  0x0f  uint8 value (e.g. deckNumber on macOS)
  0x13  float32 (4-byte-aligned) — macOS only
  0x14  float64 (8-byte-aligned)
  0x15  binary blob: 4-byte-aligned uint32 length, then raw bytes
        (macOS: CFURLBookmarkData stored in urlBookmarkData)
  0x21  string wrapper: skip 1 sub-type byte, read string, skip trailing 0x00
  0x2b  nested object whose fields merge into the parent
  0x2d  implicit integer 1 (seen before deckNumber on macOS)
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

    def _merge_list_into(target: dict, items: list) -> None:
        """Merge dict items from a keyless array into *target* (first-seen wins)."""
        for item in items:
            if isinstance(item, dict):
                for k, v in item.items():
                    if v is not None and k not in target:
                        target[k] = v

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
        if tc == 0x08:
            return read_string()
        return None

    def parse_object() -> dict:  # pylint: disable=too-many-branches,too-many-statements
        nonlocal pos
        result: dict = {}

        # class name (discard)
        if pos >= len(blob) or blob[pos] != 0x08:
            return result
        pos += 1
        read_string()

        # Detect obj_id: a string immediately followed by 0x05 is an
        # object identity field, not a named field.
        local_max: int | None = None
        if pos < len(blob) and blob[pos] == 0x08:
            save_pos = pos
            pos += 1
            read_string()  # candidate obj_id (discard)
            if pos < len(blob) and blob[pos] == 0x05:
                pos += 1
                local_max = blob[pos]
                pos += 1
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

            if tc == 0x08:
                value: object = read_string()
            elif tc == 0x0F:
                # uint8: value is the next byte (e.g. deckNumber on macOS)
                value = blob[pos] if pos < len(blob) else None
                pos += 1
            elif tc == 0x13:
                # macOS: float32 with 4-byte alignment
                value = read_float32()
            elif tc in (0x14, 0x30):
                # float64 with 8-byte alignment; 0x30 = timestamp
                value = read_float64()
            elif tc == 0x2D:
                # Zero-byte integer marker seen before deckNumber=1 on macOS.
                # The value is implicit (1); no value bytes precede the key.
                value = 1
            elif tc == 0x2B:
                # Inline nested object: merge fields into parent
                sub = parse_object()
                result.update(sub)
                fields_read += 1
                continue  # no separate key
            elif tc == 0x0B:
                # Array: 4-byte-aligned int32 count, then elements
                rem = pos % 4
                if rem:
                    pos += 4 - rem
                count = struct.unpack_from("<i", blob, pos)[0]
                pos += 4
                value = [read_array_element() for _ in range(count) if pos < len(blob)]
            elif tc == 0x21:
                if pos < len(blob):
                    pos += 1  # skip sub-type byte
                value = read_string()
                if pos < len(blob) and blob[pos] == 0x00:
                    pos += 1
            elif tc == 0x15:
                # Binary blob: 4-byte-aligned uint32 length, then raw bytes
                # Used on macOS for CFURLBookmarkData (urlBookmarkData field)
                rem = pos % 4
                if rem:
                    pos += 4 - rem
                length = struct.unpack_from("<I", blob, pos)[0]
                pos += 4
                value = bytes(blob[pos : pos + length])
                pos += length
            else:
                # Unknown type: cannot safely advance pos, so stop parsing
                # this object rather than misreading value bytes as the next
                # type code.
                logging.debug("Unknown TSAF type 0x%02x at offset %d", tc, pos - 1)
                break

            if pos < len(blob) and blob[pos] == 0x08:
                pos += 1
                key = read_string()
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
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return None


def parse_blob(blob_data: bytes) -> dict[str, str | int | None]:
    """Parse a TSAF blob and return a flat track-metadata dict."""
    try:
        flat = flatten_tsaf_raw(parse_tsaf(blob_data))

        uri = flat.get("sourceURI")
        file_path = resolve_file_uri(uri) if isinstance(uri, str) else None

        if file_path is None:
            bookmark = flat.get("urlBookmarkData")
            if isinstance(bookmark, bytes):
                file_path = resolve_bookmark(bookmark)

        duration_raw = flat.get("duration")
        duration: int | None = int(duration_raw) if isinstance(duration_raw, float) else None

        bpm_raw = flat.get("bpm")
        bpm: str | None = str(bpm_raw) if isinstance(bpm_raw, float) else None

        isrc_raw = flat.get("isrc")
        isrc: str | None = str(isrc_raw) if isinstance(isrc_raw, str) and isrc_raw else None

        return {
            "artist": flat.get("artist") or None,  # type: ignore[return-value]
            "title": flat.get("title") or None,  # type: ignore[return-value]
            "album": flat.get("album") or None,  # type: ignore[return-value]
            "source": flat.get("originSourceID") or None,  # type: ignore[return-value]
            "filename": file_path,
            "bpm": bpm,
            "duration": duration,
            "isrc": isrc,
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
        }
