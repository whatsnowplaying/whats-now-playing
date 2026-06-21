#!/usr/bin/env python3
"""Lumia Stream Notification Plugin"""

import logging
from typing import TYPE_CHECKING

import aiohttp

from nowplaying.exceptions import PluginVerifyError
from nowplaying.types import TrackMetadata

from . import NotificationPlugin

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
    from PySide6.QtWidgets import QWidget

    import nowplaying.config

_DEFAULT_PORT = 39231


class Plugin(NotificationPlugin):
    """Lumia Stream Notification Handler"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Lumia Stream"
        self.enabled = False
        self.token: str = ""
        self.port: int = _DEFAULT_PORT
        self._session: aiohttp.ClientSession | None = None

    async def notify_track_change(self, metadata: TrackMetadata) -> None:
        """Send track metadata to Lumia Stream when a new track becomes live."""
        await self.start()
        if not self.enabled or not self.token:
            return

        payload = self.build_payload(metadata)
        url = f"http://localhost:{self.port}/api/send?token={self.token}"

        try:
            session = await self._get_session()
            async with session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status == 200:
                    logging.debug(
                        "Lumia Stream accepted track: %s - %s",
                        metadata.get("artist"),
                        metadata.get("title"),
                    )
                else:
                    error_text = ""
                    try:
                        error_text = await response.text()
                    except Exception:  # pylint: disable=broad-except
                        pass
                    logging.error(
                        "Lumia Stream returned status %d: %s", response.status, error_text
                    )
        except aiohttp.ClientError as exc:
            logging.error("Failed to connect to Lumia Stream on port %d: %s", self.port, exc)
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Unexpected error sending to Lumia Stream: %s", exc)

    @staticmethod
    def build_payload(metadata: TrackMetadata) -> dict:
        """Build the Lumia Stream nowplaying-switchSong alert payload."""
        httpport = metadata.get("httpport")
        image_url = f"http://localhost:{httpport}/cover.png" if httpport else ""

        duration = metadata.get("duration")
        isrc_list = metadata.get("isrc")

        extra: dict = {
            "title": metadata.get("title", ""),
            "artist": metadata.get("artist", ""),
            "album": metadata.get("album", ""),
            "label": metadata.get("label", ""),
            "bpm": metadata.get("bpm", ""),
            "key": metadata.get("key", ""),
            "comment": metadata.get("comments", ""),
            "length": str(duration) if duration is not None else "",
            "id": isrc_list[0] if isrc_list else "",
            "image": image_url,
            "artwork": "",
            "url": "",
            "spotify_url": "",
            "beatport_url": "",
            "beatport_id": "",
            "file_key": "",
            "rating": "",
        }

        return {
            "type": "alert",
            "params": {
                "value": "nowplaying-switchSong",
                "extraSettings": extra,
            },
        }

    async def start(self) -> None:
        """Read current config values."""
        if not self.config:
            return
        self.enabled = self.config.cparser.value(
            "lumiastream/enabled", type=bool, defaultValue=False
        )
        self.token = self.config.cparser.value("lumiastream/token", defaultValue="")
        self.port = self.config.cparser.value(
            "lumiastream/port", type=int, defaultValue=_DEFAULT_PORT
        )

    async def stop(self) -> None:
        """Close the aiohttp session."""
        await self._close_session()
        if self.enabled:
            logging.debug("Lumia Stream notifications stopped")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _close_session(self) -> None:
        """Close aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def defaults(self, qsettings: "QSettings") -> None:
        """Set default configuration values."""
        qsettings.setValue("lumiastream/enabled", False)
        qsettings.setValue("lumiastream/token", "")
        qsettings.setValue("lumiastream/port", _DEFAULT_PORT)

    def load_settingsui(self, qwidget: "QWidget") -> None:
        """Load settings into UI."""
        qwidget.enable_checkbox.setChecked(
            self.config.cparser.value("lumiastream/enabled", type=bool, defaultValue=False)
        )
        qwidget.token_lineedit.setText(
            self.config.cparser.value("lumiastream/token", defaultValue="")
        )
        qwidget.port_lineedit.setText(
            str(
                self.config.cparser.value("lumiastream/port", type=int, defaultValue=_DEFAULT_PORT)
            )
        )

    def save_settingsui(self, qwidget: "QWidget") -> None:
        """Save settings from UI."""
        self.config.cparser.setValue("lumiastream/enabled", qwidget.enable_checkbox.isChecked())
        self.config.cparser.setValue("lumiastream/token", qwidget.token_lineedit.text())
        try:
            port = int(qwidget.port_lineedit.text())
            self.config.cparser.setValue("lumiastream/port", port)
        except ValueError:
            pass

    def verify_settingsui(self, qwidget: "QWidget") -> bool:
        """Verify settings."""
        if qwidget.enable_checkbox.isChecked():
            if not qwidget.token_lineedit.text().strip():
                raise PluginVerifyError(
                    "Lumia Stream API token is required when Lumia Stream is enabled. "
                    "Find it in Lumia Stream: Settings > Advanced > Enable Developers API."
                )
            try:
                port = int(qwidget.port_lineedit.text())
                if not 1 <= port <= 65535:
                    raise PluginVerifyError("Port must be between 1 and 65535")
            except ValueError as err:
                raise PluginVerifyError("Port must be a valid number") from err
        return True

    def desc_settingsui(self, qwidget: "QWidget") -> None:
        """Description for settings UI."""
        qwidget.setText(
            "Send now-playing track metadata to Lumia Stream lighting software when tracks change."
        )
