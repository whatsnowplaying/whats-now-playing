#!/usr/bin/env python3
"""pick a TLS trust store, falling back to certifi when the OS store is stale

A trust store that cannot verify our hosts shows up as empty artwork and bios,
not as an error: the artistextras plugins swallow exceptions to keep a set
running.  So probe for it explicitly.

Callers get the answer three ways because three kinds of consumer need it:
create_ssl_context() for our own clients, ca_bundle() for wnpmb, and the
environment for libraries we only reach through their defaults.

Reports only -- never touches config, which is unreadable and unwritable until
nowplaying.upgrade.upgrade() has run.  Takes effect on the next launch.
"""

import json
import logging
import os
import pathlib
import socket
import ssl
import threading
import time

import certifi
import truststore

MODE_AUTO = "auto"
MODE_SYSTEM = "system"
MODE_CERTIFI = "certifi"
MODES = (MODE_AUTO, MODE_SYSTEM, MODE_CERTIFI)
VERDICTS = (MODE_SYSTEM, MODE_CERTIFI)

# The preference is a setting; the probe result is a cache, in a plain file
# because startup needs it before QSettings may be opened at all.
MODE_KEY = "settings/catrust"
STATE_FILE = "catrust.json"
_MAX_STATE_BYTES = 4096

# Set to the bundle path while the fallback is live.  Spawned subprocesses
# inherit it, which is both how they learn the verdict and how wnppyi.py knows
# to leave the system store alone instead of re-injecting truststore.
BUNDLE_ENV = "WNP_CA_BUNDLE"

# One host per distinct root we depend on, newest root first.  A stale store is
# rarely empty -- it is missing the *recent* roots, so probing only an old root
# like DigiCert G2 would pass while every Let's Encrypt-backed image fails.
#   coverartarchive.org   ISRG Root X2 (2020)  -- also fanart.tv and wikimedia
#   ws.audioscrobbler.com Sectigo R46  (2021)
#   api.discogs.com       GTS Root R4  (2016)  -- also theaudiodb
#   musicbrainz.org       DigiCert G2  (2013)  -- the baseline everyone has
PROBE_HOSTS = (
    "coverartarchive.org",
    "ws.audioscrobbler.com",
    "api.discogs.com",
    "musicbrainz.org",
)
PROBE_TIMEOUT = 3.0
# Cap on the startup wait; offline would otherwise cost PROBE_TIMEOUT per host.
PROBE_JOIN_TIMEOUT = 5.0
RECHECK_SECONDS = 7 * 24 * 3600

_effective_mode: str | None = None  # pylint: disable=invalid-name


def _certifi_context() -> ssl.SSLContext:
    """context pinned to the Mozilla roots shipped with certifi"""
    context = ssl.create_default_context(cafile=certifi.where())
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _system_context() -> ssl.SSLContext:
    """context that defers to the OS trust store"""
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _handshake(context: ssl.SSLContext, host: str, port: int = 443) -> bool | None:
    """True if the chain verified, False if it was rejected, None if unreachable"""
    try:
        with (
            socket.create_connection((host, port), timeout=PROBE_TIMEOUT) as sock,
            context.wrap_socket(sock, server_hostname=host),
        ):
            return True
    except ssl.SSLCertVerificationError:
        return False
    except (OSError, ssl.SSLError):
        return None


def probe() -> str | None:
    """Decide which trust store to use, or None if nothing could be reached.

    A success proves nothing about the other hosts, so keep going; a confirmed
    failure is the whole diagnosis, so stop.  A rejection only counts once
    certifi has verified the same host -- both stores failing means a portal, a
    proxy, or a bad server cert, none of which swapping roots would fix.
    """
    verified_any = False
    for host in PROBE_HOSTS:
        result = _handshake(_system_context(), host)
        if result is None:
            continue
        if result is True:
            verified_any = True
            continue
        if _handshake(_certifi_context(), host) is True:
            logging.warning(
                "System CA store rejected %s but the bundled roots accepted it; "
                "the machine's certificates are out of date",
                host,
            )
            return MODE_CERTIFI
        logging.warning("Neither trust store could verify %s; not a stale-root problem", host)
    return MODE_SYSTEM if verified_any else None


def apply_mode(mode: str) -> str:
    """Point this process at the chosen trust store and remember the choice.

    The environment carries the answer to spawned subprocesses and to libraries
    we only reach through their defaults.  An operator who exported their own
    bundle outranks us in both directions, so we only ever set what is unset and
    only ever remove our own path -- frozen.py plants ours before we get a say,
    and leaving it would quietly keep certifi in force after a switch away.
    """
    global _effective_mode  # pylint: disable=global-statement
    _effective_mode = mode
    bundle = certifi.where()

    if mode != MODE_CERTIFI:
        os.environ.pop(BUNDLE_ENV, None)
        for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
            if (value := os.environ.get(name)) and pathlib.Path(value) == pathlib.Path(bundle):
                del os.environ[name]
        logging.debug(
            "CA trust: OS trust store; SSL_CERT_FILE=%s, openssl cafile=%s",
            os.environ.get("SSL_CERT_FILE"),
            ssl.get_default_verify_paths().cafile,
        )
        return mode

    os.environ[BUNDLE_ENV] = bundle
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    truststore.extract_from_ssl()
    logging.info(
        "CA trust: bundled certifi roots (%s); SSL_CERT_FILE=%s",
        bundle,
        os.environ.get("SSL_CERT_FILE"),
    )
    return mode


def _current_mode() -> str:
    """A subprocess that never applied a mode still honours an inherited one."""
    if _effective_mode:
        return _effective_mode
    return MODE_CERTIFI if os.environ.get(BUNDLE_ENV) else MODE_SYSTEM


def ca_bundle() -> str | None:
    """Path to force on clients that take one, or None to keep their default."""
    return certifi.where() if _current_mode() == MODE_CERTIFI else None


def create_ssl_context() -> ssl.SSLContext:
    """The one place WNP builds a client-side TLS context."""
    if _current_mode() == MODE_CERTIFI:
        return _certifi_context()
    return _system_context()


def resolve(mode: str, cached_verdict: str) -> str:
    """Fold the configured mode and any cached verdict into one answer."""
    if mode not in MODES:
        logging.warning("Unknown CA trust mode %r; treating as %s", mode, MODE_AUTO)
        mode = MODE_AUTO
    if mode != MODE_AUTO:
        return mode
    return cached_verdict if cached_verdict in VERDICTS else MODE_SYSTEM


def needs_probe(mode: str, cached_verdict: str, checked: int) -> bool:
    """True when auto mode has no verdict, or one old enough to re-test."""
    if mode != MODE_AUTO:
        return False
    if cached_verdict not in VERDICTS or checked <= 0:
        return True
    return time.time() - checked >= RECHECK_SECONDS


def load_state(path: "pathlib.Path") -> tuple[str, str, int]:
    """Return (effective, verdict, checked) from the cache, with safe defaults.

    Untrusted input: no field can name a path or a bundle, so the worst a hand
    edit achieves is choosing between the OS store and our own certifi copy.
    Anything unrecognised degrades to the OS store.
    """
    try:
        if path.stat().st_size > _MAX_STATE_BYTES:
            logging.warning("CA trust cache at %s is implausibly large; ignoring it", path)
            return MODE_SYSTEM, "", 0
        raw = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return MODE_SYSTEM, "", 0

    if not isinstance(raw, dict):
        return MODE_SYSTEM, "", 0
    effective = raw.get("effective")
    verdict = raw.get("verdict")
    checked = raw.get("checked")
    # bool is an int, and a future timestamp means a bad clock or a hand edit
    if isinstance(checked, bool) or not isinstance(checked, int) or not 0 < checked <= time.time():
        checked = 0
    return (
        effective if effective in VERDICTS else MODE_SYSTEM,
        verdict if verdict in VERDICTS else "",
        checked,
    )


def save_state(path: "pathlib.Path", effective: str, verdict: str, checked: int) -> None:
    """Record the resolved mode and the probe result for the next launch."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"effective": effective, "verdict": verdict, "checked": checked}),
            encoding="utf-8",
        )
    except OSError:
        logging.exception("Could not write the CA trust cache to %s", path)


class TrustProbe:
    """Runs probe() on a worker so startup can overlap it."""

    def __init__(self) -> None:
        self.verdict: str | None = None
        self._thread = threading.Thread(target=self._run, name="catrust-probe", daemon=True)

    def start(self) -> "TrustProbe":
        """Begin probing in the background."""
        self._thread.start()
        return self

    def _run(self) -> None:
        self.verdict = probe()

    def result(self, timeout: float) -> str | None:
        """Verdict if the probe finished in time, else None.

        An overrunning probe is abandoned, not waited out; next launch retries.
        """
        self._thread.join(timeout)
        if self._thread.is_alive():
            logging.debug("CA trust probe still running after %ss; carrying on", timeout)
            return None
        return self.verdict
