#!/usr/bin/env python3
"""MusicBrainz settings plugin for recognition system configuration"""

from typing import TYPE_CHECKING

from nowplaying.plugin import WNPBasePlugin

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
    from PySide6.QtWidgets import QWidget

    import nowplaying.config


class Plugin(WNPBasePlugin):
    """Settings handler for MusicBrainz recognition system"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "MusicBrainz"

    def defaults(self, qsettings: "QSettings"):
        """Set default configuration values"""
        qsettings.setValue("musicbrainz/enabled", True)
        qsettings.setValue("musicbrainz/fallback", False)
        qsettings.setValue("musicbrainz/emailaddress", "")
        qsettings.setValue("musicbrainz/strict_album_matching", True)

        # Website preferences (moved from acoustidmb)
        qsettings.setValue("musicbrainz/websites", False)
        for website in ["bandcamp", "homepage", "lastfm", "musicbrainz"]:
            qsettings.setValue(f"musicbrainz/{website}", False)
        qsettings.setValue("musicbrainz/discogs", True)

    def load_settingsui(self, qwidget: "QWidget"):
        """Load settings into UI"""
        qwidget.musicbrainz_checkbox.setChecked(
            self.config.cparser.value("musicbrainz/enabled", type=bool, defaultValue=True)
        )
        qwidget.mb_fallback_checkbox.setChecked(
            self.config.cparser.value("musicbrainz/fallback", type=bool, defaultValue=False)
        )
        qwidget.emailaddress_lineedit.setText(
            self.config.cparser.value("musicbrainz/emailaddress", defaultValue="")
        )
        qwidget.strict_album_checkbox.setChecked(
            self.config.cparser.value(
                "musicbrainz/strict_album_matching", type=bool, defaultValue=True
            )
        )

        qwidget.websites_checkbox.setChecked(
            self.config.cparser.value("musicbrainz/websites", type=bool, defaultValue=False)
        )

        for website in [
            "bandcamp",
            "homepage",
            "lastfm",
            "musicbrainz",
            "discogs",
        ]:
            guiattr = getattr(qwidget, f"ws_{website}_checkbox")
            default_value = website == "discogs"  # Only discogs defaults to True
            guiattr.setChecked(
                self.config.cparser.value(
                    f"musicbrainz/{website}", type=bool, defaultValue=default_value
                )
            )

    def save_settingsui(self, qwidget: "QWidget"):
        """Save settings from UI"""
        self.config.cparser.setValue(
            "musicbrainz/enabled", qwidget.musicbrainz_checkbox.isChecked()
        )
        self.config.cparser.setValue(
            "musicbrainz/fallback", qwidget.mb_fallback_checkbox.isChecked()
        )
        self.config.cparser.setValue(
            "musicbrainz/emailaddress", qwidget.emailaddress_lineedit.text()
        )
        self.config.cparser.setValue(
            "musicbrainz/strict_album_matching", qwidget.strict_album_checkbox.isChecked()
        )

        self.config.cparser.setValue("musicbrainz/websites", qwidget.websites_checkbox.isChecked())

        for website in [
            "bandcamp",
            "homepage",
            "lastfm",
            "musicbrainz",
            "discogs",
        ]:
            guiattr = getattr(qwidget, f"ws_{website}_checkbox")
            self.config.cparser.setValue(f"musicbrainz/{website}", guiattr.isChecked())

    def verify_settingsui(self, qwidget: "QWidget"):
        """Verify settings are valid"""
        # Email is recommended but not required
        if (
            qwidget.musicbrainz_checkbox.isChecked()
            and qwidget.emailaddress_lineedit.text().strip() == ""
        ):
            # Could add a warning but not an error since we have a default
            pass
        return True

    def connect_settingsui(self, qwidget: "QWidget", uihelp):
        """Connect UI signal handlers"""
        # Enable/disable website checkboxes based on main websites checkbox
        qwidget.musicbrainz_checkbox.toggled.connect(qwidget.mb_fallback_checkbox.setEnabled)
        qwidget.musicbrainz_checkbox.toggled.connect(qwidget.emailaddress_lineedit.setEnabled)
        qwidget.musicbrainz_checkbox.toggled.connect(qwidget.emailaddress_label.setEnabled)
        qwidget.musicbrainz_checkbox.toggled.connect(qwidget.strict_album_checkbox.setEnabled)
        qwidget.musicbrainz_checkbox.toggled.connect(qwidget.websites_checkbox.setEnabled)

        # Website checkboxes depend on both musicbrainz and websites being enabled
        def update_website_checkboxes():
            enabled = (
                qwidget.musicbrainz_checkbox.isChecked() and qwidget.websites_checkbox.isChecked()
            )
            for website in ["bandcamp", "homepage", "lastfm", "musicbrainz", "discogs"]:
                checkbox = getattr(qwidget, f"ws_{website}_checkbox")
                checkbox.setEnabled(enabled)

        qwidget.websites_checkbox.toggled.connect(update_website_checkboxes)
        qwidget.musicbrainz_checkbox.toggled.connect(update_website_checkboxes)

    @staticmethod
    def desc_settingsui(qwidget: "QWidget"):
        """Description for settings UI"""
        qwidget.setText(
            "MusicBrainz provides comprehensive music metadata including artist information, "
            "album details, and website links. It serves as the backbone for music recognition "
            "and metadata enhancement throughout the application."
        )
