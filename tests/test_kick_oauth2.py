#!/usr/bin/env python3
"""Unit tests for Kick OAuth2 functionality."""

import asyncio
import base64
import hashlib
import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp

import nowplaying.kick.oauth2


class TestKickOAuth2:
    """Test cases for KickOAuth2 class."""

    def test_init_with_config(self, bootstrap):
        """Test OAuth2 initialization with config."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/secret', 'test_secret')
        config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        assert oauth.config == config
        assert oauth.client_id == 'test_client_id'
        assert oauth.client_secret == 'test_secret'
        assert oauth.redirect_uri == 'http://localhost:8080/callback'
        assert oauth.code_verifier is None
        assert oauth.code_challenge is None
        assert oauth.state is None

    def test_init_without_config(self):
        """Test OAuth2 initialization without config."""
        oauth = nowplaying.kick.oauth2.KickOAuth2()
        
        assert oauth.config is not None
        assert isinstance(oauth.config, nowplaying.config.ConfigFile)

    def test_generate_pkce_parameters(self, bootstrap):
        """Test PKCE parameter generation."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        oauth._generate_pkce_parameters()
        
        # Verify code verifier is generated
        assert oauth.code_verifier is not None
        assert len(oauth.code_verifier) >= 43
        assert len(oauth.code_verifier) <= 128
        
        # Verify code challenge is generated correctly
        assert oauth.code_challenge is not None
        expected_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(oauth.code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')
        assert oauth.code_challenge == expected_challenge
        
        # Verify state is generated
        assert oauth.state is not None
        assert len(oauth.state) >= 43

    def test_get_authorization_url_missing_client_id(self, bootstrap):
        """Test authorization URL generation fails without client ID."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        with pytest.raises(ValueError, match="Client ID is required"):
            oauth.get_authorization_url()

    def test_get_authorization_url_missing_redirect_uri(self, bootstrap):
        """Test authorization URL generation fails without redirect URI."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        with pytest.raises(ValueError, match="Redirect URI is required"):
            oauth.get_authorization_url()

    def test_get_authorization_url_success(self, bootstrap):
        """Test successful authorization URL generation."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        auth_url = oauth.get_authorization_url()
        
        assert auth_url.startswith('https://id.kick.com/oauth/authorize?')
        assert 'client_id=test_client_id' in auth_url
        assert 'response_type=code' in auth_url
        assert 'redirect_uri=http://localhost:8080/callback' in auth_url
        assert 'scope=user:read+user:write+chat:read+chat:write' in auth_url
        assert 'code_challenge_method=S256' in auth_url
        assert oauth.code_verifier is not None
        assert oauth.state is not None

    @patch('webbrowser.open')
    def test_open_browser_for_auth_success(self, mock_open, bootstrap):
        """Test successful browser opening for auth."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        result = oauth.open_browser_for_auth()
        
        assert result is True
        mock_open.assert_called_once()

    @patch('webbrowser.open', side_effect=Exception("Browser error"))
    def test_open_browser_for_auth_failure(self, mock_open, bootstrap):
        """Test browser opening failure."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        result = oauth.open_browser_for_auth()
        
        assert result is False
        mock_open.assert_called_once()

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_missing_verifier(self, bootstrap):
        """Test token exchange fails without code verifier."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        with pytest.raises(ValueError, match="Code verifier not generated"):
            await oauth.exchange_code_for_token('test_code')

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_state_mismatch(self, bootstrap):
        """Test token exchange fails with state mismatch."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        oauth.code_verifier = 'test_verifier'
        oauth.state = 'expected_state'
        
        with pytest.raises(ValueError, match="State parameter mismatch"):
            await oauth.exchange_code_for_token('test_code', 'wrong_state')

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_success(self, bootstrap):
        """Test successful token exchange."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        oauth.code_verifier = 'test_verifier'
        oauth.state = 'test_state'
        
        mock_response = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token'
        }
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_resp
            
            result = await oauth.exchange_code_for_token('test_code', 'test_state')
            
            assert result == mock_response
            assert oauth.access_token == 'test_access_token'
            assert oauth.refresh_token == 'test_refresh_token'
            assert config.cparser.value('kick/accesstoken') == 'test_access_token'
            assert config.cparser.value('kick/refreshtoken') == 'test_refresh_token'

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_error(self, bootstrap):
        """Test token exchange error handling."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        oauth.code_verifier = 'test_verifier'
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 400
            mock_resp.text = AsyncMock(return_value='Bad Request')
            
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_resp
            
            with pytest.raises(Exception, match="Token exchange failed"):
                await oauth.exchange_code_for_token('test_code')

    @pytest.mark.asyncio
    async def test_refresh_access_token_success(self, bootstrap):
        """Test successful token refresh."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/refreshtoken', 'test_refresh_token')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        mock_response = {
            'access_token': 'new_access_token',
            'refresh_token': 'new_refresh_token'
        }
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_resp
            
            result = await oauth.refresh_access_token('test_refresh_token')
            
            assert result == mock_response
            assert oauth.access_token == 'new_access_token'
            assert oauth.refresh_token == 'new_refresh_token'

    @pytest.mark.asyncio
    async def test_refresh_access_token_no_token(self, bootstrap):
        """Test token refresh fails without refresh token."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        with pytest.raises(ValueError, match="Refresh token is required"):
            await oauth.refresh_access_token()

    @pytest.mark.asyncio
    async def test_validate_token_success(self, bootstrap):
        """Test successful token validation."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        mock_response = {'valid': True, 'client_id': 'test_client'}
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_resp
            
            result = await oauth.validate_token('test_token')
            
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_validate_token_invalid(self, bootstrap):
        """Test token validation failure."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 401
            
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_resp
            
            result = await oauth.validate_token('invalid_token')
            
            assert result is False

    def test_get_stored_tokens(self, bootstrap):
        """Test getting stored tokens from config."""
        config = bootstrap
        config.cparser.setValue('kick/accesstoken', 'stored_access')
        config.cparser.setValue('kick/refreshtoken', 'stored_refresh')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        access_token, refresh_token = oauth.get_stored_tokens()
        
        assert access_token == 'stored_access'
        assert refresh_token == 'stored_refresh'

    def test_get_stored_tokens_empty(self, bootstrap):
        """Test getting stored tokens when none exist."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        access_token, refresh_token = oauth.get_stored_tokens()
        
        assert access_token is None
        assert refresh_token is None

    def test_clear_stored_tokens(self, bootstrap):
        """Test clearing stored tokens."""
        config = bootstrap
        config.cparser.setValue('kick/accesstoken', 'stored_access')
        config.cparser.setValue('kick/refreshtoken', 'stored_refresh')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        oauth.access_token = 'current_access'
        oauth.refresh_token = 'current_refresh'
        
        oauth.clear_stored_tokens()
        
        assert oauth.access_token is None
        assert oauth.refresh_token is None
        assert config.cparser.value('kick/accesstoken') is None
        assert config.cparser.value('kick/refreshtoken') is None

    @pytest.mark.asyncio
    async def test_revoke_token_success(self, bootstrap):
        """Test successful token revocation."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/accesstoken', 'test_token')
        
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_resp
            
            await oauth.revoke_token('test_token')
            
            assert oauth.access_token is None
            assert oauth.refresh_token is None
            assert config.cparser.value('kick/accesstoken') is None
            assert config.cparser.value('kick/refreshtoken') is None

    @pytest.mark.asyncio
    async def test_revoke_token_no_token(self, bootstrap):
        """Test token revocation with no token."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        # Should not raise an exception
        await oauth.revoke_token()