#!/usr/bin/env python3
''' Kick-related constants '''

import nowplaying.oauth2

# OAuth and API endpoints
OAUTH_HOST = 'https://id.kick.com'
API_HOST = 'https://api.kick.com'
API_BASE = 'https://api.kick.com/public/v1'
TOKEN_INTROSPECT_ENDPOINT = 'https://api.kick.com/public/v1/token/introspect'

# OAuth scopes
KICK_SCOPES = ['user:read', 'chat:write', 'events:subscribe']

# OAuth2 service configuration
KICK_SERVICE_CONFIG: nowplaying.oauth2.ServiceConfig = {
    'oauth_host': OAUTH_HOST,
    'api_host': API_HOST,
    'config_prefix': 'kick',
    'default_scopes': KICK_SCOPES,
    'token_endpoint': '/oauth/token',
    'authorize_endpoint': '/oauth/authorize',
    'revoke_endpoint': '/oauth/revoke'
    # Note: Kick's validation uses api.kick.com/public/v1/token/introspect
    # which is handled separately in validate_token_async()
}

# Chat constants
KICK_MESSAGE_LIMIT = 500  # Character limit for Kick messages
KICK_CHAT_TIMEOUT = 60  # HTTP timeout for chat API calls in seconds
SPLIT_MESSAGE_TEXT = '****SPLITMESSAGEHERE****'  # Message splitting marker

# UI constants - needs to match ui file
KICKBOT_CHECKBOXES = ['anyone', 'broadcaster', 'moderator', 'subscriber', 'founder', 'vip']
