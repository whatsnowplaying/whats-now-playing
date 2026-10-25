#!/usr/bin/env python3
"""Kick settings: the auth URL goes to the clipboard, not a browser.

The user may be logged in to Kick in a browser other than the default, so the
URL has to be something they can paste where they choose. The callback runs in
the webserver process, so the PKCE verifier and state must land in config.
"""

import base64
import hashlib
import unittest.mock
import urllib.parse
import webbrowser

import pytest

import nowplaying.kick.settings
import nowplaying.settingsui
from nowplaying.kick.constants import ACCESS_TOKEN_KEY, OAUTH_STATUS_KEY


@pytest.fixture(name="clipboard")
def fixture_clipboard(monkeypatch) -> unittest.mock.MagicMock:
    """Record clipboard writes so a test run never clobbers the real clipboard."""
    board = unittest.mock.MagicMock()
    monkeypatch.setattr(nowplaying.kick.settings.QApplication, "clipboard", lambda: board)
    return board


@pytest.fixture(name="no_browser")
def fixture_no_browser(monkeypatch):
    """Fail the test if anything tries to open a browser."""

    def _fail(*args, **kwargs):
        pytest.fail(f"webbrowser.open called with {args} {kwargs}")

    monkeypatch.setattr(webbrowser, "open", _fail)


@pytest.fixture(name="kick_settings")
def fixture_kick_settings(bootstrap, qtbot):
    """The real kick.ui page, loaded and connected the way settingsui does it."""
    widget = nowplaying.settingsui.load_widget_ui(bootstrap, "kick")
    qtbot.addWidget(widget)
    settings = nowplaying.kick.settings.KickSettings()
    settings.load(bootstrap, widget, None)
    settings.connect(None, widget)
    widget.enable_checkbox.setChecked(True)
    yield settings
    settings.cleanup()


@pytest.mark.usefixtures("no_browser")
def test_copies_auth_url_and_stores_pkce(bootstrap, kick_settings, clipboard):
    """The copied URL's state must resolve to a verifier the callback can read."""
    widget = kick_settings.widget
    port = bootstrap.cparser.value("weboutput/httpport", type=int)
    widget.clientid_lineedit.setText("wnptestclientid")
    widget.secret_lineedit.setText("wnptestsecret")
    kick_settings.update_oauth_status()
    assert widget.authenticate_button.text() == "Copy Kick Auth URL"

    widget.authenticate_button.click()

    clipboard.setText.assert_called_once()
    url = clipboard.setText.call_args.args[0]
    assert url.startswith("https://id.kick.com/oauth/authorize?")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params["redirect_uri"] == [f"http://localhost:{port}/kickredirect"]
    state = params["state"][0]
    session_id = base64.urlsafe_b64decode(f"{state}==").decode("utf-8").split(":", 1)[0]

    bootstrap.get()
    assert bootstrap.cparser.value(f"kick/temp_state_{session_id}") == state
    verifier = bootstrap.cparser.value(f"kick/temp_code_verifier_{session_id}")
    # A verifier regenerated after the URL was built would fail the token exchange.
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    assert params["code_challenge"] == [base64.urlsafe_b64encode(digest).decode().rstrip("=")]
    assert widget.oauth_status_label.text().startswith("URL copied to clipboard.")
    # Re-copying has to stay possible until a token actually arrives.
    assert widget.authenticate_button.isEnabled()
    assert widget.authenticate_button.text() == "Copy Kick Auth URL"


@pytest.mark.usefixtures("no_browser")
@pytest.mark.parametrize(
    ("clientid", "secret", "expected"),
    [
        ("", "wnptestsecret", "Error: Client ID required"),
        ("wnptestclientid", "", "Error: Client Secret required"),
    ],
)
def test_missing_credentials_copy_nothing(kick_settings, clipboard, clientid, secret, expected):
    """Without both credentials there is no URL, so say so and copy nothing."""
    widget = kick_settings.widget
    widget.clientid_lineedit.setText(clientid)
    widget.secret_lineedit.setText(secret)

    widget.authenticate_button.click()

    clipboard.setText.assert_not_called()
    assert widget.oauth_status_label.text() == expected


def _session_id(url: str) -> str:
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
    return base64.urlsafe_b64decode(f"{state}==").decode("utf-8").split(":", 1)[0]


@pytest.mark.usefixtures("no_browser")
def test_recopy_keeps_earlier_url_valid(bootstrap, kick_settings, clipboard):
    """Copying again must not invalidate a URL already pasted into a browser."""
    widget = kick_settings.widget
    widget.clientid_lineedit.setText("wnptestclientid")
    widget.secret_lineedit.setText("wnptestsecret")

    widget.authenticate_button.click()
    widget.authenticate_button.click()

    first, second = (call.args[0] for call in clipboard.setText.call_args_list)
    first_session, second_session = _session_id(first), _session_id(second)
    assert first_session != second_session
    bootstrap.get()
    for url, session_id in ((first, first_session), (second, second_session)):
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        assert bootstrap.cparser.value(f"kick/temp_state_{session_id}") == state


def test_token_without_status_leaves_copy_enabled(bootstrap, kick_settings):
    """A saved token with no status from Kick chat must not lock out recopying."""
    widget = kick_settings.widget
    widget.clientid_lineedit.setText("wnptestclientid")
    widget.secret_lineedit.setText("wnptestsecret")
    bootstrap.cparser.setValue(ACCESS_TOKEN_KEY, "wnptesttoken")
    bootstrap.cparser.remove(OAUTH_STATUS_KEY)

    kick_settings.update_oauth_status()

    assert widget.oauth_status_label.text() == "Connecting..."
    assert widget.authenticate_button.isEnabled()
    assert widget.authenticate_button.text() == "Copy Kick Auth URL"
