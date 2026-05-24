#!/usr/bin/env python3
"""Probe the charts server's /api/v1/check-version endpoint.

Walks a fixed table of representative platform combinations and prints
the response for each.  Useful when validating server-side changes to
update routing, asset selection, or the tufup_channel field.

Mirrors the query params that nowplaying/upgrades/__init__.py's
_build_version_params() sends in production.  No client-side state
is involved — this is purely a diagnostic against the live API.

Usage:
    python tools/probe_check_version.py [BASE_URL]

BASE_URL defaults to https://whatsnowplaying.com.  Pass http://localhost:8000
to hit a local dev instance.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://whatsnowplaying.com"

# Each row: (label, params dict) mirroring what _build_version_params would emit.
CASES: list[tuple[str, dict]] = [
    (
        "macOS 15 Apple Silicon (stable)",
        {"version": "5.2.0", "os": "macos", "chipset": "arm", "macos_version": 15},
    ),
    (
        "macOS 15 Intel (stable) - browser misdetect candidate",
        {"version": "5.2.0", "os": "macos", "chipset": "intel", "macos_version": 15},
    ),
    (
        "macOS 14 Apple Silicon (older OS, no compatible build)",
        {"version": "5.1.0", "os": "macos", "chipset": "arm", "macos_version": 14},
    ),
    (
        "Windows x86_64",
        {"version": "5.2.0", "os": "windows", "chipset": "x86_64"},
    ),
    (
        "Linux x86_64",
        {"version": "5.2.0", "os": "linux", "chipset": "x86_64"},
    ),
    (
        "Linux aarch64 (no compatible build)",
        {"version": "5.2.0", "os": "linux", "chipset": "aarch64"},
    ),
    (
        "macOS 15 arm running pre-release (track=prerelease)",
        {
            "version": "5.2.1-preview1",
            "os": "macos",
            "chipset": "arm",
            "macos_version": 15,
            "track": "prerelease",
        },
    ),
    (
        "macOS 26 arm (newer than any published build, forward-fall)",
        {"version": "5.2.0", "os": "macos", "chipset": "arm", "macos_version": 26},
    ),
    (
        "macOS 26 intel (newer than any published build, forward-fall)",
        {"version": "5.2.0", "os": "macos", "chipset": "intel", "macos_version": 26},
    ),
    (
        "Unknown / weird platform (current version)",
        {"version": "5.2.0", "os": "unknown"},
    ),
    (
        "Unknown / weird platform (older version, update should be available)",
        {"version": "5.1.0", "os": "unknown"},
    ),
]


def call(endpoint: str, params: dict[str, str]) -> tuple[int, dict[str, Any] | str]:
    """Call the endpoint and return (status, body or error string)."""
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:  # pylint: disable=broad-except
        return -1, f"{type(e).__name__}: {e}"

    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body


def main() -> None:
    """Run all test cases against the check-version endpoint and print results."""
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    endpoint = f"{base_url}/api/v1/check-version"
    print(f"Endpoint: {endpoint}")
    print(f"Running {len(CASES)} test cases\n")
    known = {
        "update_available",
        "latest_version",
        "asset_name",
        "asset_size_bytes",
        "tufup_channel",
        "download_page_url",
        "download_url",
    }
    for label, params in CASES:
        print(f"=== {label} ===")
        print(f"  params: {params}")
        status, body = call(endpoint, params)
        print(f"  HTTP {status}")
        if isinstance(body, dict):
            print(f"  update_available:  {body.get('update_available')}")
            print(f"  latest_version:    {body.get('latest_version')}")
            print(f"  asset_name:        {body.get('asset_name')}")
            print(f"  asset_size_bytes:  {body.get('asset_size_bytes')}")
            print(f"  tufup_channel:     {body.get('tufup_channel')!r}")
            print(f"  download_page_url: {body.get('download_page_url')!r}")
            print(f"  download_url:      {body.get('download_url')!r}")
            extras = {k: v for k, v in body.items() if k not in known}
            if extras:
                print(f"  other fields:     {extras}")
        else:
            print(f"  body: {body}")
        print()


if __name__ == "__main__":
    main()
