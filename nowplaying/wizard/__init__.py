#!/usr/bin/env python3
"""Wizard infrastructure shared between the setup wizard and input plugins.

Facade only. Twelve input plugins reach for `nowplaying.wizard.WizardPage`, so
that name stays here regardless of how the internals are arranged.

Feature wizards live with their feature -- `nowplaying/twitch/wizard.py` beside
`twitch/settings.py` and `twitch/oauth2.py`. The exception is `artistextras`,
which is a plugin package and so cannot hold a helper module without tripping
`pluginimporter`; its wizard lives here instead.
"""

from nowplaying.wizard.page import WizardPage
from nowplaying.wizard.verify import VerifyResult, VerifyStatus

__all__ = ["WizardPage", "VerifyResult", "VerifyStatus"]
