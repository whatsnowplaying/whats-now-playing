/**
 * Shared WebSocket URL builder for guessgame templates.
 *
 * Port precedence: ?port= query param > window.location.port > 8899
 * IPv6 literals are wrapped in brackets as required by RFC 2732.
 *
 * Note: ws:// is used intentionally. The WNP webserver does not support
 * TLS/HTTPS, so wss:// is not applicable here.
 */
function buildWebSocketUrl(path, portOverride) {
    const { hostname, port } = window.location;
    const effectivePort = portOverride || port || '8899';
    // Wrap IPv6 literals in brackets (e.g. ::1 becomes [::1])
    const hostForUrl = hostname.includes(':') ? `[${hostname}]` : hostname;
    return `ws://${hostForUrl}:${effectivePort}${path}`;
}
