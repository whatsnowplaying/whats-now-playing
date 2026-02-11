#!/usr/bin/env python3
"""Shared utilities for Charts API communication"""

import json
import logging
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt  # pylint: disable=import-error,no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=import-error,no-name-in-module
    QApplication,
    QMessageBox,
)

if TYPE_CHECKING:
    import nowplaying.config

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


def get_charts_base_url(config: "nowplaying.config.ConfigFile | None" = None) -> str:
    """
    Get the appropriate charts base URL based on debug configuration.

    Args:
        config: Optional config object. If None or debug not set, returns PROD_BASE_URL.

    Returns:
        str: Either LOCAL_BASE_URL (if debug=True) or PROD_BASE_URL (if debug=False)
    """
    if config is None:
        return PROD_BASE_URL

    debug_mode = config.cparser.value("charts/debug", defaultValue=False, type=bool)
    if debug_mode:
        return LOCAL_BASE_URL
    return PROD_BASE_URL


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

        # Only log non-success responses to avoid spam (200 happens every 2s)
        if status != 200:
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


def _show_platform_conflict_dialog(platform: str) -> None:
    """
    Show error dialog for platform account conflict (409 error).
    Must be called from Qt main thread.

    Args:
        platform: Platform name (e.g., "Twitch")
    """
    dialog = QMessageBox(
        QMessageBox.Icon.Warning,
        f"{platform} Account Already Linked",
        f"Your {platform} account is already linked to an existing charts profile.<br><br>"
        f"To merge your current data with that profile:<br>"
        f"1. Go to <a href='https://whatsnowplaying.com/dashboard'>"
        f"whatsnowplaying.com/dashboard</a><br>"
        f"2. Log in using {platform} (this logs you into your existing account)<br>"
        f"3. Use the claim form to enter your current charts API key<br>"
        f"4. Your data will be merged and your key will be linked",
        QMessageBox.StandardButton.Ok,
        QApplication.activeWindow(),
    )
    dialog.setTextFormat(Qt.TextFormat.RichText)
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dialog.exec()


def link_platform_account(  # pylint: disable=too-many-locals
    config: "nowplaying.config.ConfigFile", platform: str, platform_token: str
) -> tuple[bool, dict | None]:
    """
    Link streaming platform account to charts API key.

    Args:
        config: Config object with charts API key
        platform: Platform name ("twitch", "kick", "youtube", etc.)
        platform_token: OAuth access token for the platform

    Returns:
        Tuple of (success: bool, response_data: dict | None)
        response_data contains: status, platform, platform_username, profile_slug
    """
    # Check if platform linking is enabled
    link_enabled = config.cparser.value("charts/link_platform", type=bool, defaultValue=True)
    if not link_enabled:
        logging.debug("Platform linking disabled, skipping %s account link", platform)
        return (False, None)

    charts_key = config.cparser.value("charts/charts_key", defaultValue="")
    if not is_valid_api_key(charts_key):
        logging.debug("No valid charts API key, skipping %s account link", platform)
        return (False, None)

    base_url = get_charts_base_url(config)
    url = f"{base_url}/api/auth/link-platform"

    payload = {"secret": charts_key, "platform": platform, "platform_token": platform_token}

    try:
        # Make HTTP POST request
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status == 200:
                response_data = response.read()
                result = json.loads(response_data)
                platform_username = result.get("platform_username", "")
                profile_slug = result.get("profile_slug", "")
                logging.info(
                    "%s account linked to charts: %s (profile: %s)",
                    platform.capitalize(),
                    platform_username,
                    profile_slug,
                )
                return (True, result)

        # urllib raises HTTPError for non-2xx status codes, so this shouldn't be reached
        return (False, None)

    except urllib.error.HTTPError as exc:
        # Handle HTTP errors with status codes
        try:
            error_data = exc.read()
            error_response = json.loads(error_data)
            error_detail = error_response.get("detail", "Unknown error")
        except Exception:  # pylint: disable=broad-except
            error_detail = str(exc)

        # Handle specific status codes
        if exc.code == 400:
            # Client errors: malformed request, missing params, invalid token, etc.
            logging.error(
                "Failed to link %s account to charts (bad request): %s",
                platform,
                error_detail,
            )
        elif exc.code == 401:
            # Missing or invalid API key
            logging.error(
                "Failed to link %s account to charts (authentication failed): %s",
                platform,
                error_detail,
            )
        elif exc.code == 403:
            # Account blocked from using API
            logging.error(
                "Failed to link %s account to charts (account blocked): %s",
                platform,
                error_detail,
            )
        elif exc.code == 409:
            # Platform account already linked to different user
            logging.error(
                "%s account already linked to existing charts profile: %s",
                platform.capitalize(),
                error_detail,
            )
            # Show error dialog (already in Qt main thread)
            _show_platform_conflict_dialog(platform.capitalize())
        else:
            # Unexpected error
            logging.error(
                "Failed to link %s account to charts (%d): %s",
                platform,
                exc.code,
                error_detail,
            )
        return (False, None)

    except Exception as exc:  # pylint: disable=broad-except
        logging.error("Error linking %s account to charts: %s", platform, exc)
        return (False, None)
