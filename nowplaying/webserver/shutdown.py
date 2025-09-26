#!/usr/bin/env python3
"""WebSocket shutdown handling utilities"""

import logging

# Global flag to track if WebServer is in forced shutdown mode
_WEBSOCKET_FORCED_SHUTDOWN = False


def safe_stopevent_check_websocket(stopevent):
    """
    WebSocket-safe version of stopevent check that handles transient pipe errors.

    For WebSocket connections, we need to be more conservative about pipe errors
    since they might be temporary issues rather than actual shutdown signals.
    Only treat repeated pipe errors as actual shutdown.
    """
    if _WEBSOCKET_FORCED_SHUTDOWN:
        return True

    try:
        return stopevent.is_set()
    except (BrokenPipeError, EOFError, AttributeError) as error:
        # For WebSocket connections, log but don't immediately shutdown
        # This prevents connection loops when main process has temporary issues
        logging.warning("WebSocket pipe error: %s - continuing operation", error)
        return False  # Don't shutdown on first pipe error
    except OSError as error:
        # Log details for analysis of unexpected OSErrors in production
        error_details = f"errno={getattr(error, 'errno', 'N/A')}"
        if hasattr(error, "winerror"):
            error_details += f", winerror={error.winerror}"
        logging.warning(
            "WebSocket OSError in stopevent check (%s): %s - continuing operation",
            error_details,
            error,
        )
        return False  # Don't shutdown on OSError for WebSocket


def force_websocket_shutdown():
    """Enable forced shutdown mode for WebSocket connections"""
    global _WEBSOCKET_FORCED_SHUTDOWN  # pylint: disable=global-statement
    _WEBSOCKET_FORCED_SHUTDOWN = True
    logging.info("Enabled forced WebSocket shutdown mode")


def reset_websocket_shutdown():
    """Reset WebSocket shutdown state for testing"""
    global _WEBSOCKET_FORCED_SHUTDOWN  # pylint: disable=global-statement
    _WEBSOCKET_FORCED_SHUTDOWN = False
