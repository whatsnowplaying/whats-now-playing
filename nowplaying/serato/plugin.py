#!/usr/bin/env python3
"""
Serato Main Plugin

This module contains the main plugin class that coordinates all the Serato components.
It handles the plugin lifecycle, UI integration, and track polling for both local
Serato libraries and Serato Live playlists.
"""

import logging
import os
import pathlib
import random
import struct
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QFileDialog

from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin

from .crate import SeratoCrateReader
from .database import SeratoDatabaseV2Reader
from .handler import SeratoHandler
from .smart_crate import SeratoSmartCrateReader

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.uihelp


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """handler for NowPlaying"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Serato"
        self.url: str | None = None
        self.libpath = None
        self.local = True
        self.serato = None
        self.mixmode = "newest"
        self.testmode = False
        # Network failure tracking for circuit breaker pattern
        self.network_failure_count = 0
        self.last_network_failure_time = 0
        self.backoff_until: int = 0
        # Track last extracted track to reduce success log spam
        self.last_extracted_track = None
        self.last_extraction_method = None
        # Cache crate file counts to avoid re-parsing
        self._crate_count_cache: dict[str, int] = {}

    def clear_crate_cache(self) -> None:
        """Clear the crate count cache (useful if crates are modified)"""
        self._crate_count_cache.clear()
        logging.debug("Cleared crate count cache")

    def install(self):
        """auto-install for Serato"""
        seratodir = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.MusicLocation)[0]
        ).joinpath("_Serato_")

        if seratodir.exists():
            self.config.cparser.value("settings/input", "serato")
            self.config.cparser.value("serato/libpath", str(seratodir))
            return True

        return False

    async def gethandler(self):
        """setup the SeratoHandler for this session"""

        stilllocal = self.config.cparser.value("serato/local", type=bool)
        usepoll = self.config.cparser.value("quirks/pollingobserver", type=bool)

        # now configured as remote!
        if not stilllocal:
            stillurl: str = self.config.cparser.value("serato/url")

            # if previously remote and same URL, do nothing
            if not self.local and self.url == stillurl:
                return

            logging.debug("new url = %s", stillurl)
            self.local = stilllocal
            self.url = stillurl
            if self.serato:
                self.serato.stop()
            polling_interval = self.config.cparser.value(
                "quirks/pollinginterval", type=float, defaultValue=1.0
            )
            self.serato = SeratoHandler(
                pollingobserver=usepoll,
                seratourl=self.url,
                testmode=self.testmode,
                polling_interval=polling_interval,
            )
            return

        # configured as local!

        self.local = stilllocal
        stilllibpath = self.config.cparser.value("serato/libpath")
        stillmixmode = self.config.cparser.value("serato/mixmode")

        # same path and same mixmode, no nothing
        if self.libpath == stilllibpath and self.mixmode == stillmixmode:
            return

        self.libpath = stilllibpath
        self.mixmode = stillmixmode

        self.serato = None

        # paths for session history
        hist_dir = os.path.abspath(os.path.join(self.libpath, "History"))
        sess_dir = os.path.abspath(os.path.join(hist_dir, "Sessions"))
        if os.path.isdir(sess_dir):
            logging.debug("new session path = %s", sess_dir)
            polling_interval = self.config.cparser.value(
                "quirks/pollinginterval", type=float, defaultValue=1.0
            )
            self.serato = SeratoHandler(
                seratodir=self.libpath,
                mixmode=self.mixmode,
                pollingobserver=usepoll,
                testmode=self.testmode,
                polling_interval=polling_interval,
            )
            # if self.serato:
            #    self.serato.process_sessions()
        else:
            logging.error("%s does not exist!", sess_dir)
            return
        await self.serato.start()

    async def start(self, testmode=False):
        """get a handler"""
        self.testmode = testmode
        await self.gethandler()

    async def getplayingtrack(self):
        """wrapper to call getplayingtrack"""
        await self.gethandler()

        # get poll interval and then poll
        if self.local:
            interval = 1
        else:
            interval = self.config.cparser.value("settings/interval", type=float)

        time.sleep(interval)

        if self.serato:
            deckskip = self.config.cparser.value("serato/deckskip")
            if deckskip and not isinstance(deckskip, list):
                deckskip = list(deckskip)
            return self.serato.getplayingtrack(deckskiplist=deckskip)
        return {}

    async def getrandomtrack(  # pylint: disable=too-many-return-statements
        self, playlist: str
    ) -> str | None:
        """Get the files associated with a playlist, crate, whatever"""

        libpath = self.config.cparser.value("serato/libpath")
        logging.debug("libpath: %s", libpath)
        if not libpath:
            return None

        crate_path = pathlib.Path(libpath).joinpath("Subcrates")
        smartcrate_path = pathlib.Path(libpath).joinpath("SmartCrates")

        logging.debug("Determined: %s %s", crate_path, smartcrate_path)

        # Check for regular crate first
        if crate_path.joinpath(f"{playlist}.crate").exists():
            playlistfile = crate_path.joinpath(f"{playlist}.crate")
            logging.debug("Using regular crate: %s", playlistfile)

            try:
                crate = SeratoCrateReader(playlistfile)
                await crate.loadcrate()

                # Check plugin-level cache first
                cache_key = str(playlistfile)
                if cache_key in self._crate_count_cache:
                    file_count = self._crate_count_cache[cache_key]
                else:
                    # Two-pass approach: count first, then cache
                    file_count = crate.count_files()
                    self._crate_count_cache[cache_key] = file_count

                if file_count == 0:
                    return None

                random_index = random.randrange(file_count)
                return crate.get_file_at_index(random_index)

            except (IOError, struct.error, UnicodeDecodeError) as err:
                logging.error("Failed to load crate %s: %s", playlist, err)
                return None

        # Check for smart crate
        elif smartcrate_path.joinpath(f"{playlist}.scrate").exists():
            playlistfile = smartcrate_path.joinpath(f"{playlist}.scrate")
            logging.debug("Using smart crate: %s", playlistfile)

            smart_crate = SeratoSmartCrateReader(playlistfile, libpath)
            await smart_crate.loadsmartcrate()
            if filelist := await smart_crate.getfilenames():
                return filelist[random.randrange(len(filelist))] if filelist else None
        else:
            logging.error("Unknown crate: %s", playlist)
            return None

        return None

    def defaults(self, qsettings: "QSettings"):
        qsettings.setValue(
            "serato/libpath",
            os.path.join(
                QStandardPaths.standardLocations(QStandardPaths.MusicLocation)[0], "_Serato_"
            ),
        )
        qsettings.setValue("serato/interval", 10.0)
        qsettings.setValue("serato/local", True)
        qsettings.setValue("serato/mixmode", "newest")
        qsettings.setValue("serato/url", None)
        qsettings.setValue("serato/deckskip", None)
        qsettings.setValue("serato/artist_query_scope", "entire_library")
        qsettings.setValue("serato/selected_playlists", "")

    def validmixmodes(self):
        """let the UI know which modes are valid"""
        if self.config.cparser.value("serato/local", type=bool):
            return ["newest", "oldest"]

        return ["newest"]

    def setmixmode(self, mixmode: str):
        """set the mixmode"""
        if mixmode not in ["newest", "oldest"]:
            mixmode = self.config.cparser.value("serato/mixmode")

        if not self.config.cparser.value("serato/local", type=bool):
            mixmode = "newest"

        self.config.cparser.setValue("serato/mixmode", mixmode)
        return mixmode

    def getmixmode(self):
        """get the mixmode"""

        if self.config.cparser.value("serato/local", type=bool):
            return self.config.cparser.value("serato/mixmode")

        self.config.cparser.setValue("serato/mixmode", "newest")
        return "newest"

    async def stop(self):
        """stop the handler"""
        if self.serato:
            self.serato.stop()
        # Clear crate cache on stop
        self._crate_count_cache.clear()

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if DJ has any tracks by the specified artist"""
        try:
            scope = self.config.cparser.value(
                "serato/artist_query_scope", defaultValue="entire_library"
            )
            libpath = self.config.cparser.value("serato/libpath")

            if scope == "selected_playlists":
                return await self._has_tracks_in_selected_playlists(artist_name, libpath)

            return await self._has_tracks_in_entire_library(artist_name, libpath)

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error("Failed to query Serato database for artist %s: %s", artist_name, err)
            return False

    async def _has_tracks_in_selected_playlists(  # pylint: disable=too-many-locals,too-many-branches
        self, artist_name: str, libpath: str
    ) -> bool:
        """Check for artist tracks in specific playlists/crates"""
        selected_playlists = self.config.cparser.value(
            "serato/selected_playlists", defaultValue=""
        )
        if not selected_playlists.strip():
            return False

        playlist_names = [name.strip() for name in selected_playlists.split(",") if name.strip()]
        if not playlist_names:
            return False

        artist_name_lower = artist_name.lower()

        # Check each specified playlist/crate
        for playlist_name in playlist_names:  # pylint: disable=too-many-nested-blocks
            crate_path = pathlib.Path(libpath).joinpath("Subcrates", f"{playlist_name}.crate")
            smartcrate_path = pathlib.Path(libpath).joinpath(
                "SmartCrates", f"{playlist_name}.scrate"
            )

            # Check regular crate
            if crate_path.exists():
                try:
                    crate = SeratoCrateReader(crate_path)
                    await crate.loadcrate()

                    # Check if any track in this crate matches the artist
                    for track_file in crate.files:
                        if artist_name_lower in track_file.get("artist", "").lower():
                            return True

                except (IOError, struct.error, UnicodeDecodeError) as err:
                    logging.error("Failed to load crate %s: %s", playlist_name, err)
                    continue

            # Check smart crate
            elif smartcrate_path.exists():
                try:
                    smart_crate = SeratoSmartCrateReader(smartcrate_path, libpath)
                    await smart_crate.loadsmartcrate()

                    # For smart crates, we need to get the actual file list and check artists
                    if filelist := await smart_crate.getfilenames():
                        # Load database to get track metadata for comparison
                        db_reader = SeratoDatabaseV2Reader(libpath)
                        await db_reader.loaddatabase()

                        for filename in filelist:
                            # Find track in database by filename
                            for track in db_reader.tracks:
                                if track.get("filename") == filename:
                                    if track.get("artist", "").lower() == artist_name_lower:
                                        return True
                                    break

                except (IOError, struct.error, UnicodeDecodeError) as err:
                    logging.error("Failed to load smart crate %s: %s", playlist_name, err)
                    continue

        return False

    @staticmethod
    async def _has_tracks_in_entire_library(artist_name: str, libpath: str) -> bool:
        """Check for artist tracks in entire library"""
        db_reader = SeratoDatabaseV2Reader(libpath)
        await db_reader.loaddatabase()

        artist_name_lower = artist_name.lower()
        return any(
            track.get("artist", "").lower() == artist_name_lower for track in db_reader.tracks
        )

    def on_serato_lib_button(self):
        """lib button clicked action"""
        startdir = self.qwidget.local_dir_lineedit.text() or str(pathlib.Path.home())
        if libdir := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            self.qwidget.local_dir_lineedit.setText(libdir)

    def connect_settingsui(self, qwidget: "QWidget", uihelp: "nowplaying.uihelp.UIHelp"):
        """connect serato local dir button"""
        self.qwidget = qwidget
        self.uihelp = uihelp
        self.qwidget.local_dir_button.clicked.connect(self.on_serato_lib_button)

    def load_settingsui(self, qwidget: "QWidget"):
        """draw the plugin's settings page"""

        def handle_deckskip(cparser, qwidget: "QWidget"):
            deckskip = cparser.value("serato/deckskip")
            qwidget.deck1_checkbox.setChecked(False)
            qwidget.deck2_checkbox.setChecked(False)
            qwidget.deck3_checkbox.setChecked(False)
            qwidget.deck4_checkbox.setChecked(False)

            if not deckskip:
                return

            if not isinstance(deckskip, list):
                deckskip = list(deckskip)

            if "1" in deckskip:
                qwidget.deck1_checkbox.setChecked(True)

            if "2" in deckskip:
                qwidget.deck2_checkbox.setChecked(True)

            if "3" in deckskip:
                qwidget.deck3_checkbox.setChecked(True)

            if "4" in deckskip:
                qwidget.deck4_checkbox.setChecked(True)

        if self.config.cparser.value("serato/local", type=bool):
            qwidget.local_button.setChecked(True)
            qwidget.remote_button.setChecked(False)
        else:
            qwidget.local_dir_button.setChecked(False)
            qwidget.remote_button.setChecked(True)
        qwidget.local_dir_lineedit.setText(self.config.cparser.value("serato/libpath"))
        qwidget.remote_url_lineedit.setText(self.config.cparser.value("serato/url"))
        qwidget.remote_poll_lineedit.setText(str(self.config.cparser.value("serato/interval")))
        handle_deckskip(self.config.cparser, qwidget)

        # Set artist query scope
        scope = self.config.cparser.value(
            "serato/artist_query_scope", defaultValue="entire_library"
        )
        if scope == "selected_playlists":
            qwidget.serato_artist_scope_combo.setCurrentText("Selected Playlists")
        else:
            qwidget.serato_artist_scope_combo.setCurrentText("Entire Library")

        # Load selected playlists
        qwidget.serato_playlists_lineedit.setText(
            self.config.cparser.value("serato/selected_playlists", defaultValue="")
        )

    def verify_settingsui(self, qwidget: "QWidget"):
        """no verification to do"""
        if qwidget.remote_button.isChecked() and (
            "https://serato.com/playlists" not in qwidget.remote_url_lineedit.text()
            and "https://www.serato.com/playlists" not in qwidget.remote_url_lineedit.text()
            or len(qwidget.remote_url_lineedit.text()) < 30
        ):
            raise PluginVerifyError("Serato Live Playlist URL is invalid")

        if qwidget.local_button.isChecked() and (
            "_Serato_" not in qwidget.local_dir_lineedit.text()
        ):
            raise PluginVerifyError(
                r'Serato Library Path is required.  Should point to "\_Serato\_" folder'
            )

    def save_settingsui(self, qwidget: "QWidget"):
        """take the settings page and save it"""
        self.config.cparser.setValue("serato/libpath", qwidget.local_dir_lineedit.text())
        self.config.cparser.setValue("serato/local", qwidget.local_button.isChecked())
        self.config.cparser.setValue("serato/url", qwidget.remote_url_lineedit.text())
        self.config.cparser.setValue("serato/interval", qwidget.remote_poll_lineedit.text())

        deckskip = []
        if qwidget.deck1_checkbox.isChecked():
            deckskip.append("1")
        if qwidget.deck2_checkbox.isChecked():
            deckskip.append("2")
        if qwidget.deck3_checkbox.isChecked():
            deckskip.append("3")
        if qwidget.deck4_checkbox.isChecked():
            deckskip.append("4")

        self.config.cparser.setValue("serato/deckskip", deckskip)

        # Save artist query scope
        scope = (
            "selected_playlists"
            if qwidget.serato_artist_scope_combo.currentText() == "Selected Playlists"
            else "entire_library"
        )
        self.config.cparser.setValue("serato/artist_query_scope", scope)

        # Save selected playlists
        self.config.cparser.setValue(
            "serato/selected_playlists", qwidget.serato_playlists_lineedit.text()
        )

    def desc_settingsui(self, qwidget: "QWidget"):
        """description"""
        qwidget.setText(
            "This plugin provides support for Serato in both a local and remote capacity."
        )
