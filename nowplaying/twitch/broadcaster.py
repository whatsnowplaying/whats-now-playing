#!/usr/bin/env python3
"""Twitch broadcaster-level API functionality"""

import asyncio
import logging
import pathlib
from typing import Any

import aiohttp
import jinja2  # pylint: disable=import-error

import nowplaying.db
import nowplaying.twitch.oauth2
import nowplaying.twitch.utils

TWITCH_TITLE_MAX_LEN = 140


class TwitchBroadcaster:
    """Handle broadcaster-level Twitch API calls (stream title, etc.)"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile" = None,
        stopevent: asyncio.Event = None,
    ):
        self.config = config
        self.stopevent = stopevent
        self.metadb = nowplaying.db.MetadataDB()
        self._last_title: str | None = None
        self._session: aiohttp.ClientSession | None = None
        self._jinja_env: jinja2.Environment | None = None
        self._jinja_template_dir: str | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the shared aiohttp session, creating it if needed."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _get_jinja_env(self, template_dir: str) -> jinja2.Environment:
        """Return a cached Jinja2 environment for the given template directory."""
        if self._jinja_env is None or self._jinja_template_dir != template_dir:
            self._jinja_env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(template_dir),
                finalize=self._finalize,
                trim_blocks=True,
            )
            self._jinja_template_dir = template_dir
        return self._jinja_env

    async def on_track_change(self) -> None:
        """Called by TwitchLaunch when a track change is detected"""
        self.config.get()
        await self._update_stream_title()

    async def _update_stream_title(self) -> None:  # pylint: disable=too-many-return-statements
        """Update the Twitch stream title from the configured Jinja2 template file"""
        if not self.config.cparser.value("twitchbot/streamtitle_enabled", type=bool):
            return

        template_path_str: str = self.config.cparser.value(
            "twitchbot/streamtitle", defaultValue=""
        )
        if not template_path_str:
            return

        template_path = pathlib.Path(template_path_str)
        if not template_path.is_file():
            logging.warning("Stream title template not found: %s", template_path)
            return

        metadata = await self.metadb.read_last_meta_async()
        if not metadata:
            return
        if not metadata.get("artist") and not metadata.get("title"):
            return

        try:
            env = self._get_jinja_env(str(template_path.parent))
            title = env.get_template(template_path.name).render(metadata).strip()
            title = title[:TWITCH_TITLE_MAX_LEN]
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Stream title template error: %s", error)
            return

        if not title or title == self._last_title:
            return

        self._last_title = title

        oauth = nowplaying.twitch.oauth2.TwitchOAuth2(self.config)
        access_token, _ = oauth.get_stored_tokens()
        if not access_token:
            logging.warning("No broadcaster token available for stream title update")
            return
        oauth.access_token = access_token
        session = await self._get_session()
        await nowplaying.twitch.utils.update_stream_title(oauth, title, session=session)

    async def stop(self) -> None:
        """Release shared resources"""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    @staticmethod
    def _finalize(variable: Any) -> Any | str:
        """helper routine to avoid NoneType exceptions in templates"""
        if variable is not None:
            return variable
        return ""
