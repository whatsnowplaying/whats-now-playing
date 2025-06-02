#!/usr/bin/env python3
''' test jriver input plugin '''

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

import nowplaying.inputs.jriver # pylint: disable=import-error


def create_mock_response(status=200, text=''):
    """Helper to create mock aiohttp response"""
    mock_response = AsyncMock()
    mock_response.status = status
    mock_response.text = AsyncMock(return_value=text)
    return mock_response


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
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    assert plugin.displayname == "JRiver Media Center"
    assert plugin.host is None
    assert plugin.port is None
    assert plugin.token is None
    assert plugin.base_url is None


def test_plugin_defaults():
    """Test default configuration values"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    mock_qsettings = MagicMock()
    plugin.defaults(mock_qsettings)
    
    mock_qsettings.setValue.assert_any_call('jriver/host', None)
    mock_qsettings.setValue.assert_any_call('jriver/port', '52199')
    mock_qsettings.setValue.assert_any_call('jriver/username', None)
    mock_qsettings.setValue.assert_any_call('jriver/password', None)
    mock_qsettings.setValue.assert_any_call('jriver/access_key', None)


def test_plugin_mixmodes():
    """Test mix mode functionality"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    assert plugin.validmixmodes() == ['newest']
    assert plugin.setmixmode('any') == 'newest'
    assert plugin.getmixmode() == 'newest'


def test_settings_ui_load(jriver_bootstrap):
    """Test loading settings into UI"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap) # pylint: disable=no-member
    mock_qwidget = MagicMock()
    
    plugin.load_settingsui(mock_qwidget)
    
    mock_qwidget.host_lineedit.setText.assert_called_once_with('192.168.1.100')
    mock_qwidget.port_lineedit.setText.assert_called_once_with('52199')
    mock_qwidget.username_lineedit.setText.assert_called_once_with('testuser')
    mock_qwidget.password_lineedit.setText.assert_called_once_with('testpass')
    mock_qwidget.access_key_lineedit.setText.assert_called_once_with('testkey')


def test_settings_ui_save(jriver_bootstrap):
    """Test saving settings from UI"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap) # pylint: disable=no-member
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


def test_settings_ui_description():
    """Test settings UI description"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    mock_qwidget = MagicMock()
    
    plugin.desc_settingsui(mock_qwidget)
    
    expected_text = ('This plugin provides support for JRiver Media Center via MCWS API. '
                    'Configure the host/IP and port of your JRiver server. '
                    'Username/password are optional if authentication is not required.')
    mock_qwidget.setText.assert_called_once_with(expected_text)


@pytest.mark.asyncio
async def test_start_no_host():
    """Test start() with no host configured"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    mock_config = MagicMock()
    mock_config.cparser.value.return_value = None
    plugin.config = mock_config
    
    result = await plugin.start()
    assert result is False


@pytest.mark.asyncio
async def test_start_success(jriver_bootstrap):
    """Test successful start() with connection and authentication"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap) # pylint: disable=no-member
    
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
        mock_test.assert_called_once()
        mock_auth.assert_called_once()


@pytest.mark.asyncio
async def test_start_connection_failure(jriver_bootstrap):
    """Test start() with connection failure"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap) # pylint: disable=no-member
    
    with patch.object(plugin, '_test_connection', return_value=False):
        result = await plugin.start()
        assert result is False


@pytest.mark.asyncio
async def test_start_auth_failure(jriver_bootstrap):
    """Test start() with authentication failure"""
    plugin = nowplaying.inputs.jriver.Plugin(config=jriver_bootstrap) # pylint: disable=no-member
    
    with patch.object(plugin, '_test_connection', return_value=True), \
         patch.object(plugin, '_authenticate', return_value=False):
        
        result = await plugin.start()
        assert result is False


@pytest.mark.asyncio
async def test_test_connection_success():
    """Test successful connection test"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.access_key = 'testkey'
    
    # Mock aiohttp session
    mock_session = AsyncMock()
    plugin.session = mock_session
    
    mock_response = create_mock_response(
        status=200,
        text='''
        <Response Status="OK">
            <Item Name="AccessKey">testkey</Item>
        </Response>
        '''
    )
    
    # Set up the async context manager properly
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_response
    mock_context_manager.__aexit__.return_value = None
    mock_session.get.return_value = mock_context_manager
    
    result = await plugin._test_connection()
    assert result is True


@pytest.mark.asyncio
async def test_test_connection_wrong_access_key():
    """Test connection test with wrong access key"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.access_key = 'wrongkey'
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '''
    <Response Status="OK">
        <Item Name="AccessKey">correctkey</Item>
    </Response>
    '''
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response):
        result = await plugin._test_connection()
        assert result is False


@pytest.mark.asyncio
async def test_test_connection_http_error():
    """Test connection test with HTTP error"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    
    mock_response = MagicMock()
    mock_response.status_code = 404
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response):
        result = await plugin._test_connection()
        assert result is False


@pytest.mark.asyncio
async def test_test_connection_network_error():
    """Test connection test with network error"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    
    with patch('nowplaying.inputs.jriver.requests.get', side_effect=Exception('Connection failed')):
        result = await plugin._test_connection()
        assert result is False


@pytest.mark.asyncio
async def test_authenticate_success():
    """Test successful authentication"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.username = 'testuser'
    plugin.password = 'testpass'
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '''
    <Response Status="OK">
        <Item Name="Token">abc123token</Item>
    </Response>
    '''
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response):
        result = await plugin._authenticate()
        assert result is True
        assert plugin.token == 'abc123token'


@pytest.mark.asyncio
async def test_authenticate_no_credentials():
    """Test authentication with no credentials"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.username = None
    plugin.password = None
    
    result = await plugin._authenticate()
    assert result is True  # Should succeed when no auth is needed


@pytest.mark.asyncio
async def test_authenticate_no_token():
    """Test authentication with no token in response"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.username = 'testuser'
    plugin.password = 'testpass'
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '''
    <Response Status="OK">
    </Response>
    '''
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response):
        result = await plugin._authenticate()
        assert result is False


@pytest.mark.asyncio
async def test_authenticate_http_error():
    """Test authentication with HTTP error"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.username = 'testuser'
    plugin.password = 'testpass'
    
    mock_response = MagicMock()
    mock_response.status_code = 401
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response):
        result = await plugin._authenticate()
        assert result is False


@pytest.mark.asyncio
async def test_getplayingtrack_no_base_url():
    """Test getplayingtrack with no base URL"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = None
    
    result = await plugin.getplayingtrack()
    assert result is None


@pytest.mark.asyncio
async def test_getplayingtrack_success():
    """Test successful getplayingtrack"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.token = 'testtoken'
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '''
    <Response Status="OK">
        <Item Name="State">Playing</Item>
        <Item Name="Artist">The Beatles</Item>
        <Item Name="Album">Abbey Road</Item>
        <Item Name="Name">Come Together</Item>
        <Item Name="DurationMS">240000</Item>
    </Response>
    '''
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response):
        result = await plugin.getplayingtrack()
        
        assert result['artist'] == 'The Beatles'
        assert result['album'] == 'Abbey Road'
        assert result['title'] == 'Come Together'
        assert result['duration'] == 240  # 240000ms / 1000


@pytest.mark.asyncio
async def test_getplayingtrack_minimal_data():
    """Test getplayingtrack with minimal data"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '''
    <Response Status="OK">
        <Item Name="Name">Unknown Track</Item>
    </Response>
    '''
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response):
        result = await plugin.getplayingtrack()
        
        assert result['title'] == 'Unknown Track'
        assert result.get('artist') is None
        assert result.get('album') is None
        assert result.get('duration') is None


@pytest.mark.asyncio
async def test_getplayingtrack_http_error():
    """Test getplayingtrack with HTTP error"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    
    mock_response = MagicMock()
    mock_response.status_code = 500
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response):
        result = await plugin.getplayingtrack()
        assert result is None


@pytest.mark.asyncio
async def test_getplayingtrack_network_error():
    """Test getplayingtrack with network error"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    
    with patch('nowplaying.inputs.jriver.requests.get', side_effect=Exception('Network error')):
        result = await plugin.getplayingtrack()
        assert result is None


@pytest.mark.asyncio
async def test_getplayingtrack_parse_error():
    """Test getplayingtrack with XML parse error"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = 'invalid xml content'
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response):
        result = await plugin.getplayingtrack()
        assert result is None


@pytest.mark.asyncio
async def test_getplayingtrack_with_token():
    """Test getplayingtrack includes token in request"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.token = 'mytoken123'
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '<Response Status="OK"></Response>'
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response) as mock_get:
        await plugin.getplayingtrack()
        
        # Verify token was included in the request
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[1]['params']['Token'] == 'mytoken123'


@pytest.mark.asyncio
async def test_getplayingtrack_without_token():
    """Test getplayingtrack without token"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    plugin.base_url = 'http://localhost:52199/MCWS/v1'
    plugin.token = None
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '<Response Status="OK"></Response>'
    
    with patch('nowplaying.inputs.jriver.requests.get', return_value=mock_response) as mock_get:
        await plugin.getplayingtrack()
        
        # Verify no token in params
        call_args = mock_get.call_args
        assert 'Token' not in call_args[1]['params']


@pytest.mark.asyncio
async def test_getrandomtrack():
    """Test getrandomtrack returns None"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    result = await plugin.getrandomtrack('test')
    assert result is None


def test_connect_settingsui():
    """Test connect_settingsui method"""
    plugin = nowplaying.inputs.jriver.Plugin() # pylint: disable=no-member
    mock_qwidget = MagicMock()
    mock_uihelp = MagicMock()
    
    plugin.connect_settingsui(mock_qwidget, mock_uihelp)
    
    assert plugin.qwidget == mock_qwidget
    assert plugin.uihelp == mock_uihelp