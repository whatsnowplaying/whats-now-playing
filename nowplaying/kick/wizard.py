#!/usr/bin/env python3
"""Guided OAuth authorization wizard for Kick.

Launched from Kick settings.
"""

# pylint: disable=too-few-public-methods

import webbrowser
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QWizard  # pylint: disable=no-name-in-module

import nowplaying.kick.oauth2
from nowplaying.wizard.finish import FinishPage
from nowplaying.wizard.tokenpoll import TokenPollPage

if TYPE_CHECKING:
    import nowplaying.config

_FINISH_BODY = (
    "Kick is now authorized. What's Now Playing will use these credentials "
    "when it runs.\n\n"
    "You can re-authorize at any time from Settings."
)


class _AuthorizePage(TokenPollPage):
    """Open the browser for Kick's OAuth flow and wait for the token."""

    authorized_key = "kick/accesstoken"
    action_text = "Open Browser to Authorize Kick"
    success_text = "✅ Kick authorized."
    disable_when_done = True

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(config, parent)
        self.setTitle("Authorize Kick")
        self.setSubTitle(
            "WNP will open your browser to authorize with Kick. "
            "Complete the login and this page will update automatically."
        )

    def act(self) -> str:
        """Send the user to Kick's authorization page."""
        oauth = nowplaying.kick.oauth2.KickOAuth2(config=self._config)
        # get_auth_url() sets redirect_uri and generates PKCE in one shot;
        # open_browser_for_auth() would regenerate PKCE, causing a state mismatch.
        url = oauth.get_auth_url()
        if not url:
            return (
                "Could not generate auth URL — check that your Client ID and "
                "Client Secret are saved in Settings."
            )
        webbrowser.open(url)
        # Not disabled here: disable_when_done already does it once a token
        # arrives, and doing it on open strands anyone who declines the login
        # or loses the callback, with Next still blocked behind the token.
        return "Browser opened — complete authorization on the Kick website."


class KickWizard(QWizard):
    """Step-by-step OAuth authorization wizard for Kick."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Up Kick")
        self.setModal(True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)

        self.addPage(_AuthorizePage(config))
        self.addPage(FinishPage("Kick Setup Complete", _FINISH_BODY))
