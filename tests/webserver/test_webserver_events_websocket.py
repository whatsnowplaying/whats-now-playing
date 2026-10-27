#!/usr/bin/env python3
"""test the pure-function pieces of /v1/events: diffing, blob-stripping, session ids

Deliberately no asyncio/DB/webserver here -- these are plain functions and the
whole point of factoring them out that way is that they're testable without any
of that.  End-to-end behavior (snapshot on connect, live broadcasts, auth) is
covered in tests/webserver/test_webserver_consolidated.py against a real server.
"""

from unittest.mock import MagicMock

import nowplaying.db  # pylint: disable=import-error
import nowplaying.webserver.events_websocket  # pylint: disable=import-error

Handler = nowplaying.webserver.events_websocket.EventsWebSocketHandler


def test_diff_requests_empty_to_empty():
    """no rows on either side -- nothing to report"""
    added, changed, removed = Handler.diff_requests({}, {})
    assert added == {}
    assert changed == {}
    assert removed == {}


def test_diff_requests_one_added():
    """a reqid present in current but not previous is added"""
    row = {"reqid": 1, "artist": "WNP Mock Artist", "title": "WNP Mock Song"}
    added, changed, removed = Handler.diff_requests({}, {1: row})
    assert added == {1: row}
    assert changed == {}
    assert removed == {}


def test_diff_requests_one_removed_carries_last_known_payload():
    """removed must carry the row's LAST-KNOWN value, not just a bare id"""
    row = {"reqid": 1, "artist": "WNP Mock Artist", "title": "WNP Mock Song"}
    added, changed, removed = Handler.diff_requests({1: row}, {})
    assert added == {}
    assert changed == {}
    assert removed == {1: row}


def test_diff_requests_simultaneous_add_and_remove():
    """one row appearing and another vanishing in the same tick don't cross-contaminate"""
    gone = {"reqid": 1, "artist": "Gone Artist", "title": "Gone Song"}
    new = {"reqid": 2, "artist": "New Artist", "title": "New Song"}
    added, changed, removed = Handler.diff_requests({1: gone}, {2: new})
    assert added == {2: new}
    assert changed == {}
    assert removed == {1: gone}


def test_diff_requests_identical_input_is_a_noop():
    """the same row set on both sides produces no events"""
    row = {"reqid": 1, "artist": "WNP Mock Artist", "title": "WNP Mock Song"}
    added, changed, removed = Handler.diff_requests({1: row}, {1: row})
    assert added == {}
    assert changed == {}
    assert removed == {}


def test_diff_requests_reqid_present_both_sides_with_different_payload_is_changed():
    """respin (same reqid, new artist/title) must surface as changed, not added+removed"""
    before = {"reqid": 1, "artist": "WNP Mock Artist", "title": "WNP Mock Song"}
    after = {"reqid": 1, "artist": "WNP Mock Artist 2", "title": "WNP Mock Song 2"}
    added, changed, removed = Handler.diff_requests({1: before}, {1: after})
    assert added == {}
    assert changed == {1: after}
    assert removed == {}


def test_diff_requests_added_changed_and_removed_together_dont_cross_contaminate():
    """one row added, one changed in place, one removed, all in the same tick"""
    stable = {"reqid": 1, "artist": "WNP Mock Artist", "title": "WNP Mock Song"}
    respun_before = {"reqid": 2, "artist": "WNP Mock Artist 2", "title": "WNP Mock Song 2"}
    respun_after = {"reqid": 2, "artist": "WNP Mock Artist 3", "title": "WNP Mock Song 3"}
    gone = {"reqid": 3, "artist": "Gone Artist", "title": "Gone Song"}
    new = {"reqid": 4, "artist": "New Artist", "title": "New Song"}

    previous = {1: stable, 2: respun_before, 3: gone}
    current = {1: stable, 2: respun_after, 4: new}

    added, changed, removed = Handler.diff_requests(previous, current)
    assert added == {4: new}
    assert changed == {2: respun_after}
    assert removed == {3: gone}


def test_strip_track_blobs_drops_blobs_and_dbid_keeps_everything_else():
    """the track-update wire shape: no METADATABLOBLIST keys, no dbid, rest intact"""
    metadata = dict.fromkeys(nowplaying.db.METADATABLOBLIST, b"binary data")
    metadata["dbid"] = 42
    metadata["coverurl"] = "cover/some-cachekey"
    metadata["artist"] = "WNP Mock Artist"
    metadata["title"] = "WNP Mock Song"

    stripped = Handler._strip_track_blobs(metadata)  # pylint: disable=protected-access

    for key in nowplaying.db.METADATABLOBLIST:
        assert key not in stripped
    assert "dbid" not in stripped
    assert stripped["coverurl"] == "cover/some-cachekey"
    assert stripped["artist"] == "WNP Mock Artist"
    assert stripped["title"] == "WNP Mock Song"


def _request_with_header(value):
    request = MagicMock()
    request.headers = {"X-WNP-Client-Session": value} if value is not None else {}
    return request


def test_session_id_accepts_well_formed_header():
    """a caller-supplied X-WNP-Client-Session is used verbatim when it's safe"""
    request = _request_with_header("my-id_123")
    assert Handler._session_id(request) == "my-id_123"  # pylint: disable=protected-access


def test_session_id_mints_when_header_absent():
    """no header at all -- fall back to a minted id, matching str(uuid.uuid4())[:8]"""
    request = _request_with_header(None)
    session_id = Handler._session_id(request)  # pylint: disable=protected-access
    assert len(session_id) == 8


def test_session_id_mints_when_header_empty():
    """an empty header is treated the same as an absent one"""
    request = _request_with_header("")
    session_id = Handler._session_id(request)  # pylint: disable=protected-access
    assert len(session_id) == 8


def test_session_id_rejects_newline_rather_than_logging_it_verbatim():
    """log-injection guard: a header can't smuggle a fake log line through"""
    request = _request_with_header("legit\nWARNING fake log line")
    session_id = Handler._session_id(request)  # pylint: disable=protected-access
    assert "\n" not in session_id
    assert len(session_id) == 8


def test_session_id_rejects_oversized_value():
    """the allow-list caps length at 64 chars"""
    request = _request_with_header("x" * 65)
    session_id = Handler._session_id(request)  # pylint: disable=protected-access
    assert len(session_id) == 8
