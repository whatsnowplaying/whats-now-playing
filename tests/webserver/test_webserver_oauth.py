#!/usr/bin/env python3
"""test webserver OAuth and security functionality"""

import base64

import requests

# Kick OAuth CSRF protection tests


def test_kickredirect_valid_state(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with valid state parameter"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Set up valid OAuth session state using new session-based format
    session_id = "testsession123"
    state_data = f"{session_id}:randomstate456"
    encoded_state = base64.urlsafe_b64encode(state_data.encode("utf-8")).decode("utf-8").rstrip("=")

    config.cparser.setValue(f"kick/temp_state_{session_id}", encoded_state)
    config.cparser.setValue(f"kick/temp_code_verifier_{session_id}", "test_verifier")
    config.cparser.setValue("kick/clientid", "test_client")
    config.cparser.setValue("kick/redirecturi", "http://localhost:8899/kickredirect")
    config.cparser.sync()

    # Test valid state parameter - should attempt token exchange (will fail but that's expected)
    port = config.cparser.value("weboutput/httpport", type=int)
    req = requests.get(
        f"http://localhost:{port}/kickredirect?code=test_code&state={encoded_state}", timeout=5
    )

    # Should get HTML response (not error page)
    assert req.status_code == 200
    assert "text/html" in req.headers.get("content-type", "")
    # Should attempt token exchange (will fail due to invalid credentials, but CSRF check passed)
    assert "Token Exchange Failed" in req.text or "Authentication Successful" in req.text


def test_kickredirect_invalid_state_csrf_attack(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with invalid state parameter (CSRF attack simulation)"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Set up valid OAuth session state using new session-based format
    session_id = "testsession123"
    state_data = f"{session_id}:randomstate456"
    valid_encoded_state = (
        base64.urlsafe_b64encode(state_data.encode("utf-8")).decode("utf-8").rstrip("=")
    )

    # Create malicious state with different content
    malicious_state_data = "attackersession:maliciousdata"
    malicious_encoded_state = (
        base64.urlsafe_b64encode(malicious_state_data.encode("utf-8")).decode("utf-8").rstrip("=")
    )

    config.cparser.setValue(f"kick/temp_state_{session_id}", valid_encoded_state)
    config.cparser.setValue(f"kick/temp_code_verifier_{session_id}", "test_verifier")
    config.cparser.sync()

    # Test invalid state parameter (CSRF attack)
    port = config.cparser.value("weboutput/httpport", type=int)
    req = requests.get(
        f"http://localhost:{port}/kickredirect?code=test_code&state={malicious_encoded_state}",
        timeout=5,
    )

    # Should return security error page (invalid session for non-existent session ID)
    assert req.status_code == 200
    assert "text/html" in req.headers.get("content-type", "")
    assert "Invalid OAuth2 Session" in req.text
    assert "authentication session has expired" in req.text


def test_kickredirect_missing_state_parameter(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with missing state parameter"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Set up valid OAuth session state using new session-based format
    session_id = "testsession123"
    state_data = f"{session_id}:randomstate456"
    valid_encoded_state = (
        base64.urlsafe_b64encode(state_data.encode("utf-8")).decode("utf-8").rstrip("=")
    )

    config.cparser.setValue(f"kick/temp_state_{session_id}", valid_encoded_state)
    config.cparser.setValue(f"kick/temp_code_verifier_{session_id}", "test_verifier")
    config.cparser.sync()

    # Test missing state parameter
    port = config.cparser.value("weboutput/httpport", type=int)
    req = requests.get(f"http://localhost:{port}/kickredirect?code=test_code", timeout=5)

    # Should return security error page (missing state parameter)
    assert req.status_code == 200
    assert "text/html" in req.headers.get("content-type", "")
    assert "Invalid OAuth2 Session" in req.text
    assert "authentication session has expired" in req.text


def test_kickredirect_no_stored_state_expired_session(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback when no state is stored (expired session)"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Create state with session ID that won't have stored PKCE params (simulating expired session)
    state_data = "nonexistentsession:randomstate789"
    encoded_state = base64.urlsafe_b64encode(state_data.encode("utf-8")).decode("utf-8").rstrip("=")

    # Test callback with state but no stored session
    port = config.cparser.value("weboutput/httpport", type=int)
    req = requests.get(
        f"http://localhost:{port}/kickredirect?code=test_code&state={encoded_state}", timeout=5
    )

    # Should return invalid session error
    assert req.status_code == 200
    assert "text/html" in req.headers.get("content-type", "")
    assert "Invalid OAuth2 Session" in req.text
    assert "authentication session has expired" in req.text


def test_kickredirect_missing_authorization_code(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with missing authorization code"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Set up valid OAuth session state using new session-based format
    session_id = "testsession123"
    state_data = f"{session_id}:randomstate456"
    encoded_state = base64.urlsafe_b64encode(state_data.encode("utf-8")).decode("utf-8").rstrip("=")

    config.cparser.setValue(f"kick/temp_state_{session_id}", encoded_state)
    config.cparser.setValue(f"kick/temp_code_verifier_{session_id}", "test_verifier")
    config.cparser.sync()

    # Test missing authorization code
    port = config.cparser.value("weboutput/httpport", type=int)
    req = requests.get(f"http://localhost:{port}/kickredirect?state={encoded_state}", timeout=5)

    # Should return no authorization code error
    assert req.status_code == 200
    assert "text/html" in req.headers.get("content-type", "")
    assert "No Authorization Code Received" in req.text


def test_kickredirect_oauth_error_response(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with OAuth error response"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Test OAuth error response
    port = config.cparser.value("weboutput/httpport", type=int)
    req = requests.get(
        f"http://localhost:{port}/kickredirect?error=access_denied&"
        "error_description=User denied access",
        timeout=5,
    )

    # Should return OAuth error page
    assert req.status_code == 200
    assert "text/html" in req.headers.get("content-type", "")
    assert "OAuth2 Authentication Failed" in req.text
    assert "access_denied" in req.text
    assert "User denied access" in req.text


def test_kickredirect_xss_protection_in_error_parameters(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test that OAuth error parameters are properly escaped to prevent XSS"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Test XSS attempt in OAuth error parameters
    xss_payload = '<script>alert("XSS")</script>'
    xss_description = '<img src=x onerror=alert("XSS2")>'

    port = config.cparser.value("weboutput/httpport", type=int)
    req = requests.get(
        f"http://localhost:{port}/kickredirect",
        params={"error": xss_payload, "error_description": xss_description},
        timeout=5,
    )

    # Should return escaped HTML (no script execution)
    assert req.status_code == 200
    assert "text/html" in req.headers.get("content-type", "")
    assert "OAuth2 Authentication Failed" in req.text

    # Verify XSS payloads are escaped
    assert "<script>" not in req.text  # Raw script tags should be escaped
    assert "&lt;script&gt;" in req.text  # Should be HTML-escaped
    assert "<img" not in req.text  # Raw img tags should be escaped
    assert "&lt;img" in req.text  # Should be HTML-escaped
