#!/usr/bin/env python3
''' test webserver OAuth and security functionality '''

import contextlib
import logging
import os
import pathlib
import socket
import tempfile
import time
import unittest.mock

import pytest
import requests

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.config  # pylint: disable=import-error
import nowplaying.db  # pylint: disable=import-error
import nowplaying.subprocesses  # pylint: disable=import-error


def is_port_in_use(port: int) -> bool:
    ''' check if a port is in use '''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(('localhost', port)) == 0


@pytest.fixture(scope="module")
def shared_webserver_config(pytestconfig):  # pylint: disable=redefined-outer-name
    ''' module-scoped webserver configuration - sync to avoid event loop issues '''
    with contextlib.suppress(PermissionError):  # Windows blows
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as newpath:

            dbinit_patch = unittest.mock.patch('nowplaying.db.MetadataDB.init_db_var')
            dbinit_mock = dbinit_patch.start()
            dbdir = pathlib.Path(newpath).joinpath('mdb')
            dbdir.mkdir()
            dbfile = dbdir.joinpath('test.db')
            dbinit_mock.return_value = dbfile

            with unittest.mock.patch.dict(os.environ, {
                    "WNP_CONFIG_TEST_DIR": str(newpath),
                    "WNP_METADB_TEST_FILE": str(dbfile)
            }):
                bundledir = pathlib.Path(pytestconfig.rootpath).joinpath('nowplaying')
                nowplaying.bootstrap.set_qt_names(domain='com.github.whatsnowplaying.testsuite',
                                                  appname='testsuite')
                config = nowplaying.config.ConfigFile(bundledir=bundledir,
                                                      logpath=newpath,
                                                      testmode=True)
                config.cparser.setValue('acoustidmb/enabled', False)
                config.cparser.setValue('weboutput/httpenabled', 'true')
                config.cparser.sync()

                metadb = nowplaying.db.MetadataDB(initialize=True) # pylint: disable=no-member
                logging.debug("shared webserver databasefile = %s", metadb.databasefile)

                port = config.cparser.value('weboutput/httpport', type=int)
                logging.debug('checking %s for use', port)
                while is_port_in_use(port):
                    logging.debug('%s is in use; waiting', port)
                    time.sleep(2)

                manager = nowplaying.subprocesses.SubprocessManager(config=config, testmode=True)
                manager.start_webserver()
                time.sleep(5)

                req = requests.get(f'http://localhost:{port}/internals', timeout=5)
                logging.debug("internals = %s", req.json())

                # Store the actual port since config gets cleared by autouse fixtures
                yield config, metadb, manager, port

                manager.stop_all_processes()
                time.sleep(2)

                # Try to vacuum database, but handle file locking gracefully
                try:
                    metadb.vacuum_database()
                except Exception as error: # pylint: disable=broad-exception-caught
                    logging.warning("Could not vacuum database during cleanup: %s", error)
                dbinit_mock.stop()


@pytest.fixture
def reset_oauth_state(shared_webserver_config):  # pylint: disable=redefined-outer-name
    ''' reset OAuth state before each test '''
    config, metadb, manager, port = shared_webserver_config  # pylint: disable=unused-variable

    # Re-enable webserver settings (in case autouse clear_old_testsuite cleared them)
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue('weboutput/httpport', port)  # Restore the actual port
    config.cparser.sync()

    # Clear any kick OAuth state
    config.cparser.remove('kick/temp_state')
    config.cparser.remove('kick/temp_code_verifier')
    config.cparser.remove('kick/clientid')
    config.cparser.remove('kick/redirecturi')
    config.cparser.sync()

    yield config, metadb


# Kick OAuth CSRF protection tests

def test_kickredirect_valid_state(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with valid state parameter"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Set up valid OAuth session state
    valid_state = 'valid_state_12345678'
    config.cparser.setValue('kick/temp_state', valid_state)
    config.cparser.setValue('kick/temp_code_verifier', 'test_verifier')
    config.cparser.setValue('kick/clientid', 'test_client')
    config.cparser.setValue('kick/redirecturi', 'http://localhost:8899/kickredirect')
    config.cparser.sync()

    # Test valid state parameter - should attempt token exchange (will fail but that's expected)
    port = config.cparser.value('weboutput/httpport', type=int)
    req = requests.get(
        f'http://localhost:{port}/kickredirect?code=test_code&state={valid_state}', timeout=5)

    # Should get HTML response (not error page)
    assert req.status_code == 200
    assert 'text/html' in req.headers.get('content-type', '')
    # Should attempt token exchange (will fail due to invalid credentials, but CSRF check passed)
    assert ('Token Exchange Failed' in req.text or 'Authentication Successful' in req.text)


def test_kickredirect_invalid_state_csrf_attack(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with invalid state parameter (CSRF attack simulation)"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Set up valid OAuth session state
    valid_state = 'valid_state_12345678'
    malicious_state = 'malicious_state_attacker'
    config.cparser.setValue('kick/temp_state', valid_state)
    config.cparser.setValue('kick/temp_code_verifier', 'test_verifier')
    config.cparser.sync()

    # Test invalid state parameter (CSRF attack)
    port = config.cparser.value('weboutput/httpport', type=int)
    req = requests.get(
        f'http://localhost:{port}/kickredirect?code=test_code&state={malicious_state}',
        timeout=5)

    # Should return security error page
    assert req.status_code == 200
    assert 'text/html' in req.headers.get('content-type', '')
    assert 'OAuth2 State Mismatch' in req.text
    assert 'Security Warning' in req.text
    assert 'CSRF' in req.text


def test_kickredirect_missing_state_parameter(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with missing state parameter"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Set up valid OAuth session state
    valid_state = 'valid_state_12345678'
    config.cparser.setValue('kick/temp_state', valid_state)
    config.cparser.setValue('kick/temp_code_verifier', 'test_verifier')
    config.cparser.sync()

    # Test missing state parameter
    port = config.cparser.value('weboutput/httpport', type=int)
    req = requests.get(f'http://localhost:{port}/kickredirect?code=test_code', timeout=5)

    # Should return security error page
    assert req.status_code == 200
    assert 'text/html' in req.headers.get('content-type', '')
    assert 'OAuth2 State Mismatch' in req.text
    assert 'Security Warning' in req.text


def test_kickredirect_no_stored_state_expired_session(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback when no state is stored (expired session)"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Ensure no stored state (simulating expired session)
    config.cparser.remove('kick/temp_state')
    config.cparser.sync()

    # Test callback with state but no stored session
    port = config.cparser.value('weboutput/httpport', type=int)
    req = requests.get(f'http://localhost:{port}/kickredirect?code=test_code&state=some_state',
                       timeout=5)

    # Should return invalid session error
    assert req.status_code == 200
    assert 'text/html' in req.headers.get('content-type', '')
    assert 'Invalid OAuth2 Session' in req.text
    assert 'authentication session has expired' in req.text


def test_kickredirect_missing_authorization_code(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with missing authorization code"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Set up valid OAuth session state
    valid_state = 'valid_state_12345678'
    config.cparser.setValue('kick/temp_state', valid_state)
    config.cparser.sync()

    # Test missing authorization code
    port = config.cparser.value('weboutput/httpport', type=int)
    req = requests.get(f'http://localhost:{port}/kickredirect?state={valid_state}', timeout=5)

    # Should return no authorization code error
    assert req.status_code == 200
    assert 'text/html' in req.headers.get('content-type', '')
    assert 'No Authorization Code Received' in req.text


def test_kickredirect_oauth_error_response(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test OAuth callback with OAuth error response"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Test OAuth error response
    port = config.cparser.value('weboutput/httpport', type=int)
    req = requests.get(
        f'http://localhost:{port}/kickredirect?error=access_denied&'
        'error_description=User denied access',
        timeout=5)

    # Should return OAuth error page
    assert req.status_code == 200
    assert 'text/html' in req.headers.get('content-type', '')
    assert 'OAuth2 Authentication Failed' in req.text
    assert 'access_denied' in req.text
    assert 'User denied access' in req.text


def test_kickredirect_xss_protection_in_error_parameters(reset_oauth_state):  # pylint: disable=redefined-outer-name
    """Test that OAuth error parameters are properly escaped to prevent XSS"""
    config, metadb = reset_oauth_state  # pylint: disable=unused-variable

    # Test XSS attempt in OAuth error parameters
    xss_payload = '<script>alert("XSS")</script>'
    xss_description = '<img src=x onerror=alert("XSS2")>'

    port = config.cparser.value('weboutput/httpport', type=int)
    req = requests.get(f'http://localhost:{port}/kickredirect',
                       params={
                           'error': xss_payload,
                           'error_description': xss_description
                       },
                       timeout=5)

    # Should return escaped HTML (no script execution)
    assert req.status_code == 200
    assert 'text/html' in req.headers.get('content-type', '')
    assert 'OAuth2 Authentication Failed' in req.text

    # Verify XSS payloads are escaped
    assert '<script>' not in req.text  # Raw script tags should be escaped
    assert '&lt;script&gt;' in req.text  # Should be HTML-escaped
    assert '<img' not in req.text  # Raw img tags should be escaped
    assert '&lt;img' in req.text  # Should be HTML-escaped
