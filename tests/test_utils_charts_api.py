#!/usr/bin/env python3
"""Tests for charts API utilities"""

import logging

import pytest

import nowplaying.utils.charts_api


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
