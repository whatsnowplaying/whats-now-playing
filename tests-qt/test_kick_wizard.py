#!/usr/bin/env python3
"""Kick wizard: the auth URL goes to the clipboard, not a browser.

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

import nowplaying.kick.wizard


@pytest.fixture(name="clipboard")
def fixture_clipboard(monkeypatch) -> unittest.mock.MagicMock:
    """Record clipboard writes so a test run never clobbers the real clipboard."""
    board = unittest.mock.MagicMock()
    monkeypatch.setattr(nowplaying.kick.wizard.QApplication, "clipboard", lambda: board)
    return board


@pytest.fixture(name="no_browser")
def fixture_no_browser(monkeypatch):
    """Fail the test if anything tries to open a browser."""

    def _fail(*args, **kwargs):
        pytest.fail(f"webbrowser.open called with {args} {kwargs}")

    monkeypatch.setattr(webbrowser, "open", _fail)


def _page(config) -> nowplaying.kick.wizard._AuthorizePage:  # pylint: disable=protected-access
    return nowplaying.kick.wizard._AuthorizePage(config)  # pylint: disable=protected-access


@pytest.mark.usefixtures("no_browser")
def test_copies_auth_url_and_stores_pkce(bootstrap, qtbot, clipboard):
    """The copied URL's state must resolve to a verifier the callback can read."""
    bootstrap.cparser.setValue("kick/clientid", "wnptestclientid")
    bootstrap.cparser.setValue("kick/secret", "wnptestsecret")
    port = bootstrap.cparser.value("weboutput/httpport", type=int)

    page = _page(bootstrap)
    qtbot.addWidget(page)
    assert page.action_button.text() == "Copy Kick Auth URL"
    page.action_button.click()

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
    assert page.status.text().startswith("URL copied to clipboard.")
    # Re-copying has to stay possible until a token actually arrives.
    assert page.action_button.isEnabled()


@pytest.mark.usefixtures("no_browser")
def test_missing_client_id_leaves_clipboard_alone(bootstrap, qtbot, clipboard):
    """Without a Client ID there is no URL, so say so and copy nothing."""
    bootstrap.cparser.remove("kick/clientid")

    page = _page(bootstrap)
    qtbot.addWidget(page)
    page.action_button.click()

    clipboard.setText.assert_not_called()
    assert page.status.text().startswith("Could not generate auth URL")
