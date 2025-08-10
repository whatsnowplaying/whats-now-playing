#!/usr/bin/env python3
"""
Serato Main Plugin

This module contains the main plugin class that coordinates all the Serato components.
It handles the plugin lifecycle, UI integration, and track polling for both local
Serato libraries and Serato Live playlists.
"""

import asyncio
import logging
import os
import pathlib
import random
import struct
from typing import TYPE_CHECKING

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

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

        await asyncio.sleep(interval)

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

    def _get_all_database_paths(self) -> list[str]:
        """Get all configured Serato database paths (primary + additional)"""
        paths = []

        # Primary libpath (for session files and primary database)
        primary_path = self.config.cparser.value("serato/libpath")
        if primary_path:
            paths.append(primary_path)

        if additional_paths := self.config.cparser.value(
            "serato/additional_libpaths", defaultValue=""
        ):
            # Split by newlines or semicolons, strip whitespace, filter empty
            extra_paths = [
                path.strip()
                for path in additional_paths.replace(";", "\n").split("\n")
                if path.strip()
            ]
            paths.extend(extra_paths)

        return paths

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if DJ has any tracks by the specified artist"""
        try:
            scope = self.config.cparser.value(
                "serato/artist_query_scope", defaultValue="entire_library"
            )
            libpaths = self._get_all_database_paths()

            if not libpaths:
                logging.warning("No Serato library paths configured")
                return False

            if scope == "selected_playlists":
                # Check selected playlists across all database paths
                return await self._has_tracks_in_selected_playlists(artist_name)

            # Check entire library across all database paths
            for libpath in libpaths:
                if await self._has_tracks_in_entire_library(artist_name, libpath):
                    logging.debug("Found artist '%s' in database: %s", artist_name, libpath)
                    return True
            return False

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.exception(
                "Failed to query Serato database for artist %s: %s", artist_name, err
            )
            return False

    @staticmethod
    async def _find_artist_in_filelist(
        filelist: list[str], artist_name: str, libpath: str
    ) -> bool:
        """Check if artist exists in any of the provided files by looking up metadata in database"""
        artist_name_lower = artist_name.lower()

        try:  # pylint: disable=too-many-nested-blocks
            db_reader = SeratoDatabaseV2Reader(libpath)
            await db_reader.loaddatabase()
            logging.debug("Database %s loaded with %d tracks", libpath, len(db_reader.tracks))

            for crate_filename in filelist:
                logging.debug("Checking crate file: %s", crate_filename)

                # Normalize paths - crate has leading slash, database doesn't
                # Convert /washu/path -> washu/path for cross-platform compatibility
                normalized_crate_path = crate_filename.lstrip("/")

                # Find track in database by filepath (not just filename)
                track_found = False
                for track in db_reader.tracks:
                    db_filepath = track.get("filepath", "")
                    if db_filepath == normalized_crate_path:
                        track_found = True
                        track_artist = track.get("artist", "")
                        logging.debug(
                            "Found track in DB: %s, artist: '%s', searching for: '%s'",
                            normalized_crate_path,
                            track_artist,
                            artist_name,
                        )
                        if artist_name_lower in track_artist.lower():
                            logging.debug(
                                "Found artist '%s' in file: %s", artist_name, crate_filename
                            )
                            return True
                        break

                if not track_found:
                    logging.debug(
                        "Track not found in database: %s (normalized: %s)",
                        crate_filename,
                        normalized_crate_path,
                    )

            return False

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error("Failed to check database %s: %s", libpath, err)
            return False
        finally:
            # Clean up memory
            if "db_reader" in locals():
                del db_reader

    async def _check_regular_crate_in_path(
        self, playlist_name: str, artist_name: str, libpath: str
    ) -> bool:
        """Check if artist exists in a regular crate at the given library path"""
        crate_path = pathlib.Path(libpath).joinpath("Subcrates", f"{playlist_name}.crate")

        if not crate_path.exists():
            return False

        try:
            logging.debug("Loading regular crate: %s", crate_path)
            crate = SeratoCrateReader(crate_path)
            await crate.loadcrate()

            if filelist := crate.getfilenames():
                logging.debug("Regular crate '%s' contains %d files", playlist_name, len(filelist))
                return await self._find_artist_in_filelist(filelist, artist_name, libpath)
            logging.debug("Regular crate '%s' contains no files", playlist_name)
            return False

        except (IOError, struct.error, UnicodeDecodeError) as err:
            logging.error("Failed to load crate %s: %s", playlist_name, err)
            return False

    async def _check_smart_crate_in_path(
        self, playlist_name: str, artist_name: str, libpath: str
    ) -> bool:
        """Check if artist exists in a smart crate at the given library path"""
        smartcrate_path = pathlib.Path(libpath).joinpath("SmartCrates", f"{playlist_name}.scrate")

        if not smartcrate_path.exists():
            return False

        try:
            logging.debug("Loading smart crate: %s", smartcrate_path)
            smart_crate = SeratoSmartCrateReader(smartcrate_path, libpath)
            await smart_crate.loadsmartcrate()

            # For smart crates, check across all configured library paths
            all_libpaths = self._get_all_database_paths()
            logging.debug(
                "Checking smart crate against %d library paths: %s",
                len(all_libpaths),
                all_libpaths,
            )

            if filelist := await smart_crate.getfilenames_from_multiple_paths(all_libpaths):
                logging.debug(
                    "Smart crate '%s' returned %d files across all libraries",
                    playlist_name,
                    len(filelist),
                )

                # Check each library path for artist matches
                for check_libpath in all_libpaths:
                    if await self._find_artist_in_filelist(filelist, artist_name, check_libpath):
                        return True
                return False
            logging.debug("Smart crate '%s' returned no files across all libraries", playlist_name)
            return False

        except (IOError, struct.error, UnicodeDecodeError) as err:
            logging.error("Failed to load smart crate %s: %s", playlist_name, err)
            return False

    async def _has_tracks_in_selected_playlists(  # pylint: disable=too-many-locals,too-many-branches
        self, artist_name: str
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

        # Check each specified playlist/crate across all library paths
        for playlist_name in playlist_names:
            # Check all library paths for this playlist
            for check_libpath in self._get_all_database_paths():
                # Check regular crate first
                if await self._check_regular_crate_in_path(
                    playlist_name, artist_name, check_libpath
                ):
                    return True

                # Check smart crate if regular crate not found
                if await self._check_smart_crate_in_path(
                    playlist_name, artist_name, check_libpath
                ):
                    return True

        return False

    @staticmethod
    async def _has_tracks_in_entire_library(artist_name: str, libpath: str) -> bool:
        """Check for artist tracks in entire library"""
        logging.debug(
            "Serato artist query: searching for '%s' in libpath: %s", artist_name, libpath
        )
        db_reader = SeratoDatabaseV2Reader(libpath)
        await db_reader.loaddatabase()

        logging.debug("Serato database loaded: %d tracks found", len(db_reader.tracks))
        if len(db_reader.tracks) > 0:
            # Log first few artists for debugging
            sample_artists = [track.get("artist", "") for track in db_reader.tracks[:5]]
            logging.debug("Sample artists in database: %s", sample_artists)

        artist_name_lower = artist_name.lower()

        # Check for exact matches and log some details
        matches = [
            track
            for track in db_reader.tracks
            if track.get("artist", "").lower() == artist_name_lower
        ]
        logging.debug("Found %d exact matches for artist '%s'", len(matches), artist_name)

        return len(matches) > 0

    def on_serato_lib_button(self):
        """lib button clicked action"""
        connection_widgets = self.uihelp.find_tab_by_identifier(self.qwidget, "local_button")
        startdir = connection_widgets.local_dir_lineedit.text() or str(pathlib.Path.home())
        if libdir := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            connection_widgets.local_dir_lineedit.setText(libdir)

    def on_add_additional_lib_button(self):
        """add additional library button clicked action"""
        library_widgets = self.uihelp.find_tab_by_identifier(self.qwidget, "deck1_checkbox")
        startdir = str(pathlib.Path.home())
        if libdir := QFileDialog.getExistingDirectory(
            self.qwidget, "Select additional Serato library directory", startdir
        ):
            if current_text := library_widgets.additional_libs_textedit.toPlainText().strip():
                new_text = current_text + "\n" + libdir
            else:
                new_text = libdir
            library_widgets.additional_libs_textedit.setPlainText(new_text)

    def connect_settingsui(self, qwidget: "QWidget", uihelp: "nowplaying.uihelp.UIHelp"):
        """connect serato local dir button"""
        self.qwidget = qwidget
        self.uihelp = uihelp

        # Connect buttons from specific tabs
        connection_widgets = self.uihelp.find_tab_by_identifier(qwidget, "local_button")
        connection_widgets.local_dir_button.clicked.connect(self.on_serato_lib_button)

        library_widgets = self.uihelp.find_tab_by_identifier(qwidget, "deck1_checkbox")
        library_widgets.add_additional_lib_button.clicked.connect(
            self.on_add_additional_lib_button
        )

    def load_settingsui(self, qwidget: "QWidget"):
        """draw the plugin's settings page"""
        # Load connection tab settings
        self._load_connection_settings(qwidget)

        # Load library tab settings (including deck skip checkboxes)
        self._load_library_settings(qwidget)

        # Load query tab settings
        self._load_query_settings(qwidget)

    def _load_connection_settings(self, qwidget: "QWidget"):
        """Load connection tab settings"""
        connection_widgets = self.uihelp.find_tab_by_identifier(qwidget, "local_button")

        # Set radio buttons based on local/remote mode
        if self.config.cparser.value("serato/local", type=bool):
            connection_widgets.local_button.setChecked(True)
            connection_widgets.remote_button.setChecked(False)
        else:
            connection_widgets.local_button.setChecked(False)
            connection_widgets.remote_button.setChecked(True)

        # Set connection values
        connection_widgets.local_dir_lineedit.setText(self.config.cparser.value("serato/libpath"))
        connection_widgets.remote_url_lineedit.setText(self.config.cparser.value("serato/url"))
        connection_widgets.remote_poll_lineedit.setText(
            str(self.config.cparser.value("serato/interval"))
        )

    def _load_library_settings(self, qwidget: "QWidget"):
        """Load library tab settings including deck skip checkboxes"""
        library_widgets = self.uihelp.find_tab_by_identifier(qwidget, "deck1_checkbox")

        # Handle deck skip checkboxes
        deckskip = self.config.cparser.value("serato/deckskip")

        # Reset all checkboxes
        library_widgets.deck1_checkbox.setChecked(False)
        library_widgets.deck2_checkbox.setChecked(False)
        library_widgets.deck3_checkbox.setChecked(False)
        library_widgets.deck4_checkbox.setChecked(False)

        if deckskip:
            if not isinstance(deckskip, list):
                deckskip = list(deckskip)

            if "1" in deckskip:
                library_widgets.deck1_checkbox.setChecked(True)
            if "2" in deckskip:
                library_widgets.deck2_checkbox.setChecked(True)
            if "3" in deckskip:
                library_widgets.deck3_checkbox.setChecked(True)
            if "4" in deckskip:
                library_widgets.deck4_checkbox.setChecked(True)

        # Load additional library paths
        additional_paths = self.config.cparser.value("serato/additional_libpaths", defaultValue="")
        library_widgets.additional_libs_textedit.setPlainText(additional_paths)

    def _load_query_settings(self, qwidget: "QWidget"):
        """Load query tab settings"""
        query_widgets = self.uihelp.find_tab_by_identifier(qwidget, "serato_artist_scope_combo")

        # Set artist query scope
        scope = self.config.cparser.value(
            "serato/artist_query_scope", defaultValue="entire_library"
        )
        if scope == "selected_playlists":
            query_widgets.serato_artist_scope_combo.setCurrentText("Selected Playlists")
        else:
            query_widgets.serato_artist_scope_combo.setCurrentText("Entire Library")

        # Load selected playlists
        query_widgets.serato_playlists_lineedit.setText(
            self.config.cparser.value("serato/selected_playlists", defaultValue="")
        )

    def verify_settingsui(self, qwidget: "QWidget"):
        """Verify settings are valid"""
        connection_widgets = self.uihelp.find_tab_by_identifier(qwidget, "local_button")
        library_widgets = self.uihelp.find_tab_by_identifier(qwidget, "deck1_checkbox")

        # Validate remote URL if remote mode is selected
        if connection_widgets.remote_button.isChecked() and (
            "https://serato.com/playlists" not in connection_widgets.remote_url_lineedit.text()
            and "https://www.serato.com/playlists"
            not in connection_widgets.remote_url_lineedit.text()
            or len(connection_widgets.remote_url_lineedit.text()) < 30
        ):
            raise PluginVerifyError("Serato Live Playlist URL is invalid")

        # Validate local directory if local mode is selected
        if (
            connection_widgets.local_button.isChecked()
            and "_Serato_" not in connection_widgets.local_dir_lineedit.text()
        ):
            raise PluginVerifyError(
                r'Serato Library Path is required.  Should point to "\_Serato\_" folder'
            )

        if additional_paths := library_widgets.additional_libs_textedit.toPlainText().strip():
            for path in additional_paths.split("\n"):
                path = path.strip()
                if path and "_Serato_" not in path:
                    raise PluginVerifyError(
                        f'Additional library path "{path}" should point to a "_Serato_" folder'
                    )

    def save_settingsui(self, qwidget: "QWidget"):
        """Save settings from all tabs"""
        # Save connection tab settings
        self._save_connection_settings(qwidget)

        # Save library tab settings (including deck skip checkboxes)
        self._save_library_settings(qwidget)

        # Save query tab settings
        self._save_query_settings(qwidget)

    def _save_connection_settings(self, qwidget: "QWidget"):
        """Save connection tab settings"""
        connection_widgets = self.uihelp.find_tab_by_identifier(qwidget, "local_button")

        self.config.cparser.setValue(
            "serato/libpath", connection_widgets.local_dir_lineedit.text()
        )
        self.config.cparser.setValue("serato/local", connection_widgets.local_button.isChecked())
        self.config.cparser.setValue("serato/url", connection_widgets.remote_url_lineedit.text())
        self.config.cparser.setValue(
            "serato/interval", connection_widgets.remote_poll_lineedit.text()
        )

    def _save_library_settings(self, qwidget: "QWidget"):
        """Save library tab settings including deck skip checkboxes"""
        library_widgets = self.uihelp.find_tab_by_identifier(qwidget, "deck1_checkbox")

        # Save deck skip settings
        deckskip = []
        if library_widgets.deck1_checkbox.isChecked():
            deckskip.append("1")
        if library_widgets.deck2_checkbox.isChecked():
            deckskip.append("2")
        if library_widgets.deck3_checkbox.isChecked():
            deckskip.append("3")
        if library_widgets.deck4_checkbox.isChecked():
            deckskip.append("4")

        self.config.cparser.setValue("serato/deckskip", deckskip)

        # Save additional library paths
        additional_paths = library_widgets.additional_libs_textedit.toPlainText().strip()
        self.config.cparser.setValue("serato/additional_libpaths", additional_paths)

    def _save_query_settings(self, qwidget: "QWidget"):
        """Save query tab settings"""
        query_widgets = self.uihelp.find_tab_by_identifier(qwidget, "serato_artist_scope_combo")

        # Save artist query scope
        scope = (
            "selected_playlists"
            if query_widgets.serato_artist_scope_combo.currentText() == "Selected Playlists"
            else "entire_library"
        )
        self.config.cparser.setValue("serato/artist_query_scope", scope)

        # Save selected playlists
        self.config.cparser.setValue(
            "serato/selected_playlists", query_widgets.serato_playlists_lineedit.text()
        )

    def desc_settingsui(self, qwidget: "QWidget"):
        """description"""
        qwidget.setText(
            "This plugin provides support for Serato in both a local and remote capacity."
        )
