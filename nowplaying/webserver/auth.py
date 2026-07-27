#!/usr/bin/env python3
"""shared client authentication for inbound webserver endpoints"""

import logging
from typing import TYPE_CHECKING

import nowplaying.utils

if TYPE_CHECKING:
    from aiohttp import web

    import nowplaying.config

# Preferred way for clients to present the shared secret.  Headers stay out of
# access logs, proxy logs, and browser history, unlike query parameters.
CLIENT_AUTH_HEADER = "X-WNP-Client-Auth"

# Return values for check_client_auth()
AUTH_OK = "ok"
AUTH_MISSING = "missing"
AUTH_INVALID = "invalid"


def check_client_auth(
    request: "web.Request",
    config: "nowplaying.config.ConfigFile",
    legacy_secret: str = "",
    source: str = "Request",
) -> str:
    """Validate a client-provided secret against the configured webserver key.

    The secret is read from the CLIENT_AUTH_HEADER header when present,
    otherwise from legacy_secret -- the query parameter or body field older
    clients send.  Keeping the fallback means existing integrations continue
    to work unchanged.

    Args:
        request: the inbound request (supplies headers and remote address)
        config: config object holding the expected key
        legacy_secret: secret pulled from a query param or body field, used
            only when the header is absent
        source: short description used in auth-failure log messages

    Returns:
        AUTH_OK when authorized, or when no key is configured (auth disabled);
        AUTH_MISSING when a key is required but the client sent none;
        AUTH_INVALID when the client sent a secret that does not match.
    """
    required = str(config.cparser.value("remote/remote_key", type=str, defaultValue="") or "")
    if not required:
        return AUTH_OK

    provided = request.headers.get(CLIENT_AUTH_HEADER, "") or legacy_secret
    if not provided:
        logging.warning("%s without secret from %s", source, request.remote)
        return AUTH_MISSING

    if not nowplaying.utils.secure_compare(required, provided):
        logging.warning("%s with invalid secret from %s", source, request.remote)
        return AUTH_INVALID

    return AUTH_OK
