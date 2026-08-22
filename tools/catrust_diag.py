#!/usr/bin/env python3
"""Report what this machine's TLS trust store can and cannot verify.

Runs the same probe the app runs, against the same hosts, so the verdict here
is the verdict the app will reach.  Useful on a machine where artwork and
biographies come back empty for no obvious reason.

    python tools/catrust_diag.py
"""

import argparse
import platform
import ssl
import sys

import certifi

import nowplaying.tlstrust

# Mirrors truststore's own platform.system() dispatch in truststore/_api.py.
# Only the openssl backend reads the cafile below; the other two ask the OS and
# ignore it, which is what makes an upgraded Homebrew openssl look relevant on
# macOS when it changes nothing about what "system" trusts.
_SYSTEM_STORES = {
    "Windows": "Windows certificate store (CryptoAPI)",
    "Darwin": "macOS Keychain (SecTrust)",
}


def _describe(result: bool | None) -> str:
    return {True: "verified", False: "REJECTED", None: "unreachable"}[result]


def main() -> int:
    """probe each host with both trust stores and report"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "hosts",
        nargs="*",
        default=list(nowplaying.tlstrust.PROBE_HOSTS),
        help="hosts to test (default: the ones the app probes)",
    )
    args = parser.parse_args()
    # probe() reads PROBE_HOSTS, so point it at whatever was asked for rather
    # than letting the table and the verdict disagree about which hosts ran.
    nowplaying.tlstrust.PROBE_HOSTS = tuple(args.hosts)

    print(f"platform      : {platform.platform()}")
    print(f"python        : {sys.version.split()[0]}")
    print(f"openssl       : {ssl.OPENSSL_VERSION}")
    print(f"system store  : {_SYSTEM_STORES.get(platform.system(), 'openssl cafile below')}")
    print(f"openssl cafile: {ssl.get_default_verify_paths().cafile}")
    print(f"certifi       : {certifi.where()}")
    print()

    stores = {
        "system": nowplaying.tlstrust._system_context,  # pylint: disable=protected-access
        "certifi": nowplaying.tlstrust._certifi_context,  # pylint: disable=protected-access
    }
    print(f"{'host':32} {'system':<12} certifi")
    for host in nowplaying.tlstrust.PROBE_HOSTS:
        results = {
            name: nowplaying.tlstrust._handshake(factory(), host)  # pylint: disable=protected-access
            for name, factory in stores.items()
        }
        print(f"{host:32} {_describe(results['system']):<12} {_describe(results['certifi'])}")

    print()
    verdict = nowplaying.tlstrust.probe()
    if verdict is None:
        print("verdict: inconclusive -- nothing answered, or both stores failed the same host")
        print("         the app leaves its cached verdict alone in this case")
    elif verdict == nowplaying.tlstrust.MODE_CERTIFI:
        print("verdict: certifi -- this machine's certificates are too old, fallback would engage")
    else:
        print("verdict: system -- this machine's certificates are fine, no fallback needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
