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
from PySide6.QtWidgets import QFileDialog, QTabWidget  # pylint: disable=no-name-in-module

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

        # Additional database paths
        additional_paths = self.config.cparser.value("serato/additional_libpaths", defaultValue="")
        if additional_paths:
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
                for libpath in libpaths:
                    if await self._has_tracks_in_selected_playlists(artist_name, libpath):
                        return True
                return False

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
        return any(
            track.get("artist", "").lower() == artist_name_lower for track in db_reader.tracks
        )

    def on_serato_lib_button(self):
        """lib button clicked action"""
        local_dir_lineedit = self._find_widget_in_tabs(self.qwidget, "local_dir_lineedit")
        if not local_dir_lineedit:
            return

        startdir = local_dir_lineedit.text() or str(pathlib.Path.home())
        if libdir := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            local_dir_lineedit.setText(libdir)

    def on_add_additional_lib_button(self):
        """add additional library button clicked action"""
        additional_libs_textedit = self._find_widget_in_tabs(
            self.qwidget, "additional_libs_textedit"
        )
        if not additional_libs_textedit:
            return

        startdir = str(pathlib.Path.home())
        if libdir := QFileDialog.getExistingDirectory(
            self.qwidget, "Select additional Serato library directory", startdir
        ):
            # Add to existing paths in the text edit
            current_text = additional_libs_textedit.toPlainText().strip()
            if current_text:
                new_text = current_text + "\n" + libdir
            else:
                new_text = libdir
            additional_libs_textedit.setPlainText(new_text)

    def _find_widget_in_tabs(self, widget_container: "QWidget", widget_name: str):  # pylint: disable=no-self-use
        """Find a widget by name across tabs or in a single widget"""

        # If the container is a QTabWidget, search across all tabs
        if isinstance(widget_container, QTabWidget):
            for i in range(widget_container.count()):
                tab_widget = widget_container.widget(i)
                if hasattr(tab_widget, widget_name):
                    return getattr(tab_widget, widget_name)
            return None

        # If it's a regular widget, search directly
        if hasattr(widget_container, widget_name):
            return getattr(widget_container, widget_name)

        return None

    def connect_settingsui(self, qwidget: "QWidget", uihelp: "nowplaying.uihelp.UIHelp"):
        """connect serato local dir button"""
        self.qwidget = qwidget
        self.uihelp = uihelp

        # Find buttons across tabs and connect them
        local_dir_button = self._find_widget_in_tabs(qwidget, "local_dir_button")
        if local_dir_button:
            local_dir_button.clicked.connect(self.on_serato_lib_button)

        add_additional_lib_button = self._find_widget_in_tabs(qwidget, "add_additional_lib_button")
        if add_additional_lib_button:
            add_additional_lib_button.clicked.connect(self.on_add_additional_lib_button)

    def load_settingsui(self, qwidget: "QWidget"):  # pylint: disable=too-many-branches,too-many-statements
        """draw the plugin's settings page"""

        def handle_deckskip(cparser, plugin_self):
            deckskip = cparser.value("serato/deckskip")

            deck1_checkbox = plugin_self._find_widget_in_tabs(qwidget, "deck1_checkbox")  # pylint: disable=protected-access
            deck2_checkbox = plugin_self._find_widget_in_tabs(qwidget, "deck2_checkbox")  # pylint: disable=protected-access
            deck3_checkbox = plugin_self._find_widget_in_tabs(qwidget, "deck3_checkbox")  # pylint: disable=protected-access
            deck4_checkbox = plugin_self._find_widget_in_tabs(qwidget, "deck4_checkbox")  # pylint: disable=protected-access

            if deck1_checkbox:
                deck1_checkbox.setChecked(False)
            if deck2_checkbox:
                deck2_checkbox.setChecked(False)
            if deck3_checkbox:
                deck3_checkbox.setChecked(False)
            if deck4_checkbox:
                deck4_checkbox.setChecked(False)

            if not deckskip:
                return

            if not isinstance(deckskip, list):
                deckskip = list(deckskip)

            if "1" in deckskip and deck1_checkbox:
                deck1_checkbox.setChecked(True)

            if "2" in deckskip and deck2_checkbox:
                deck2_checkbox.setChecked(True)

            if "3" in deckskip and deck3_checkbox:
                deck3_checkbox.setChecked(True)

            if "4" in deckskip and deck4_checkbox:
                deck4_checkbox.setChecked(True)

        # Connection tab elements
        local_button = self._find_widget_in_tabs(qwidget, "local_button")
        remote_button = self._find_widget_in_tabs(qwidget, "remote_button")
        local_dir_lineedit = self._find_widget_in_tabs(qwidget, "local_dir_lineedit")
        remote_url_lineedit = self._find_widget_in_tabs(qwidget, "remote_url_lineedit")
        remote_poll_lineedit = self._find_widget_in_tabs(qwidget, "remote_poll_lineedit")

        if self.config.cparser.value("serato/local", type=bool):
            if local_button:
                local_button.setChecked(True)
            if remote_button:
                remote_button.setChecked(False)
        else:
            if local_button:
                local_button.setChecked(False)
            if remote_button:
                remote_button.setChecked(True)

        if local_dir_lineedit:
            local_dir_lineedit.setText(self.config.cparser.value("serato/libpath"))
        if remote_url_lineedit:
            remote_url_lineedit.setText(self.config.cparser.value("serato/url"))
        if remote_poll_lineedit:
            remote_poll_lineedit.setText(str(self.config.cparser.value("serato/interval")))

        handle_deckskip(self.config.cparser, self)

        # Query tab elements
        serato_artist_scope_combo = self._find_widget_in_tabs(qwidget, "serato_artist_scope_combo")
        serato_playlists_lineedit = self._find_widget_in_tabs(qwidget, "serato_playlists_lineedit")

        # Set artist query scope
        scope = self.config.cparser.value(
            "serato/artist_query_scope", defaultValue="entire_library"
        )
        if serato_artist_scope_combo:
            if scope == "selected_playlists":
                serato_artist_scope_combo.setCurrentText("Selected Playlists")
            else:
                serato_artist_scope_combo.setCurrentText("Entire Library")

        # Load selected playlists
        if serato_playlists_lineedit:
            serato_playlists_lineedit.setText(
                self.config.cparser.value("serato/selected_playlists", defaultValue="")
            )

        # Library tab elements
        additional_libs_textedit = self._find_widget_in_tabs(qwidget, "additional_libs_textedit")

        # Load additional library paths
        if additional_libs_textedit:
            additional_paths = self.config.cparser.value(
                "serato/additional_libpaths", defaultValue=""
            )
            additional_libs_textedit.setPlainText(additional_paths)

    def verify_settingsui(self, qwidget: "QWidget"):
        """no verification to do"""
        remote_button = self._find_widget_in_tabs(qwidget, "remote_button")
        remote_url_lineedit = self._find_widget_in_tabs(qwidget, "remote_url_lineedit")
        local_button = self._find_widget_in_tabs(qwidget, "local_button")
        local_dir_lineedit = self._find_widget_in_tabs(qwidget, "local_dir_lineedit")
        additional_libs_textedit = self._find_widget_in_tabs(qwidget, "additional_libs_textedit")

        if (  # pylint: disable=too-many-boolean-expressions
            remote_button
            and remote_button.isChecked()
            and remote_url_lineedit
            and (
                "https://serato.com/playlists" not in remote_url_lineedit.text()
                and "https://www.serato.com/playlists" not in remote_url_lineedit.text()
                or len(remote_url_lineedit.text()) < 30
            )
        ):
            raise PluginVerifyError("Serato Live Playlist URL is invalid")

        if (
            local_button
            and local_button.isChecked()
            and local_dir_lineedit
            and ("_Serato_" not in local_dir_lineedit.text())
        ):
            raise PluginVerifyError(
                r'Serato Library Path is required.  Should point to "\_Serato\_" folder'
            )

        # Validate additional library paths
        if additional_libs_textedit:
            additional_paths = additional_libs_textedit.toPlainText().strip()
            if additional_paths:
                for path in additional_paths.split("\n"):
                    path = path.strip()
                    if path and "_Serato_" not in path:
                        raise PluginVerifyError(
                            f'Additional library path "{path}" should point to a "_Serato_" folder'
                        )

    def save_settingsui(self, qwidget: "QWidget"):  # pylint: disable=too-many-locals
        """take the settings page and save it"""
        # Connection tab elements
        local_dir_lineedit = self._find_widget_in_tabs(qwidget, "local_dir_lineedit")
        local_button = self._find_widget_in_tabs(qwidget, "local_button")
        remote_url_lineedit = self._find_widget_in_tabs(qwidget, "remote_url_lineedit")
        remote_poll_lineedit = self._find_widget_in_tabs(qwidget, "remote_poll_lineedit")

        if local_dir_lineedit:
            self.config.cparser.setValue("serato/libpath", local_dir_lineedit.text())
        if local_button:
            self.config.cparser.setValue("serato/local", local_button.isChecked())
        if remote_url_lineedit:
            self.config.cparser.setValue("serato/url", remote_url_lineedit.text())
        if remote_poll_lineedit:
            self.config.cparser.setValue("serato/interval", remote_poll_lineedit.text())

        # Library tab elements
        deck1_checkbox = self._find_widget_in_tabs(qwidget, "deck1_checkbox")
        deck2_checkbox = self._find_widget_in_tabs(qwidget, "deck2_checkbox")
        deck3_checkbox = self._find_widget_in_tabs(qwidget, "deck3_checkbox")
        deck4_checkbox = self._find_widget_in_tabs(qwidget, "deck4_checkbox")
        additional_libs_textedit = self._find_widget_in_tabs(qwidget, "additional_libs_textedit")

        deckskip = []
        if deck1_checkbox and deck1_checkbox.isChecked():
            deckskip.append("1")
        if deck2_checkbox and deck2_checkbox.isChecked():
            deckskip.append("2")
        if deck3_checkbox and deck3_checkbox.isChecked():
            deckskip.append("3")
        if deck4_checkbox and deck4_checkbox.isChecked():
            deckskip.append("4")

        self.config.cparser.setValue("serato/deckskip", deckskip)

        # Query tab elements
        serato_artist_scope_combo = self._find_widget_in_tabs(qwidget, "serato_artist_scope_combo")
        serato_playlists_lineedit = self._find_widget_in_tabs(qwidget, "serato_playlists_lineedit")

        # Save artist query scope
        if serato_artist_scope_combo:
            scope = (
                "selected_playlists"
                if serato_artist_scope_combo.currentText() == "Selected Playlists"
                else "entire_library"
            )
            self.config.cparser.setValue("serato/artist_query_scope", scope)

        # Save selected playlists
        if serato_playlists_lineedit:
            self.config.cparser.setValue(
                "serato/selected_playlists", serato_playlists_lineedit.text()
            )

        # Save additional library paths
        if additional_libs_textedit:
            additional_paths = additional_libs_textedit.toPlainText().strip()
            self.config.cparser.setValue("serato/additional_libpaths", additional_paths)

    def desc_settingsui(self, qwidget: "QWidget"):
        """description"""
        qwidget.setText(
            "This plugin provides support for Serato in both a local and remote capacity."
        )
