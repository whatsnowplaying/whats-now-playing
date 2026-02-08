#!/usr/bin/env python3
"""Shared utilities for Charts API communication"""

import logging

# Base URLs for charts service
LOCAL_BASE_URL = "http://localhost:8000"
PROD_BASE_URL = "https://whatsnowplaying.com"

# HTTP status code handling for charts submissions
HTTP_STATUS_ACTIONS = {
    200: ("success", "debug", "Charts server accepted submission"),
    400: ("drop", "error", "Charts server rejected malformed data"),
    401: ("retry", "error", "Charts server authentication failed"),
    403: ("retry", "error", "Charts server authentication failed"),
    404: ("drop", "error", "Charts server endpoint not found"),
    405: ("drop", "error", "Charts server method not allowed"),
    429: ("retry", "warning", "Charts server rate limited"),
}


def handle_http_response(status: int, response_text: str = "") -> str:
    """
    Handle HTTP response status codes for charts submissions

    Args:
        status: HTTP status code
        response_text: Response body text for logging

    Returns:
        str: Action to take ("success", "retry", "drop")
    """
    # Check for specific status codes first
    if status in HTTP_STATUS_ACTIONS:
        action, log_level, message = HTTP_STATUS_ACTIONS[status]
        full_message = f"{message} ({status}): {response_text}"

        if log_level == "warning":
            logging.warning(full_message)
        elif log_level == "error":
            logging.error(full_message)
        elif log_level == "info":
            logging.info(full_message)
        elif log_level == "debug":
            logging.debug(full_message)

        return action

    # Handle ranges for unlisted status codes
    if 400 <= status < 500:
        logging.error("Charts server client error %d: %s", status, response_text)
        return "drop"  # Client errors won't resolve by retrying
    logging.error("Charts server error %d: %s", status, response_text)
    return "retry"  # Server errors may recover


def is_valid_api_key(key: str) -> bool:
    """
    Validate API key format

    Args:
        key: API key to validate

    Returns:
        bool: True if key format is valid
    """
    # API keys should be non-empty strings with reasonable length
    return isinstance(key, str) and len(key.strip()) >= 10
