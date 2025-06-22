#!/usr/bin/env python3
''' test jriver input plugin '''

#pylint: disable=too-many-lines

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
    assert plugin.displayname == "JRiver"
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
    mock_qwidget.password_lineedit.text.return_value = ''  # empty string
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
        assert plugin.password == 'testpass'  # pragma: allowlist secret
        assert plugin.access_key == 'testkey'
        assert plugin.base_url == 'http://192.168.1.100:52199/MCWS/v1'
        assert plugin.session is not None  # Session should remain open on success
        assert plugin._connection_failed is False  # Should be False on success  # pylint: disable=protected-access
        mock_test.assert_called_once()
        mock_auth.assert_called_once()

        # Clean up session manually since this is a test
        await plugin.session.close()


@pytest.mark.asyncio
async def test_start_connection_failure(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test start() with connection failure - now returns True for auto-recovery"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member

    with patch.object(plugin, '_test_connection', return_value=False):
        result = await plugin.start()
        assert result is True  # Should return True to enable auto-recovery
        assert plugin._connection_failed is True  # pylint: disable=protected-access

        # Clean up session manually since this is a test
        await plugin.session.close()  # Should mark connection as failed
        assert plugin.session is not None  # Session should remain open for recovery

        # Clean up session manually since this is a test
        await plugin.session.close()


@pytest.mark.asyncio
async def test_start_auth_failure(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test start() with authentication failure - now returns True for auto-recovery"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member

    with patch.object(plugin, '_test_connection', return_value=True), \
         patch.object(plugin, '_authenticate', return_value=False):

        result = await plugin.start()
        assert result is True  # Should return True to enable auto-recovery
        assert plugin._connection_failed is True  # pylint: disable=protected-access

        # Clean up session manually since this is a test
        await plugin.session.close()  # Should mark connection as failed
        assert plugin.session is not None  # Session should remain open for recovery

        # Clean up session manually since this is a test
        await plugin.session.close()


@pytest.mark.asyncio
async def test_start_session_kept_open_on_connection_failure(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test that session is kept open when connection fails for auto-recovery"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member

    with patch.object(plugin, '_test_connection', return_value=False):
        result = await plugin.start()
        assert result is True  # Should return True to enable auto-recovery
        assert plugin.session is not None  # Session should remain open for recovery
        assert plugin._connection_failed is True  # pylint: disable=protected-access

        # Clean up session manually since this is a test
        await plugin.session.close()


@pytest.mark.asyncio
async def test_start_session_kept_open_on_auth_failure(jriver_bootstrap):  # pylint: disable=redefined-outer-name
    """Test that session is kept open when authentication fails for auto-recovery"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap)  # pylint: disable=no-member

    with patch.object(plugin, '_test_connection', return_value=True), \
         patch.object(plugin, '_authenticate', return_value=False):

        result = await plugin.start()
        assert result is True  # Should return True to enable auto-recovery
        assert plugin.session is not None  # Session should remain open for recovery
        assert plugin._connection_failed is True  # pylint: disable=protected-access

        # Clean up session manually since this is a test
        await plugin.session.close()


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
    plugin.password = 'testpass'  # pragma: allowlist secret

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
    plugin.password = 'testpass'  # pragma: allowlist secret

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
    plugin.password = 'testpass'  # pragma: allowlist secret

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
        assert result == {}  # Parse errors return empty dict, not None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_with_xml_declaration():
    """Test getplayingtrack with XML encoding declaration (real JRiver format)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        # This simulates the actual JRiver response format with XML declaration
        jriver_response = '''<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<Response Status="OK">
<Item Name="ZoneID">0</Item>
<Item Name="State">2</Item>
<Item Name="FileKey">477</Item>
<Item Name="DurationMS">341342</Item>
<Item Name="Artist">Information Society</Item>
<Item Name="Album">Don't Be Afraid</Item>
<Item Name="Name">Are 'Friends' Electric? 2.0</Item>
<Item Name="Status">Playing</Item>
</Response>'''

        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info', body=jriver_response)

        result = await plugin.getplayingtrack()
        assert result is not None
        assert result['artist'] == 'Information Society'
        assert result['album'] == "Don't Be Afraid"
        assert result['title'] == "Are 'Friends' Electric? 2.0"
        assert result['duration'] == 341  # 341342ms / 1000

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
        url = 'http://localhost:52199/MCWS/v1/File/GetInfo?File=12345&AccessKey=myaccesskey123'
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
        url = ('http://localhost:52199/MCWS/v1/File/GetInfo?File=12345&'
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


@pytest.mark.parametrize(
    "host,expected",
    [
        # Localhost variants
        ('localhost', True),
        ('127.0.0.1', True),
        ('::1', True),
        # Private IPv4 ranges
        ('192.168.1.100', True),
        ('10.0.0.5', True),
        ('172.16.1.10', True),
        # Private IPv6 ranges
        ('fe80::1', True),  # Link-local
        ('fd00::1', True),  # Unique local
        # Public IPv4 addresses
        ('8.8.8.8', False),
        ('1.1.1.1', False),
        # Public IPv6 addresses
        ('2001:4860:4860::8888', False),  # Google DNS
        ('2606:4700:4700::1111', False),  # Cloudflare DNS
        # Generic hostnames (should NOT be considered local - security risk)
        ('jriver-server', False),
        ('remote.example.com', False),
        # Explicit local domain patterns
        ('media-pc.local', True),
        ('jriver.lan', True),
        ('server.home', True),
        ('media.internal', True),
        # Remote hostnames (security test)
        ('jriver.example.com', False),
        ('music-server.net', False),
        ('remote-jriver.org', False),
        ('malicious-server.co.uk', False),
        ('untrusted-host', False),
        ('random-hostname', False),
        # Edge case
        (None, False),
    ])
def test_is_local_connection(host, expected):
    """Test local connection detection for various hosts"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.host = host
    assert plugin._is_local_connection() is expected  # pylint: disable=protected-access


def test_is_local_connection_ipv6_url_formatting():
    """Test that IPv6 localhost works with URL formatting"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    formatted_host = plugin._format_host_for_url('::1')  # pylint: disable=protected-access
    assert formatted_host == '[::1]'


@pytest.mark.parametrize(
    "input_host,expected",
    [
        # IPv4 addresses (should remain unchanged)
        ('192.168.1.100', '192.168.1.100'),
        ('127.0.0.1', '127.0.0.1'),
        ('10.0.0.1', '10.0.0.1'),
        # IPv6 addresses (should be wrapped in brackets)
        ('2001:db8::1', '[2001:db8::1]'),
        ('::1', '[::1]'),
        ('fe80::1%lo0', '[fe80::1%lo0]'),
        ('2001:0db8:85a3:0000:0000:8a2e:0370:7334', '[2001:0db8:85a3:0000:0000:8a2e:0370:7334]'),
        # Already bracketed IPv6 (should remain unchanged)
        ('[2001:db8::1]', '[2001:db8::1]'),
        ('[::1]', '[::1]'),
        # Hostnames (should remain unchanged)
        ('localhost', 'localhost'),
        ('jriver.local', 'jriver.local'),
        ('media-server.lan', 'media-server.lan'),
        # Edge cases
        (None, None),
        ('', ''),
        ('invalid-ip', 'invalid-ip'),
    ])
def test_format_host_for_url(input_host, expected):
    """Test host formatting for URL construction"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    assert plugin._format_host_for_url(input_host) == expected  # pylint: disable=protected-access


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
        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?File=12345&Token=testtoken',
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
        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?File=12345',
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
        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?File=12345', status=404)

        result = await plugin._get_filename('12345')  # pylint: disable=protected-access
        assert result is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_get_filename_mpl_format():
    """Test _get_filename with MPL format response (real JRiver format)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        # This simulates the actual JRiver MPL response format
        mpl_response = '''<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<MPL Version="2.0" Title="MCWS - Files - 6096105472" PathSeparator="/">
<Item>
<Field Name="Key">477</Field>
<Field Name="Filename">/Users/aw/Music/Artist/Album/Song.mp3</Field>
<Field Name="Name">Song Title</Field>
<Field Name="Artist">Artist Name</Field>
<Field Name="Album">Album Name</Field>
</Item>
</MPL>'''

        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?File=477', body=mpl_response)

        result = await plugin._get_filename('477')  # pylint: disable=protected-access
        assert result == '/Users/aw/Music/Artist/Album/Song.mp3'

    await plugin.session.close()


@pytest.mark.asyncio
async def test_get_filename_response_format():
    """Test _get_filename with Response format (compatibility)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        # Test the old Response format for backwards compatibility
        response_format = '''<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<Response Status="OK">
<Item Name="FileKey">477</Item>
<Item Name="Filename">/Users/aw/Music/Artist/Album/Song.mp3</Item>
<Item Name="Name">Song Title</Item>
</Response>'''

        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?File=477', body=response_format)

        result = await plugin._get_filename('477')  # pylint: disable=protected-access
        assert result == '/Users/aw/Music/Artist/Album/Song.mp3'

    await plugin.session.close()


# Error condition tests for improved error handling
@pytest.mark.asyncio
async def test_test_connection_jriver_not_running():
    """Test connection test when JRiver is not running (ClientConnectorError)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Alive',
                      exception=aiohttp.ClientConnectorError(
                          connection_key=None, os_error=OSError("Connection refused")))

        result = await plugin._test_connection()  # pylint: disable=protected-access
        assert result is False

    await plugin.session.close()


@pytest.mark.asyncio
async def test_test_connection_timeout():
    """Test connection test with timeout"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Alive',
                      exception=aiohttp.ClientTimeout())

        result = await plugin._test_connection()  # pylint: disable=protected-access
        assert result is False

    await plugin.session.close()


@pytest.mark.asyncio
async def test_authenticate_jriver_not_running():
    """Test authentication when JRiver is not running (ClientConnectorError)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.username = 'testuser'
    plugin.password = 'testpass'  # pragma: allowlist secret

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        url = 'http://localhost:52199/MCWS/v1/Authenticate?Username=testuser&Password=testpass'
        mock_resp.get(url, exception=aiohttp.ClientConnectorError(
            connection_key=None, os_error=OSError("Connection refused")))

        result = await plugin._authenticate()  # pylint: disable=protected-access
        assert result is False

    await plugin.session.close()


@pytest.mark.asyncio
async def test_authenticate_timeout():
    """Test authentication with timeout"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.username = 'testuser'
    plugin.password = 'testpass'  # pragma: allowlist secret

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        url = 'http://localhost:52199/MCWS/v1/Authenticate?Username=testuser&Password=testpass'
        mock_resp.get(url, exception=aiohttp.ClientTimeout())

        result = await plugin._authenticate()  # pylint: disable=protected-access
        assert result is False

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_jriver_not_running():
    """Test getplayingtrack when JRiver is not running (ClientConnectorError)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info',
                      exception=aiohttp.ClientConnectorError(
                          connection_key=None, os_error=OSError("Connection refused")))

        result = await plugin.getplayingtrack()
        assert result is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_timeout():
    """Test getplayingtrack with timeout"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info',
                      exception=aiohttp.ClientTimeout())

        result = await plugin.getplayingtrack()
        assert result is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_getplayingtrack_xml_none_safety():
    """Test getplayingtrack with XML parsing error (safety check)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        # Return completely empty response that will cause XML parsing error
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info', body='')

        result = await plugin.getplayingtrack()
        # Should return empty dict when XML parsing fails, not crash
        assert result == {}

    await plugin.session.close()


@pytest.mark.asyncio
async def test_get_filename_jriver_not_running():
    """Test _get_filename when JRiver is not running (ClientConnectorError)"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?File=12345',
                      exception=aiohttp.ClientConnectorError(
                          connection_key=None, os_error=OSError("Connection refused")))

        result = await plugin._get_filename('12345')  # pylint: disable=protected-access
        assert result is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_get_filename_timeout():
    """Test _get_filename with timeout"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'

    # Create real aiohttp session for testing
    plugin.session = aiohttp.ClientSession()

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/File/GetInfo?File=12345',
                      exception=aiohttp.ClientTimeout())

        result = await plugin._get_filename('12345')  # pylint: disable=protected-access
        assert result is None

    await plugin.session.close()


@pytest.mark.asyncio
async def test_auto_recovery_success():
    """Test successful auto-recovery when JRiver comes back online"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.session = aiohttp.ClientSession()
    plugin._connection_failed = True  # pylint: disable=protected-access

    with patch.object(plugin, '_test_connection', return_value=True), \
         patch.object(plugin, '_authenticate', return_value=True):

        with aioresponses() as mock_resp:
            mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info',
                          body='<Response><Item Name="Artist">Test Artist</Item>'
                               '<Item Name="Name">Test Title</Item></Response>')

            result = await plugin.getplayingtrack()

            assert result is not None
            assert result['artist'] == 'Test Artist'
            assert result['title'] == 'Test Title'
            assert plugin._connection_failed is False  # pylint: disable=protected-access  # pylint: disable=protected-access

    await plugin.session.close()


@pytest.mark.asyncio
async def test_auto_recovery_connection_fails():
    """Test auto-recovery when connection still fails"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.session = aiohttp.ClientSession()
    plugin._connection_failed = True  # pylint: disable=protected-access

    with patch.object(plugin, '_test_connection', return_value=False):
        result = await plugin.getplayingtrack()

        assert result is None
        assert plugin._connection_failed is True  # pylint: disable=protected-access

    await plugin.session.close()


@pytest.mark.asyncio
async def test_connection_error_sets_failed_state():
    """Test that connection errors set the failed state"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.session = aiohttp.ClientSession()
    plugin._connection_failed = False  # pylint: disable=protected-access

    with aioresponses() as mock_resp:
        mock_resp.get('http://localhost:52199/MCWS/v1/Playback/Info',
                      exception=aiohttp.ClientConnectorError(
                          connection_key=None, os_error=OSError("Connection refused")))

        result = await plugin.getplayingtrack()

        assert result is None
        assert plugin._connection_failed is True  # pylint: disable=protected-access

    await plugin.session.close()


@pytest.mark.asyncio
async def test_stop_resets_connection_state():
    """Test that stop() resets connection failed state"""
    plugin = nowplaying.inputs.jriver.Plugin()  # pylint: disable=no-member
    plugin.session = aiohttp.ClientSession()
    plugin._connection_failed = True  # pylint: disable=protected-access

    await plugin.stop()

    assert plugin._connection_failed is False  # pylint: disable=protected-access
    assert plugin.session is None
