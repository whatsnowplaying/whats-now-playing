#!/usr/bin/env python3
''' test jriver input plugin '''

from unittest.mock import MagicMock, patch

import aiohttp
import pytest
import pytest_asyncio
from aioresponses import aioresponses

import nowplaying.inputs.jriver  # pylint: disable=import-error,no-name-in-module


@pytest_asyncio.fixture
async def jriver_plugin_with_session():
    """Create JRiver plugin with real aiohttp session for testing"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.session = aiohttp.ClientSession()
    yield plugin
    await plugin.session.close()


@pytest.fixture
def jriver_bootstrap(bootstrap):
    ''' bootstrap test '''
    config = bootstrap
    config.cparser.setValue('jriver/host', '192.168.1.100')
    config.cparser.setValue('jriver/port', '52199')
    config.cparser.setValue('jriver/username', 'testuser')
    config.cparser.setValue('jriver/password', 'testpass')
    config.cparser.setValue('jriver/access_key', 'testkey')
    config.cparser.sync()
    return config


def test_plugin_init():
    """Test plugin initialization"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    assert plugin.displayname == "JRiver Media Center"
    assert plugin.host is None
    assert plugin.port is None
    assert plugin.token is None
    assert plugin.base_url is None


def test_plugin_defaults():
    """Test default configuration values"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    mock_qsettings = MagicMock()
    plugin.defaults(mock_qsettings)

    mock_qsettings.setValue.assert_any_call('jriver/host', None)
    mock_qsettings.setValue.assert_any_call('jriver/port', '52199')
    mock_qsettings.setValue.assert_any_call('jriver/username', None)
    mock_qsettings.setValue.assert_any_call('jriver/password', None)
    mock_qsettings.setValue.assert_any_call('jriver/access_key', None)


def test_plugin_mixmodes():
    """Test mix mode functionality"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    assert plugin.validmixmodes() == ['newest']
    assert plugin.setmixmode('any') == 'newest'
    assert plugin.getmixmode() == 'newest'


def test_settings_ui_load(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test loading settings into UI"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member
    mock_qwidget = MagicMock()

    plugin.load_settingsui(mock_qwidget)

    mock_qwidget.host_lineedit.setText.assert_called_once_with('192.168.1.100')
    mock_qwidget.port_lineedit.setText.assert_called_once_with('52199')
    mock_qwidget.username_lineedit.setText.assert_called_once_with('testuser')
    mock_qwidget.password_lineedit.setText.assert_called_once_with('testpass')
    mock_qwidget.access_key_lineedit.setText.assert_called_once_with('testkey')


def test_settings_ui_save(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test saving settings from UI"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member
    mock_qwidget = MagicMock()
    mock_qwidget.host_lineedit.text.return_value = 'localhost'
    mock_qwidget.port_lineedit.text.return_value = '12345'
    mock_qwidget.username_lineedit.text.return_value = 'newuser'
    mock_qwidget.password_lineedit.text.return_value = 'newpass'
    mock_qwidget.access_key_lineedit.text.return_value = 'newkey'

    plugin.save_settingsui(mock_qwidget)

    assert plugin.config.cparser.value('jriver/host') == 'localhost'
    assert plugin.config.cparser.value('jriver/port') == '12345'
    assert plugin.config.cparser.value('jriver/username') == 'newuser'
    assert plugin.config.cparser.value('jriver/password') == 'newpass'
    assert plugin.config.cparser.value('jriver/access_key') == 'newkey'


def test_settings_ui_save_strips_whitespace(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test saving settings from UI strips whitespace"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member
    mock_qwidget = MagicMock()
    mock_qwidget.host_lineedit.text.return_value = '  localhost  '
    mock_qwidget.port_lineedit.text.return_value = '  12345  '
    mock_qwidget.username_lineedit.text.return_value = '  newuser  '
    mock_qwidget.password_lineedit.text.return_value = '  newpass  '
    mock_qwidget.access_key_lineedit.text.return_value = '  newkey  '

    plugin.save_settingsui(mock_qwidget)

    assert plugin.config.cparser.value('jriver/host') == 'localhost'
    assert plugin.config.cparser.value('jriver/port') == '12345'
    assert plugin.config.cparser.value('jriver/username') == 'newuser'
    assert plugin.config.cparser.value('jriver/password') == 'newpass'
    assert plugin.config.cparser.value('jriver/access_key') == 'newkey'


def test_settings_ui_save_handles_empty_strings(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test saving settings from UI handles empty strings and whitespace-only strings"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member
    mock_qwidget = MagicMock()
    mock_qwidget.host_lineedit.text.return_value = 'localhost'
    mock_qwidget.port_lineedit.text.return_value = '52199'
    mock_qwidget.username_lineedit.text.return_value = '   '  # whitespace-only
    mock_qwidget.password_lineedit.text.return_value = ''     # empty string
    mock_qwidget.access_key_lineedit.text.return_value = '  '  # whitespace-only

    plugin.save_settingsui(mock_qwidget)

    assert plugin.config.cparser.value('jriver/host') == 'localhost'
    assert plugin.config.cparser.value('jriver/port') == '52199'
    assert plugin.config.cparser.value('jriver/username') == ''  # stripped to empty
    assert plugin.config.cparser.value('jriver/password') == ''  # remains empty
    assert plugin.config.cparser.value('jriver/access_key') == ''  # stripped to empty


def test_settings_ui_description():
    """Test settings UI description"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    mock_qwidget = MagicMock()

    plugin.desc_settingsui(mock_qwidget)

    expected_text = ('This plugin provides support for JRiver Media Center via MCWS API. '
                     'Configure the host/IP and port of your JRiver server. '
                     'Username/password are optional if authentication is not required. '
                     'File paths are automatically retrieved for local connections only '
                     '(localhost, private IPs, and .local/.lan/.home/.internal domains).')
    mock_qwidget.setText.assert_called_once_with(expected_text)


@pytest.mark.asyncio
async def test_start_no_host():
    """Test start() with no host configured"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    mock_config = MagicMock()
    mock_config.cparser.value.return_value = None
    plugin.config = mock_config

    result = await plugin.start()
    assert result is False


@pytest.mark.asyncio
async def test_start_success(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test successful start() with connection and authentication"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member

    with patch.object(plugin, '_test_connection', return_value=True) as mock_test, \
         patch.object(plugin, '_authenticate', return_value=True) as mock_auth:

        result = await plugin.start()

        assert result is True
        assert plugin.host == '192.168.1.100'
        assert plugin.port == '52199'
        assert plugin.username == 'testuser'
        assert plugin.password == 'testpass'
        assert plugin.access_key == 'testkey'
        assert plugin.base_url == 'http://192.168.1.100:52199/MCWS/v1'
        assert plugin.session is not None  # Session should remain open on success
        mock_test.assert_called_once()
        mock_auth.assert_called_once()

        # Clean up session manually since this is a test
        await plugin.session.close()


@pytest.mark.asyncio
async def test_start_connection_failure(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test start() with connection failure"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member

    with patch.object(plugin, '_test_connection', return_value=False):
        result = await plugin.start()
        assert result is False


@pytest.mark.asyncio
async def test_start_auth_failure(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test start() with authentication failure"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member

    with patch.object(plugin, '_test_connection', return_value=True), \
         patch.object(plugin, '_authenticate', return_value=False):

        result = await plugin.start()
        assert result is False
        assert plugin.session is None  # Session should be closed and set to None


@pytest.mark.asyncio
async def test_start_session_cleanup_on_connection_failure(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test that session is properly closed when connection fails"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member

    with patch.object(plugin, '_test_connection', return_value=False):
        result = await plugin.start()
        assert result is False
        assert plugin.session is None  # Session should be closed and set to None


@pytest.mark.asyncio
async def test_start_session_cleanup_on_auth_failure(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test that session is properly closed when authentication fails"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member

    with patch.object(plugin, '_test_connection', return_value=True), \
         patch.object(plugin, '_authenticate', return_value=False):

        result = await plugin.start()
        assert result is False
        assert plugin.session is None  # Session should be closed and set to None


@pytest.mark.asyncio
async def test_test_connection_success():
    """Test successful connection test"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.access_key = 'testkey'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Alive',
              body='''<Response Status="OK">
                        <Item Name="AccessKey">testkey</Item>
                      </Response>''')

        result = await plugin._test_connection()  # pylint: disable=protected-access
        assert result is True

    await plugin.session.close()


@pytest.mark.asyncio
async def test_test_connection_wrong_access_key():
    """Test connection test with wrong access key"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.access_key = 'wrongkey'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Alive',
              body='''<Response Status="OK">
                        <Item Name="AccessKey">correctkey</Item>
                      </Response>''')

        result = await plugin._test_connection()  # pylint: disable=protected-access
        assert result is False

    await plugin.session.close()


@pytest.mark.asyncio
async def test_test_connection_http_error():
    """Test connection test with HTTP error"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Alive', status=404)

        result = await plugin._test_connection()  # pylint: disable=protected-access
        assert result is False

    await plugin.session.close()


@pytest.mark.asyncio
async def test_test_connection_network_error():
    """Test connection test with network error"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Alive',
                      exception=Exception('Connection failed'))

        result = await plugin._test_connection()  # pylint: disable=protected-access
        assert result is False

    await plugin.session.close()


@pytest.mark.asyncio
async def test_authenticate_success():
    """Test successful authentication"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.username = 'testuser'
    plugin.password = 'testpass'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        url = 'http://localhost:52199/MCWS/v1/Authenticate?Username=testuser&Password=testpass'
        mock_resp.get(url,
              body='''
              <Response Status="OK">
                  <Item Name="Token">abc123token</Item>
              </Response>
              ''')

        result = await plugin._authenticate()  # pylint: disable=protected-access
        assert result is True
        assert plugin.token == 'abc123token'

    await plugin.session.close()


@pytest.mark.asyncio
async def test_authenticate_no_credentials():
    """Test authentication with no credentials"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.username = None
    plugin.password = None

    result = await plugin._authenticate()  # pylint: disable=protected-access
    assert result is True  # Should succeed when no auth is needed


@pytest.mark.asyncio
async def test_authenticate_no_token():
    """Test authentication with no token in response"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.username = 'testuser'
    plugin.password = 'testpass'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        url = 'http://localhost:52199/MCWS/v1/Authenticate?Username=testuser&Password=testpass'
        mock_resp.get(url,
              body='''
              <Response Status="OK">
              </Response>
              ''')

        result = await plugin._authenticate()  # pylint: disable=protected-access
        assert result is False

    await plugin.session.close()


@pytest.mark.asyncio
async def test_authenticate_http_error():
    """Test authentication with HTTP error"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.username = 'testuser'
    plugin.password = 'testpass'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        url = 'http://localhost:52199/MCWS/v1/Authenticate?Username=testuser&Password=testpass'
        mock_resp.get(url, status=401)

        result = await plugin._authenticate()  # pylint: disable=protected-access
        assert result is False

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_no_base_url():
    """Test getplayingtrack with no base URL"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = None

    result = await plugin.getplayingtrack()
    assert result is None


@pytest.mark.asyncio
async def test_getplayingtrack_success(jriver_plugin_with_session):  # pylint: disable=redefined-outer-name
    """Test successful getplayingtrack"""
    plugin = jriver_plugin_with_session
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.token = 'testtoken'

    with aioresponses() as mock_resp:
        # aioresponses matches the URL pattern, including query parameters
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info?Token=testtoken',
              body='''<Response Status="OK">
                        <Item Name="State">Playing</Item>
                        <Item Name="Artist">The Beatles</Item>
                        <Item Name="Album">Abbey Road</Item>
                        <Item Name="Name">Come Together</Item>
                        <Item Name="DurationMS">240000</Item>
                      </Response>''')

        result = await plugin.getplayingtrack()

        assert result['artist'] == 'The Beatles'
        assert result['album'] == 'Abbey Road'
        assert result['title'] == 'Come Together'
        assert result['duration'] == 240  # 240000ms / 1000


@pytest.mark.asyncio
async def test_getplayingtrack_minimal_data():
    """Test getplayingtrack with minimal data"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info',
              body='''
              <Response Status="OK">
                  <Item Name="Name">Unknown Track</Item>
              </Response>
              ''')

        result = await plugin.getplayingtrack()

        assert result['title'] == 'Unknown Track'
        assert result.get('artist') is None
        assert result.get('album') is None
        assert result.get('duration') is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_http_error():
    """Test getplayingtrack with HTTP error"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info', status=500)

        result = await plugin.getplayingtrack()
        assert result is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_network_error():
    """Test getplayingtrack with network error"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info',
                      exception=Exception('Network error'))

        result = await plugin.getplayingtrack()
        assert result is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_parse_error():
    """Test getplayingtrack with XML parse error"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info', body='invalid xml content')

        result = await plugin.getplayingtrack()
        assert result is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_with_token():
    """Test getplayingtrack includes token in request"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.token = 'mytoken123'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        # aioresponses matches the exact URL including query parameters
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info?Token=mytoken123',
              body='<Response Status="OK"></Response>')

        await plugin.getplayingtrack()

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_without_token():
    """Test getplayingtrack without token"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.token = None

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        # aioresponses matches the exact URL without query parameters
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info',
              body='<Response Status="OK"></Response>')

        await plugin.getplayingtrack()

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_with_access_key():
    """Test getplayingtrack includes access_key in request"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.access_key = 'myaccesskey123'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        # aioresponses matches the exact URL including query parameters
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info?AccessKey=myaccesskey123',
              body='<Response Status="OK"></Response>')

        await plugin.getplayingtrack()

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_with_token_and_access_key():
    """Test getplayingtrack includes both token and access_key in request"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.token = 'mytoken123'
    plugin.access_key = 'myaccesskey123'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        # aioresponses matches the exact URL including query parameters
        # Note: order of parameters in URL may vary, so we test the call was made correctly
        url = ('http://localhost:52199/MCWS/v1/Playback/Info?Token=mytoken123&'
               'AccessKey=myaccesskey123')
        mock_resp.get(url, body='<Response Status="OK"></Response>')

        await plugin.getplayingtrack()

    await plugin.session.close()


@pytest.mark.asyncio
async def test_get_filename_with_access_key():
    """Test _get_filename includes access_key in request"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.access_key = 'myaccesskey123'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        url = 'http://localhost:52199/MCWS/v1/File/GetInfo?FileKey=12345&AccessKey=myaccesskey123'
        mock_resp.get(url,
              body='''<Response Status="OK">
                        <Item Name="Filename">test.mp3</Item>
                      </Response>''')

        result = await plugin._get_filename('12345')  # pylint: disable=protected-access
        assert result == 'test.mp3'

    await plugin.session.close()


@pytest.mark.asyncio
async def test_get_filename_with_token_and_access_key():
    """Test _get_filename includes both token and access_key in request"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.token = 'mytoken123'
    plugin.access_key = 'myaccesskey123'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        url = ('http://localhost:52199/MCWS/v1/File/GetInfo?FileKey=12345&'
               'Token=mytoken123&AccessKey=myaccesskey123')
        mock_resp.get(url,
              body='''<Response Status="OK">
                        <Item Name="Filename">test.mp3</Item>
                      </Response>''')

        result = await plugin._get_filename('12345')  # pylint: disable=protected-access
        assert result == 'test.mp3'

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getrandomtrack():
    """Test getrandomtrack returns None"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    result = await plugin.getrandomtrack('test')
    assert result is None


def test_connect_settingsui():
    """Test connect_settingsui method"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    mock_qwidget = MagicMock()
    mock_uihelp = MagicMock()

    plugin.connect_settingsui(mock_qwidget, mock_uihelp)

    assert plugin.qwidget == mock_qwidget
    assert plugin.uihelp == mock_uihelp


def test_is_local_connection_localhost():
    """Test local connection detection for localhost"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    plugin.host = 'localhost'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    plugin.host = '127.0.0.1'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    plugin.host = '::1'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    # Test that IPv6 localhost works with URL formatting
    formatted_host = plugin._format_host_for_url('::1')  # pylint: disable=protected-access
    assert formatted_host == '[::1]'


def test_is_local_connection_private_networks():
    """Test local connection detection for private networks"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # Private IPv4 ranges
    plugin.host = '192.168.1.100'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    plugin.host = '10.0.0.5'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    plugin.host = '172.16.1.10'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    # Private IPv6 ranges (link-local and unique local)
    plugin.host = 'fe80::1'  # Link-local
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    plugin.host = 'fd00::1'  # Unique local
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access


def test_is_local_connection_public_ip():
    """Test local connection detection for public IPs"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # Public IPv4 addresses
    plugin.host = '8.8.8.8'
    assert plugin._is_local_connection() is False  # pylint: disable=protected-access

    plugin.host = '1.1.1.1'
    assert plugin._is_local_connection() is False  # pylint: disable=protected-access

    # Public IPv6 addresses
    plugin.host = '2001:4860:4860::8888'  # Google DNS
    assert plugin._is_local_connection() is False  # pylint: disable=protected-access

    plugin.host = '2606:4700:4700::1111'  # Cloudflare DNS
    assert plugin._is_local_connection() is False  # pylint: disable=protected-access


def test_is_local_connection_hostname():
    """Test local connection detection for hostnames"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # Generic hostnames should NOT be considered local (security risk)
    plugin.host = 'jriver-server'
    assert plugin._is_local_connection() is False  # pylint: disable=protected-access

    plugin.host = 'remote.example.com'
    assert plugin._is_local_connection() is False  # pylint: disable=protected-access

    # Only explicit local domain patterns should be considered local
    plugin.host = 'media-pc.local'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    plugin.host = 'jriver.lan'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    plugin.host = 'server.home'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access

    plugin.host = 'media.internal'
    assert plugin._is_local_connection() is True  # pylint: disable=protected-access


def test_is_local_connection_no_host():
    """Test local connection detection with no host"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    plugin.host = None
    assert plugin._is_local_connection() is False  # pylint: disable=protected-access


def test_is_local_connection_security():
    """Test that remote hostnames are properly rejected for security"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # These should all be considered remote/unsafe
    remote_hosts = [
        'jriver.example.com',
        'music-server.net',
        'remote-jriver.org',
        'malicious-server.co.uk',
        'untrusted-host',
        'random-hostname',
    ]

    for host in remote_hosts:
        plugin.host = host
        assert plugin._is_local_connection() is False, f"Host '{host}' should be considered remote"  # pylint: disable=protected-access


def test_format_host_for_url_ipv4():
    """Test IPv4 address formatting (should remain unchanged)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # IPv4 addresses should not be wrapped
    assert plugin._format_host_for_url('192.168.1.100') == '192.168.1.100'  # pylint: disable=protected-access
    assert plugin._format_host_for_url('127.0.0.1') == '127.0.0.1'  # pylint: disable=protected-access
    assert plugin._format_host_for_url('10.0.0.1') == '10.0.0.1'  # pylint: disable=protected-access


def test_format_host_for_url_ipv6():
    """Test IPv6 address formatting (should be wrapped in brackets)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # IPv6 addresses should be wrapped in brackets
    assert plugin._format_host_for_url('2001:db8::1') == '[2001:db8::1]'  # pylint: disable=protected-access
    assert plugin._format_host_for_url('::1') == '[::1]'  # pylint: disable=protected-access
    assert plugin._format_host_for_url('fe80::1%lo0') == '[fe80::1%lo0]'  # pylint: disable=protected-access
    assert plugin._format_host_for_url(  # pylint: disable=protected-access
        '2001:0db8:85a3:0000:0000:8a2e:0370:7334') == '[2001:0db8:85a3:0000:0000:8a2e:0370:7334]'


def test_format_host_for_url_already_bracketed():
    """Test that already bracketed IPv6 addresses are not double-wrapped"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # Already bracketed IPv6 should remain unchanged
    assert plugin._format_host_for_url('[2001:db8::1]') == '[2001:db8::1]'  # pylint: disable=protected-access
    assert plugin._format_host_for_url('[::1]') == '[::1]'  # pylint: disable=protected-access


def test_format_host_for_url_hostname():
    """Test hostname formatting (should remain unchanged)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # Hostnames should not be wrapped
    assert plugin._format_host_for_url('localhost') == 'localhost'  # pylint: disable=protected-access
    assert plugin._format_host_for_url('jriver.local') == 'jriver.local'  # pylint: disable=protected-access
    assert plugin._format_host_for_url('media-server.lan') == 'media-server.lan'  # pylint: disable=protected-access


def test_format_host_for_url_edge_cases():
    """Test edge cases for host formatting"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # Edge cases
    assert plugin._format_host_for_url(None) is None  # pylint: disable=protected-access
    assert plugin._format_host_for_url('') == ''  # pylint: disable=protected-access
    assert plugin._format_host_for_url('invalid-ip') == 'invalid-ip'  # pylint: disable=protected-access


def test_ipv6_url_construction():
    """Test that IPv6 addresses result in proper URLs"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member

    # Mock config to avoid actual initialization
    mock_config = MagicMock()
    mock_config.cparser.value.side_effect = lambda key, default=None: {
        'jriver/host': '2001:db8::1',
        'jriver/port': '52199'
    }.get(key, default)
    plugin.config = mock_config

    # Test IPv6 URL construction
    plugin.host = '2001:db8::1'
    plugin.port = '52199'
    formatted_host = plugin._format_host_for_url(plugin.host)  # pylint: disable=protected-access
    expected_url = f"http://{formatted_host}:{plugin.port}/MCWS/v1"

    assert formatted_host == '[2001:db8::1]'
    assert expected_url == 'http://[2001:db8::1]:52199/MCWS/v1'


@pytest.mark.asyncio
async def test_get_filename_success(jriver_plugin_with_session):  # pylint: disable=redefined-outer-name
    """Test successful filename retrieval"""
    plugin = jriver_plugin_with_session
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.token = 'testtoken'

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?FileKey=12345&Token=testtoken',
              body='''<Response Status="OK">
                        <Item Name="FileKey">12345</Item>
                        <Item Name="Name">Come Together</Item>
                        <Item Name="Artist">The Beatles</Item>
                        <Item Name="Filename">C:\\Music\\The Beatles\\Abbey Road\\Come Together.mp3</Item>
                      </Response>''')

        result = await plugin._get_filename('12345')  # pylint: disable=protected-access
        assert result == 'C:\\Music\\The Beatles\\Abbey Road\\Come Together.mp3'


@pytest.mark.asyncio
async def test_get_filename_not_found():
    """Test filename retrieval when no filename in response"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?FileKey=12345',
              body='''
              <Response Status="OK">
                  <Item Name="FileKey">12345</Item>
                  <Item Name="Name">Come Together</Item>
              </Response>
              ''')

        result = await plugin._get_filename('12345')  # pylint: disable=protected-access
        assert result is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_get_filename_http_error():
    """Test filename retrieval with HTTP error"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?FileKey=12345', status=404)

        result = await plugin._get_filename('12345')  # pylint: disable=protected-access
        assert result is None

    await plugin.session.close()
