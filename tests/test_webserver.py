#!/usr/bin/env python3
''' test webserver '''

import asyncio
import logging
import socket
import sys

import pytest
import pytest_asyncio
import requests

import nowplaying.db  # pylint: disable=import-error
import nowplaying.subprocesses  # pylint: disable=import-error
import nowplaying.processes.webserver  # pylint: disable=import-error


def is_port_in_use(port: int) -> bool:
    ''' check if a port is in use '''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(('localhost', port)) == 0


@pytest_asyncio.fixture
async def getwebserver(bootstrap):
    ''' configure the webserver, dependents with prereqs '''
    config = bootstrap
    metadb = nowplaying.db.MetadataDB(initialize=True)
    logging.debug("test_webserver databasefile = %s", metadb.databasefile)
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.sync()
    port = config.cparser.value('weboutput/httpport', type=int)
    logging.debug('checking %s for use', port)
    while is_port_in_use(port):
        logging.debug('%s is in use; waiting', port)
        await asyncio.sleep(2)

    manager = nowplaying.subprocesses.SubprocessManager(config=config, testmode=True)
    manager.start_webserver()
    await asyncio.sleep(5)

    req = requests.get(f'http://localhost:{port}/internals', timeout=5)
    logging.debug("internals = %s", req.json())

    yield config, metadb
    manager.stop_all_processes()


@pytest.mark.asyncio
async def test_startstopwebserver(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test a simple start/stop '''
    config, metadb = getwebserver  #pylint: disable=unused-variable
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.sync()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_webserver_htmtest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' start webserver, read existing data, add new data, then read that '''
    config, metadb = getwebserver
    config.cparser.setValue('weboutput/htmltemplate',
                            config.getbundledir().joinpath('templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    await asyncio.sleep(10)

    logging.debug(config.cparser.value('weboutput/htmltemplate'))
    # handle no data, should return refresh

    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 202
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

    # handle first write

    await metadb.write_to_metadb(metadata={'title': 'testhtmtitle', 'artist': 'testhtmartist'})
    await asyncio.sleep(1)
    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testhtmartist - testhtmtitle'

    # another read should give us refresh

    await asyncio.sleep(1)
    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

    config.cparser.setValue('weboutput/once', False)
    config.cparser.sync()

    # flipping once to false should give us back same info

    await asyncio.sleep(1)
    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testhtmartist - testhtmtitle'

    # handle second write

    await metadb.write_to_metadb(metadata={
        'artist': 'artisthtm2',
        'title': 'titlehtm2',
    })
    await asyncio.sleep(1)
    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' artisthtm2 - titlehtm2'


@pytest.mark.asyncio
async def test_webserver_txttest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' start webserver, read existing data, add new data, then read that '''
    config, metadb = getwebserver
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue('weboutput/htmltemplate',
                            config.getbundledir().joinpath('templates', 'basic-plain.txt'))
    config.cparser.setValue('textoutput/txttemplate',
                            config.getbundledir().joinpath('templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    await asyncio.sleep(10)

    # handle no data, should return refresh

    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ''  # sourcery skip: simplify-empty-collection-comparison

    # should return empty
    req = requests.get('http://localhost:8899/v1/last', timeout=5)
    assert req.status_code == 200
    assert req.json() == {}
    # handle first write

    await metadb.write_to_metadb(metadata={'title': 'testtxttitle', 'artist': 'testtxtartist'})
    await asyncio.sleep(1)
    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testtxtartist - testtxttitle'

    req = requests.get('http://localhost:8899/v1/last', timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata['artist'] == 'testtxtartist'
    assert checkdata['title'] == 'testtxttitle'
    assert not checkdata.get('dbid')

    # another read should give us same info

    await asyncio.sleep(1)
    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testtxtartist - testtxttitle'

    req = requests.get('http://localhost:8899/v1/last', timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata['artist'] == 'testtxtartist'
    assert checkdata['title'] == 'testtxttitle'
    assert not checkdata.get('dbid')

    # handle second write

    await metadb.write_to_metadb(metadata={
        'artist': 'artisttxt2',
        'title': 'titletxt2',
    })
    await asyncio.sleep(1)
    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' artisttxt2 - titletxt2'

    req = requests.get('http://localhost:8899/v1/last', timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata['artist'] == 'artisttxt2'
    assert checkdata['title'] == 'titletxt2'
    assert not checkdata.get('dbid')


@pytest.mark.xfail(sys.platform == "darwin", reason='timesout on macos')
def test_webserver_gifwordstest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure gifwords works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/gifwords.htm', timeout=5)
    assert req.status_code == 200


def test_webserver_coverpng(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure coverpng works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/cover.png', timeout=5)
    assert req.status_code == 200


def test_webserver_artistfanart_test(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure artistfanart works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/artistfanart.htm', timeout=5)
    assert req.status_code == 202


def test_webserver_banner_test(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure banner works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/artistbanner.htm', timeout=5)
    assert req.status_code == 202

    req = requests.get('http://localhost:8899/artistbanner.png', timeout=5)
    assert req.status_code == 200


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot close fast enough")
def test_webserver_logo_test(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure banner works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/artistlogo.htm', timeout=5)
    assert req.status_code == 202

    req = requests.get('http://localhost:8899/artistlogo.png', timeout=5)
    assert req.status_code == 200


class TestKickOAuthCSRFProtection:
    """Test CSRF protection in Kick OAuth2 callback handler"""

    @pytest.mark.asyncio
    async def test_kickredirect_valid_state(self, getwebserver):
        """Test OAuth callback with valid state parameter"""
        config, metadb = getwebserver  # pylint: disable=unused-variable

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
        # Should attempt token exchange (will fail due to invalid credentials, but that means CSRF check passed)
        assert 'Token Exchange Failed' in req.text or 'Authentication Successful' in req.text

    @pytest.mark.asyncio
    async def test_kickredirect_invalid_state_csrf_attack(self, getwebserver):
        """Test OAuth callback with invalid state parameter (CSRF attack simulation)"""
        config, metadb = getwebserver  # pylint: disable=unused-variable

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

    @pytest.mark.asyncio
    async def test_kickredirect_missing_state_parameter(self, getwebserver):
        """Test OAuth callback with missing state parameter"""
        config, metadb = getwebserver  # pylint: disable=unused-variable

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

    @pytest.mark.asyncio
    async def test_kickredirect_no_stored_state_expired_session(self, getwebserver):
        """Test OAuth callback when no state is stored (expired session)"""
        config, metadb = getwebserver  # pylint: disable=unused-variable

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

    @pytest.mark.asyncio
    async def test_kickredirect_missing_authorization_code(self, getwebserver):
        """Test OAuth callback with missing authorization code"""
        config, metadb = getwebserver  # pylint: disable=unused-variable

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

    @pytest.mark.asyncio
    async def test_kickredirect_oauth_error_response(self, getwebserver):
        """Test OAuth callback with OAuth error response"""
        config, metadb = getwebserver  # pylint: disable=unused-variable

        # Test OAuth error response
        port = config.cparser.value('weboutput/httpport', type=int)
        req = requests.get(
            f'http://localhost:{port}/kickredirect?error=access_denied&error_description=User denied access',
            timeout=5)

        # Should return OAuth error page
        assert req.status_code == 200
        assert 'text/html' in req.headers.get('content-type', '')
        assert 'OAuth2 Authentication Failed' in req.text
        assert 'access_denied' in req.text
        assert 'User denied access' in req.text

    @pytest.mark.asyncio
    async def test_kickredirect_xss_protection_in_error_parameters(self, getwebserver):
        """Test that OAuth error parameters are properly escaped to prevent XSS"""
        config, metadb = getwebserver  # pylint: disable=unused-variable

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
