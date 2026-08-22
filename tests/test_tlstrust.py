#!/usr/bin/env python3
"""tests for the CA trust-store probe and certifi fallback"""

import os
import ssl
import threading
import time

import orjson

import certifi
import pytest

import nowplaying.tlstrust


@pytest.fixture(autouse=True)
def restore_process_state():
    """tlstrust deliberately mutates process-wide state; put it back afterwards"""
    saved_mode = nowplaying.tlstrust._effective_mode  # pylint: disable=protected-access
    saved_env = {
        key: os.environ.get(key)
        for key in (nowplaying.tlstrust.BUNDLE_ENV, "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
    }
    yield
    nowplaying.tlstrust._effective_mode = saved_mode  # pylint: disable=protected-access
    for key, value in saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_default_mode_is_system():
    """no configured mode and no verdict leaves the OS trust store in charge"""
    mode = nowplaying.tlstrust.resolve(nowplaying.tlstrust.MODE_AUTO, "")
    assert nowplaying.tlstrust.apply_mode(mode) == nowplaying.tlstrust.MODE_SYSTEM
    assert nowplaying.tlstrust.ca_bundle() is None
    assert type(nowplaying.tlstrust.create_ssl_context()).__module__ == "truststore._api"


@pytest.mark.parametrize(
    "mode,expected",
    [
        (nowplaying.tlstrust.MODE_SYSTEM, nowplaying.tlstrust.MODE_SYSTEM),
        (nowplaying.tlstrust.MODE_CERTIFI, nowplaying.tlstrust.MODE_CERTIFI),
        ("nonsense", nowplaying.tlstrust.MODE_SYSTEM),
    ],
)
def test_explicit_mode_overrides_probe(mode, expected):
    """a forced mode wins, and an unreadable one degrades to the OS store"""
    assert nowplaying.tlstrust.resolve(mode, "") == expected


def test_auto_follows_cached_verdict():
    """auto mode replays whatever the last probe decided"""
    mode = nowplaying.tlstrust.resolve(
        nowplaying.tlstrust.MODE_AUTO, nowplaying.tlstrust.MODE_CERTIFI
    )
    assert nowplaying.tlstrust.apply_mode(mode) == nowplaying.tlstrust.MODE_CERTIFI
    assert nowplaying.tlstrust.ca_bundle() == certifi.where()


def test_certifi_mode_sets_bundle_for_subprocesses():
    """the fallback has to reach libraries we never touch, so it goes in the environment"""
    nowplaying.tlstrust.apply_mode(nowplaying.tlstrust.MODE_CERTIFI)
    assert os.environ[nowplaying.tlstrust.BUNDLE_ENV] == certifi.where()
    assert os.environ["SSL_CERT_FILE"]
    assert os.environ["REQUESTS_CA_BUNDLE"]
    assert ssl.SSLContext.__module__ == "ssl"
    assert type(nowplaying.tlstrust.create_ssl_context()).__module__ == "ssl"


def test_operator_bundle_outranks_the_verdict(monkeypatch):
    """someone who exported their own bundle meant it"""
    monkeypatch.setenv("SSL_CERT_FILE", "/somewhere/corporate.pem")
    nowplaying.tlstrust.apply_mode(nowplaying.tlstrust.MODE_CERTIFI)
    assert os.environ["SSL_CERT_FILE"] == "/somewhere/corporate.pem"


def test_inherited_bundle_survives_without_apply(monkeypatch):
    """a subprocess reads the verdict off the environment before its config exists"""
    monkeypatch.setattr(nowplaying.tlstrust, "_effective_mode", None)
    monkeypatch.setenv(nowplaying.tlstrust.BUNDLE_ENV, certifi.where())
    assert nowplaying.tlstrust.effective_mode() == nowplaying.tlstrust.MODE_CERTIFI


@pytest.mark.parametrize(
    "system_result,certifi_result,expected",
    [
        (True, None, nowplaying.tlstrust.MODE_SYSTEM),
        (False, True, nowplaying.tlstrust.MODE_CERTIFI),
        (False, False, None),
        (None, None, None),
    ],
)
def test_probe_verdicts(monkeypatch, system_result, certifi_result, expected):
    """certifi only wins when it verifies a host the system store rejected"""
    results = {"truststore._api": system_result, "ssl": certifi_result}

    def fake_handshake(context, host, port=443):  # pylint: disable=unused-argument
        return results[type(context).__module__]

    monkeypatch.setattr(nowplaying.tlstrust, "_handshake", fake_handshake)
    monkeypatch.setattr(nowplaying.tlstrust, "PROBE_HOSTS", ("example.invalid",))
    assert nowplaying.tlstrust.probe() == expected


def test_probe_catches_a_partial_trust_gap(monkeypatch):
    """an old store keeps its old roots, so one host verifying proves nothing

    The realistic failure is a machine that still trusts DigiCert G2 from 2013
    but never picked up ISRG Root X2 from 2020: MusicBrainz works while every
    Let's Encrypt-backed image fails.  Stopping at the first success would call
    that healthy.
    """
    old_root_ok = "musicbrainz.org"

    def fake_handshake(context, host, port=443):  # pylint: disable=unused-argument
        if host == old_root_ok:
            return True
        return type(context).__module__ != "truststore._api"

    monkeypatch.setattr(nowplaying.tlstrust, "_handshake", fake_handshake)
    monkeypatch.setattr(nowplaying.tlstrust, "PROBE_HOSTS", (old_root_ok, "coverartarchive.org"))
    assert nowplaying.tlstrust.probe() == nowplaying.tlstrust.MODE_CERTIFI


def test_probe_newest_roots_come_first():
    """the canary has to be a root an unpatched machine would actually lack"""
    assert nowplaying.tlstrust.PROBE_HOSTS[0] == "coverartarchive.org"
    assert nowplaying.tlstrust.PROBE_HOSTS[-1] == "musicbrainz.org"


def test_probe_moves_past_an_unreachable_host(monkeypatch):
    """one dead host must not stop the probe from asking the next one"""
    seen: list[str] = []

    def fake_handshake(context, host, port=443):  # pylint: disable=unused-argument
        seen.append(host)
        return None if host == "dead.invalid" else True

    monkeypatch.setattr(nowplaying.tlstrust, "_handshake", fake_handshake)
    monkeypatch.setattr(nowplaying.tlstrust, "PROBE_HOSTS", ("dead.invalid", "live.invalid"))
    assert nowplaying.tlstrust.probe() == nowplaying.tlstrust.MODE_SYSTEM
    assert seen == ["dead.invalid", "live.invalid"]


def test_handshake_reports_unreachable_as_none():
    """an unresolvable host is not evidence about anyone's certificates"""
    context = nowplaying.tlstrust.create_ssl_context()
    assert nowplaying.tlstrust._handshake(context, "no-such-host.invalid") is None  # pylint: disable=protected-access


@pytest.mark.parametrize(
    "mode,verdict,checked_offset,expected",
    [
        (nowplaying.tlstrust.MODE_AUTO, "", 0, True),
        (nowplaying.tlstrust.MODE_AUTO, nowplaying.tlstrust.MODE_SYSTEM, -60, False),
        (
            nowplaying.tlstrust.MODE_AUTO,
            nowplaying.tlstrust.MODE_SYSTEM,
            -(nowplaying.tlstrust.RECHECK_SECONDS + 60),
            True,
        ),
        (nowplaying.tlstrust.MODE_AUTO, "garbage", 0, True),
        (nowplaying.tlstrust.MODE_SYSTEM, "", 0, False),
        (nowplaying.tlstrust.MODE_CERTIFI, "", 0, False),
    ],
)
def test_needs_probe(mode, verdict, checked_offset, expected):
    """probing is a network call on the startup path, so only when warranted"""
    checked = int(time.time()) + checked_offset if verdict else 0
    assert nowplaying.tlstrust.needs_probe(mode, verdict, checked) is expected


def test_trustprobe_hands_back_the_verdict(monkeypatch):
    """the probe reports; it never writes anything itself"""
    monkeypatch.setattr(nowplaying.tlstrust, "probe", lambda: nowplaying.tlstrust.MODE_CERTIFI)
    assert (
        nowplaying.tlstrust.TrustProbe().start().result(timeout=10)
        == nowplaying.tlstrust.MODE_CERTIFI
    )


def test_trustprobe_reports_nothing_when_inconclusive(monkeypatch):
    """an offline machine keeps whatever verdict the caller already had"""
    monkeypatch.setattr(nowplaying.tlstrust, "probe", lambda: None)
    assert nowplaying.tlstrust.TrustProbe().start().result(timeout=10) is None


def test_trustprobe_is_abandoned_rather_than_waited_out(monkeypatch):
    """startup matters more than the answer; a slow probe is dropped"""
    started = threading.Event()

    def slow_probe():
        started.set()
        time.sleep(30)
        return nowplaying.tlstrust.MODE_CERTIFI

    monkeypatch.setattr(nowplaying.tlstrust, "probe", slow_probe)
    handle = nowplaying.tlstrust.TrustProbe().start()
    assert started.wait(timeout=10)
    assert handle.result(timeout=0.2) is None


@pytest.mark.parametrize(
    "body",
    [
        None,
        b"",
        b"hello",
        b'["certifi"]',
        b'"certifi"',
        b"null",
        b'{"effective": "evil", "verdict": "evil", "checked": 1}',
        b'{"effective": "auto", "verdict": "auto", "checked": 1}',
    ],
)
def test_load_state_degrades_to_the_os_store(tmp_path, body):
    """the cache sits in the user's Documents tree, so it is untrusted input"""
    path = tmp_path / nowplaying.tlstrust.STATE_FILE
    if body is not None:
        path.write_bytes(body)
    effective, verdict, _ = nowplaying.tlstrust.load_state(path)
    assert effective == nowplaying.tlstrust.MODE_SYSTEM
    assert verdict == ""


@pytest.mark.parametrize("checked", [True, -5, "99", 0, 2**40])
def test_load_state_rejects_unusable_timestamps(tmp_path, checked):
    """a bool, a string, or a time in the future all mean: probe again"""
    path = tmp_path / nowplaying.tlstrust.STATE_FILE
    path.write_bytes(
        orjson.dumps(
            {
                "effective": nowplaying.tlstrust.MODE_CERTIFI,
                "verdict": nowplaying.tlstrust.MODE_CERTIFI,
                "checked": checked,
            }
        )
    )
    assert nowplaying.tlstrust.load_state(path)[2] == 0


def test_load_state_ignores_an_oversized_file(tmp_path):
    """nobody hand-edits a megabyte of trust cache; do not read it in"""
    path = tmp_path / nowplaying.tlstrust.STATE_FILE
    path.write_bytes(b'{"effective":"certifi","pad":"' + b"x" * 8000 + b'"}')
    assert nowplaying.tlstrust.load_state(path)[0] == nowplaying.tlstrust.MODE_SYSTEM


def test_state_round_trips(tmp_path):
    """what the tray saves is what the next launch applies"""
    path = tmp_path / "nested" / nowplaying.tlstrust.STATE_FILE
    stamp = int(time.time()) - 10
    nowplaying.tlstrust.save_state(
        path, nowplaying.tlstrust.MODE_CERTIFI, nowplaying.tlstrust.MODE_CERTIFI, stamp
    )
    assert nowplaying.tlstrust.load_state(path) == (
        nowplaying.tlstrust.MODE_CERTIFI,
        nowplaying.tlstrust.MODE_CERTIFI,
        stamp,
    )


def test_save_state_survives_an_unwritable_path(tmp_path):
    """a cache we cannot write is not worth crashing a DJ's startup over"""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    nowplaying.tlstrust.save_state(
        blocker / nowplaying.tlstrust.STATE_FILE, nowplaying.tlstrust.MODE_SYSTEM, "", 1
    )
