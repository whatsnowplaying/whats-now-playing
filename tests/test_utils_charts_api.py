#!/usr/bin/env python3
"""Tests for charts API utilities"""

import contextlib
import http.client
import json
import logging
import socket
import threading
import unittest.mock
import urllib.error
import urllib.request

import pytest

import nowplaying.upgrades.platform
import nowplaying.utils.charts_api
import nowplaying.version  # pylint: disable=import-error, no-name-in-module

FAKE_CHARTS_KEY = "wnpfeedbacktestkey0123456789"  # pragma: allowlist secret


def test_constants():
    """Test that API constants are defined correctly"""
    assert nowplaying.utils.charts_api.LOCAL_BASE_URL == "http://localhost:8000"
    assert nowplaying.utils.charts_api.PROD_BASE_URL == "https://whatsnowplaying.com"


def test_get_charts_base_url_no_config():
    """Test that get_charts_base_url returns PROD when config is None"""
    url = nowplaying.utils.charts_api.get_charts_base_url(None)
    assert url == nowplaying.utils.charts_api.PROD_BASE_URL


def test_get_charts_base_url_debug_false(bootstrap):
    """Test that get_charts_base_url returns PROD when debug=False"""
    bootstrap.cparser.setValue("charts/debug", False)
    url = nowplaying.utils.charts_api.get_charts_base_url(bootstrap)
    assert url == nowplaying.utils.charts_api.PROD_BASE_URL


def test_get_charts_base_url_debug_true(bootstrap):
    """Test that get_charts_base_url returns LOCAL when debug=True"""
    bootstrap.cparser.setValue("charts/debug", True)
    url = nowplaying.utils.charts_api.get_charts_base_url(bootstrap)
    assert url == nowplaying.utils.charts_api.LOCAL_BASE_URL


def test_get_charts_base_url_default(bootstrap):
    """Test that get_charts_base_url returns PROD by default"""
    # Don't set charts/debug at all
    url = nowplaying.utils.charts_api.get_charts_base_url(bootstrap)
    assert url == nowplaying.utils.charts_api.PROD_BASE_URL


def test_http_status_actions_structure():
    """Test that HTTP_STATUS_ACTIONS has the expected structure"""
    actions = nowplaying.utils.charts_api.HTTP_STATUS_ACTIONS

    # Check that known status codes are present
    assert 200 in actions
    assert 400 in actions
    assert 401 in actions
    assert 403 in actions
    assert 404 in actions
    assert 429 in actions

    # Check structure of each entry (action, log_level, message)
    for entry in actions.values():
        action, log_level, message = entry
        assert action in ("success", "retry", "drop")
        assert log_level in ("debug", "info", "warning", "error")
        assert isinstance(message, str)
        assert len(message) > 0


@pytest.mark.parametrize(
    "status,expected_action",
    [
        (200, "success"),
        (302, "retry"),  # Redirect (3xx) currently treated as retry
        (400, "drop"),
        (401, "retry"),
        (403, "retry"),
        (404, "drop"),
        (405, "drop"),
        (429, "retry"),
        (500, "retry"),  # Server error should retry
        (502, "retry"),  # Bad gateway should retry
        (503, "retry"),  # Service unavailable should retry
        (422, "drop"),  # Unprocessable entity is client error
        (499, "drop"),  # Unknown 4xx should drop
    ],
)
def test_handle_http_response_actions(status, expected_action, caplog):
    """Test that handle_http_response returns correct actions for status codes"""
    with caplog.at_level(logging.DEBUG):
        action = nowplaying.utils.charts_api.handle_http_response(status, "test response")
        assert action == expected_action


def test_handle_http_response_logging(caplog):
    """Test that handle_http_response logs messages appropriately"""
    with caplog.at_level(logging.DEBUG):
        nowplaying.utils.charts_api.handle_http_response(200, "success message")
        # 200 success responses should not log (to avoid spam)
        assert "Charts server accepted submission" not in caplog.text

    caplog.clear()

    with caplog.at_level(logging.WARNING):
        nowplaying.utils.charts_api.handle_http_response(429, "rate limited")
        assert "Charts server rate limited" in caplog.text
        assert "rate limited" in caplog.text

    caplog.clear()

    with caplog.at_level(logging.ERROR):
        nowplaying.utils.charts_api.handle_http_response(401, "unauthorized")
        assert "Charts server authentication failed" in caplog.text
        assert "unauthorized" in caplog.text


@pytest.mark.parametrize(
    "key,expected_valid",
    [
        ("wnp_charts_1234567890abcdef", True),  # pragma: allowlist secret
        ("valid_key_12345", True),  # Valid key with minimum length
        ("short", False),  # Too short
        ("", False),  # Empty
        ("   ", False),  # Whitespace only
        (None, False),  # None type
        (123456, False),  # Not a string
        ("a" * 100, True),  # pragma: allowlist secret
    ],
)
def test_is_valid_api_key(key, expected_valid):
    """Test API key validation"""
    result = nowplaying.utils.charts_api.is_valid_api_key(key)
    assert result == expected_valid


def test_handle_http_response_empty_text():
    """Test handle_http_response with empty response text"""
    action = nowplaying.utils.charts_api.handle_http_response(200, "")
    assert action == "success"

    action = nowplaying.utils.charts_api.handle_http_response(500, "")
    assert action == "retry"


def test_handle_http_response_4xx_range(caplog):
    """Test that unhandled 4xx errors are dropped"""
    with caplog.at_level(logging.ERROR):
        action = nowplaying.utils.charts_api.handle_http_response(418, "I'm a teapot")
        assert action == "drop"
        assert "Charts server client error 418" in caplog.text


def test_handle_http_response_5xx_range(caplog):
    """Test that unhandled 5xx errors are retried"""
    with caplog.at_level(logging.ERROR):
        action = nowplaying.utils.charts_api.handle_http_response(599, "Unknown server error")
        assert action == "retry"
        assert "Charts server error 599" in caplog.text


@pytest.fixture
def feedback_server(bootstrap, httpserver):  # pylint: disable=redefined-outer-name
    """A local charts server, with a charts key configured that must never be sent."""
    bootstrap.cparser.setValue("charts/charts_key", FAKE_CHARTS_KEY)
    return httpserver


def _base_url(server) -> str:
    return server.url_for("").rstrip("/")


@pytest.mark.parametrize(
    "code,body,expected",
    [
        (200, {"status": "ok"}, ("success", None)),
        (400, {"error": "text too long"}, ("rejected", "text too long")),
        (429, {"error": "slow down"}, ("rate_limited", "slow down")),
        (500, {"error": "boom"}, ("server_error", "boom")),
        (400, {"error": {"nested": 1}}, ("rejected", None)),
    ],
)
def test_submit_feedback_status(feedback_server, code, body, expected):  # pylint: disable=redefined-outer-name
    """Server responses map to the statuses the dialog shows."""
    feedback_server.expect_request("/api/v1/feedback", method="POST").respond_with_json(
        body, status=code
    )
    assert (
        nowplaying.utils.charts_api.submit_feedback(_base_url(feedback_server), "hello")
        == expected
    )


def test_submit_feedback_non_json_error(feedback_server):  # pylint: disable=redefined-outer-name
    """A non-JSON error body still yields the status, without detail."""
    feedback_server.expect_request("/api/v1/feedback").respond_with_data(
        "<html>nope</html>", status=429
    )
    assert nowplaying.utils.charts_api.submit_feedback(_base_url(feedback_server), "hello") == (
        "rate_limited",
        None,
    )


def test_submit_feedback_payload_is_anonymous(feedback_server):  # pylint: disable=redefined-outer-name
    """Exactly text/version/os/chipset go out, and the charts key never does."""
    feedback_server.expect_request("/api/v1/feedback", method="POST").respond_with_json(
        {"status": "ok"}
    )
    status, _ = nowplaying.utils.charts_api.submit_feedback(
        _base_url(feedback_server), "  great app  \n"
    )
    assert status == "success"

    request, _ = feedback_server.log[0]
    info = nowplaying.upgrades.platform.PlatformDetector.get_platform_info()
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.get_data()) == {
        "text": "great app",
        "version": nowplaying.version.__VERSION__,  # pylint: disable=no-member
        "os": info["os"],
        "chipset": info["chipset"],
    }
    assert "X-WNP-Charts-Key" not in request.headers
    assert FAKE_CHARTS_KEY not in request.get_data(as_text=True)
    for name, value in request.headers.items():
        assert FAKE_CHARTS_KEY not in name
        assert FAKE_CHARTS_KEY not in value


@pytest.mark.parametrize(
    "text",
    ["", "   \n\t ", "x" * (nowplaying.utils.charts_api.FEEDBACK_MAX_LENGTH + 1)],
    ids=["empty", "whitespace", "too-long"],
)
def test_submit_feedback_invalid_not_sent(feedback_server, text):  # pylint: disable=redefined-outer-name
    """Empty or oversize text is refused locally and never hits the network."""
    assert nowplaying.utils.charts_api.submit_feedback(_base_url(feedback_server), text) == (
        "invalid",
        None,
    )
    assert not feedback_server.log


def test_submit_feedback_max_length_after_strip(feedback_server):  # pylint: disable=redefined-outer-name
    """The limit applies to the stripped text, matching the server."""
    feedback_server.expect_request("/api/v1/feedback").respond_with_json({"status": "ok"})
    text = " " + "x" * nowplaying.utils.charts_api.FEEDBACK_MAX_LENGTH + " "
    assert nowplaying.utils.charts_api.submit_feedback(_base_url(feedback_server), text) == (
        "success",
        None,
    )


def test_submit_feedback_network_error():
    """An unreachable server is a network error, not an exception."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert nowplaying.utils.charts_api.submit_feedback(f"http://127.0.0.1:{port}", "hello") == (
        "network_error",
        None,
    )


def _raw_http_server(response: bytes) -> tuple[str, threading.Thread]:
    """Serve one connection with exactly these bytes, for responses
    pytest-httpserver cannot produce (e.g. a body shorter than its length)."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        with listener:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(5)
                data = b""
                while b"\r\n\r\n" not in data:
                    data += conn.recv(65536)
                head, _, body = data.partition(b"\r\n\r\n")
                length = 0
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                while len(body) < length:
                    body += conn.recv(65536)
                # The client may stop reading at its cap and hang up.
                with contextlib.suppress(OSError):
                    conn.sendall(response)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}", thread


@pytest.mark.parametrize(
    "response,expected",
    [
        (
            b"HTTP/1.1 500 X\r\nContent-Type: application/json\r\n"
            b'Content-Length: 100\r\n\r\n{"error":',
            ("server_error", None),
        ),
        (
            b"HTTP/1.1 400 X\r\nContent-Length: 200000\r\n\r\n" + b"[" * 200000,
            ("rejected", None),
        ),
    ],
    ids=["truncated", "nested"],
)
def test_submit_feedback_unusable_error_body(response, expected):
    """A truncated or pathologically nested error body still yields a status."""
    url, thread = _raw_http_server(response)
    assert nowplaying.utils.charts_api.submit_feedback(url, "hello") == expected
    thread.join(5)


@pytest.mark.parametrize(
    "exc",
    [http.client.IncompleteRead(b"{"), RecursionError("deep"), http.client.HTTPException()],
)
def test_submit_feedback_error_body_read_raises(feedback_server, exc):  # pylint: disable=redefined-outer-name
    """Whatever reading or decoding the error body raises, a status comes back."""
    feedback_server.expect_request("/api/v1/feedback").respond_with_json(
        {"error": "nope"}, status=400
    )
    with unittest.mock.patch.object(http.client.HTTPResponse, "read", side_effect=exc):
        assert nowplaying.utils.charts_api.submit_feedback(
            _base_url(feedback_server), "hello"
        ) == ("rejected", None)


def test_submit_feedback_error_body_read_is_capped(feedback_server):  # pylint: disable=redefined-outer-name
    """Only the first FEEDBACK_ERROR_BODY_LIMIT bytes of an error body are read."""
    feedback_server.expect_request("/api/v1/feedback").respond_with_json(
        {"error": "x" * nowplaying.utils.charts_api.FEEDBACK_ERROR_BODY_LIMIT}, status=400
    )
    assert nowplaying.utils.charts_api.submit_feedback(_base_url(feedback_server), "hello") == (
        "rejected",
        None,
    )


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_submit_feedback_redirect_is_not_followed(feedback_server, code):  # pylint: disable=redefined-outer-name
    """A redirect is a server error; urllib must not turn the POST into a GET elsewhere."""
    feedback_server.expect_request("/api/v1/feedback").respond_with_data(
        "", status=code, headers={"Location": feedback_server.url_for("/elsewhere")}
    )
    feedback_server.expect_request("/elsewhere").respond_with_json({"status": "ok"})
    assert nowplaying.utils.charts_api.submit_feedback(_base_url(feedback_server), "hello") == (
        "server_error",
        None,
    )
    assert [request.path for request, _ in feedback_server.log] == ["/api/v1/feedback"]


def test_submit_feedback_user_agent(feedback_server):  # pylint: disable=redefined-outer-name
    """The request identifies the app, not Python-urllib."""
    feedback_server.expect_request("/api/v1/feedback").respond_with_json({"status": "ok"})
    nowplaying.utils.charts_api.submit_feedback(_base_url(feedback_server), "hello")
    request, _ = feedback_server.log[0]
    assert (
        request.headers["User-Agent"] == f"whats-now-playing/{nowplaying.version.__VERSION__}"  # pylint: disable=no-member
    )


def test_submit_feedback_does_not_install_opener(feedback_server):  # pylint: disable=redefined-outer-name
    """Refusing redirects is scoped to this call, not urllib's global opener."""
    feedback_server.expect_request("/api/v1/feedback").respond_with_json({"status": "ok"})
    before = urllib.request._opener  # pylint: disable=protected-access
    nowplaying.utils.charts_api.submit_feedback(_base_url(feedback_server), "hello")
    assert urllib.request._opener is before  # pylint: disable=protected-access
