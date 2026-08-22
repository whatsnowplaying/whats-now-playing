#!/usr/bin/env python3
"""pick a TLS trust store, falling back to certifi when the OS store is stale

A machine that has not taken an OS update in years carries a root store that
predates the CAs MusicBrainz, Discogs, and the rest chain to today.  Every
handshake fails with CERTIFICATE_VERIFY_FAILED and the DJ just sees empty
metadata with nothing obviously wrong.  Probe once in the background; if the
bundled Mozilla roots validate a host the system store rejects, move the whole
app onto certifi.

Three kinds of consumer have to agree on the answer:

* code that builds its own context -- ``create_ssl_context()``
* wnpmb, which takes a path -- ``ca_bundle()``
* everything reached only through library defaults (twitchAPI, discord.py,
  tufup, bare ``aiohttp.ClientSession()``) -- the environment variables set by
  ``apply_mode()``

This module only answers "are the certs bad?" -- it never touches config.
The caller reads the settings, decides whether a probe is warranted, and owns
writing any verdict back, because config must not be written before
nowplaying.upgrade.upgrade() has run.

Mode changes take effect on the next launch.  Un-doing an applied fallback
inside a live process would mean chasing every session and context already
built from it.
"""

import logging
import os
import pathlib
import socket
import ssl
import threading
import time

import certifi
import orjson
import truststore

MODE_AUTO = "auto"
MODE_SYSTEM = "system"
MODE_CERTIFI = "certifi"
MODES = (MODE_AUTO, MODE_SYSTEM, MODE_CERTIFI)
# What a probe can conclude and what can actually be applied; "auto" is a
# question, not an answer.
APPLIED_MODES = (MODE_SYSTEM, MODE_CERTIFI)

# The user's preference is a setting.  The probe result is not -- it is a cache,
# and it lives in a plain file so startup can read it before upgrade() runs,
# when opening QSettings at all is off limits.
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
# Startup waits at most this long for a verdict.  An offline machine would
# otherwise pay PROBE_TIMEOUT per host before the tray could continue.
PROBE_JOIN_TIMEOUT = 5.0
RECHECK_SECONDS = 7 * 24 * 3600

_effective_mode: str | None = None  # pylint: disable=invalid-name


def _certifi_context() -> ssl.SSLContext:
    """context pinned to the Mozilla roots shipped with certifi"""
    return ssl.create_default_context(cafile=certifi.where())


def _system_context() -> ssl.SSLContext:
    """context that defers to the OS trust store"""
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


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

    Every host gets asked, not just the first one that answers: a stale store
    typically still has the older roots, so one success proves nothing about
    the rest.  One host failing the stale-root test is enough to switch.

    A rejection only counts once certifi has verified the same host: both
    stores failing means something else is wrong (captive portal, MITM proxy,
    an actually-expired server cert) and swapping roots would not help.
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
    """Point this process at the chosen trust store and remember the choice."""
    global _effective_mode  # pylint: disable=global-statement
    _effective_mode = mode
    if mode != MODE_CERTIFI:
        logging.debug(
            "CA trust: OS trust store; SSL_CERT_FILE=%s, openssl cafile=%s",
            os.environ.get("SSL_CERT_FILE"),
            ssl.get_default_verify_paths().cafile,
        )
        return mode

    bundle = certifi.where()
    os.environ[BUNDLE_ENV] = bundle
    # setdefault, not assignment: an operator who exported their own bundle
    # (corporate root, test rig) outranks our verdict.
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    truststore.extract_from_ssl()
    # SSL_CERT_FILE is named separately because an operator export outranks our
    # bundle, so the two can legitimately disagree.
    logging.info(
        "CA trust: bundled certifi roots (%s); SSL_CERT_FILE=%s",
        bundle,
        os.environ.get("SSL_CERT_FILE"),
    )
    return mode


def effective_mode() -> str:
    """Trust store in force for this process."""
    if _effective_mode:
        return _effective_mode
    # A process that never applied a mode -- a subprocess mid-startup, a test
    # importing a client directly -- still honours an inherited verdict.
    return MODE_CERTIFI if os.environ.get(BUNDLE_ENV) else MODE_SYSTEM


def ca_bundle() -> str | None:
    """Path to force on clients that take one, or None to keep their default."""
    return certifi.where() if effective_mode() == MODE_CERTIFI else None


def create_ssl_context() -> ssl.SSLContext:
    """The one place WNP builds a client-side TLS context."""
    if effective_mode() == MODE_CERTIFI:
        return _certifi_context()
    return _system_context()


def resolve(mode: str, cached_verdict: str) -> str:
    """Fold the configured mode and any cached verdict into one answer."""
    if mode not in MODES:
        logging.warning("Unknown CA trust mode %r; treating as %s", mode, MODE_AUTO)
        mode = MODE_AUTO
    if mode != MODE_AUTO:
        return mode
    return cached_verdict if cached_verdict in MODES else MODE_SYSTEM


def needs_probe(mode: str, cached_verdict: str, checked: int) -> bool:
    """True when auto mode has no verdict, or one old enough to re-test."""
    if mode != MODE_AUTO:
        return False
    if cached_verdict not in MODES or checked <= 0:
        return True
    return time.time() - checked >= RECHECK_SECONDS


def load_state(path: "pathlib.Path") -> tuple[str, str, int]:
    """Return (effective, verdict, checked) from the cache, with safe defaults.

    This file lives in the user's Documents tree, so treat it as untrusted:
    every field is validated against values we already defined, and nothing in
    it can name a path or a bundle -- the worst a hostile edit can do is pick
    between the OS trust store and our own certifi copy.  Anything unreadable,
    oversized, or unrecognised degrades to the OS trust store, which is what an
    install with no cache has always done.
    """
    try:
        if path.stat().st_size > _MAX_STATE_BYTES:
            logging.warning("CA trust cache at %s is implausibly large; ignoring it", path)
            return MODE_SYSTEM, "", 0
        raw = orjson.loads(path.read_bytes())
    except (OSError, ValueError):
        return MODE_SYSTEM, "", 0

    if not isinstance(raw, dict):
        return MODE_SYSTEM, "", 0
    effective = raw.get("effective")
    verdict = raw.get("verdict")
    checked = raw.get("checked")
    # bool is an int; a timestamp from the future means a wrong clock or a hand
    # edit, and either way the honest move is to probe again.
    if isinstance(checked, bool) or not isinstance(checked, int) or not 0 < checked <= time.time():
        checked = 0
    return (
        effective if effective in APPLIED_MODES else MODE_SYSTEM,
        verdict if verdict in APPLIED_MODES else "",
        checked,
    )


def save_state(path: "pathlib.Path", effective: str, verdict: str, checked: int) -> None:
    """Record the resolved mode and the probe result for the next launch."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            orjson.dumps({"effective": effective, "verdict": verdict, "checked": checked})
        )
    except OSError:
        logging.exception("Could not write the CA trust cache to %s", path)


class TrustProbe:
    """Runs probe() on a worker so startup can overlap it.

    Deliberately inert: it reports a verdict and nothing else.  The caller
    joins it before the first TLS of the session and decides what to persist.
    """

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

        A probe that overruns is abandoned rather than waited out -- startup
        matters more than the answer, and the next launch tries again.
        """
        self._thread.join(timeout)
        if self._thread.is_alive():
            logging.debug("CA trust probe still running after %ss; carrying on", timeout)
            return None
        return self.verdict
