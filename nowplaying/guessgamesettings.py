#!/usr/bin/env python3
"""Guess Game Settings UI integration"""

import logging
import sys

from PySide6.QtWidgets import (  # pylint: disable=import-error,no-name-in-module
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

import nowplaying.guessgame


class GuessGameSettings:
    """Settings UI handler for Guess Game"""

    def __init__(self):
        self.widget = None
        self.uihelp = None

    def connect(self, uihelp, widget):
        """Connect guess game settings UI"""
        self.widget = widget
        self.uihelp = uihelp

        # Connect Clear Leaderboards button
        clear_button = widget.findChild(QPushButton, "clear_leaderboards_button")
        clear_button.clicked.connect(self.clear_leaderboards)

    def load(self, config, widget, uihelp):  # pylint: disable=unused-argument
        """Load guess game settings into UI"""
        self.widget = widget

        # Set platform-specific info label
        info_label = widget.findChild(QLabel, "info_label")
        if sys.platform == "darwin":
            info_text = "**To enable/disable the Guess Game, use the menu bar menu**"
        elif sys.platform == "win32":
            info_text = "**To enable/disable the Guess Game, right-click the system tray icon**"
        else:  # Linux and others
            info_text = "**To enable/disable the Guess Game, click the system tray icon**"
        info_label.setText(info_text)

        # Commands
        widget.findChild(QLineEdit, "command_lineedit").setText(
            config.cparser.value("guessgame/command", defaultValue="guess")
        )
        widget.findChild(QLineEdit, "statscommand_lineedit").setText(
            config.cparser.value("guessgame/statscommand", defaultValue="mypoints")
        )

        # Game settings
        widget.findChild(QSpinBox, "maxduration_spinbox").setValue(
            config.cparser.value("guessgame/maxduration", type=int, defaultValue=120)
        )
        widget.findChild(QSpinBox, "leaderboard_size_spinbox").setValue(
            config.cparser.value("guessgame/leaderboard_size", type=int, defaultValue=10)
        )
        widget.findChild(QDoubleSpinBox, "difficulty_threshold_spinbox").setValue(
            config.cparser.value("guessgame/difficulty_threshold", type=float, defaultValue=0.70)
        )

        # Solve mode
        solve_mode = config.cparser.value("guessgame/solve_mode", defaultValue="separate_solves")
        solve_mode_index = {"separate_solves": 0, "either": 1, "both_required": 2}.get(
            solve_mode, 0
        )
        widget.findChild(QComboBox, "solve_mode_combobox").setCurrentIndex(solve_mode_index)

        # Scoring
        widget.findChild(QSpinBox, "points_common_letter_spinbox").setValue(
            config.cparser.value("guessgame/points_common_letter", type=int, defaultValue=1)
        )
        widget.findChild(QSpinBox, "points_uncommon_letter_spinbox").setValue(
            config.cparser.value("guessgame/points_uncommon_letter", type=int, defaultValue=2)
        )
        widget.findChild(QSpinBox, "points_rare_letter_spinbox").setValue(
            config.cparser.value("guessgame/points_rare_letter", type=int, defaultValue=3)
        )
        widget.findChild(QSpinBox, "points_correct_word_spinbox").setValue(
            config.cparser.value("guessgame/points_correct_word", type=int, defaultValue=10)
        )
        widget.findChild(QSpinBox, "points_wrong_word_spinbox").setValue(
            config.cparser.value("guessgame/points_wrong_word", type=int, defaultValue=-1)
        )
        widget.findChild(QSpinBox, "points_complete_solve_spinbox").setValue(
            config.cparser.value("guessgame/points_complete_solve", type=int, defaultValue=100)
        )
        widget.findChild(QSpinBox, "points_first_solver_spinbox").setValue(
            config.cparser.value("guessgame/points_first_solver", type=int, defaultValue=50)
        )

        # Advanced options
        widget.findChild(QCheckBox, "auto_reveal_common_words_checkbox").setChecked(
            config.cparser.value(
                "guessgame/auto_reveal_common_words", type=bool, defaultValue=False
            )
        )
        widget.findChild(QCheckBox, "time_bonus_enabled_checkbox").setChecked(
            config.cparser.value("guessgame/time_bonus_enabled", type=bool, defaultValue=False)
        )

        logging.debug("Guess game settings loaded")

    @staticmethod
    def save(config, widget, subprocesses):  # pylint: disable=unused-argument
        """Save guess game settings from UI to config"""

        # Commands
        config.cparser.setValue(
            "guessgame/command", widget.findChild(QLineEdit, "command_lineedit").text().strip()
        )
        config.cparser.setValue(
            "guessgame/statscommand",
            widget.findChild(QLineEdit, "statscommand_lineedit").text().strip(),
        )

        # Game settings
        config.cparser.setValue(
            "guessgame/maxduration", widget.findChild(QSpinBox, "maxduration_spinbox").value()
        )
        config.cparser.setValue(
            "guessgame/leaderboard_size",
            widget.findChild(QSpinBox, "leaderboard_size_spinbox").value(),
        )
        config.cparser.setValue(
            "guessgame/difficulty_threshold",
            widget.findChild(QDoubleSpinBox, "difficulty_threshold_spinbox").value(),
        )

        # Solve mode
        solve_mode_map = ["separate_solves", "either", "both_required"]
        config.cparser.setValue(
            "guessgame/solve_mode",
            solve_mode_map[widget.findChild(QComboBox, "solve_mode_combobox").currentIndex()],
        )

        # Scoring
        config.cparser.setValue(
            "guessgame/points_common_letter",
            widget.findChild(QSpinBox, "points_common_letter_spinbox").value(),
        )
        config.cparser.setValue(
            "guessgame/points_uncommon_letter",
            widget.findChild(QSpinBox, "points_uncommon_letter_spinbox").value(),
        )
        config.cparser.setValue(
            "guessgame/points_rare_letter",
            widget.findChild(QSpinBox, "points_rare_letter_spinbox").value(),
        )
        config.cparser.setValue(
            "guessgame/points_correct_word",
            widget.findChild(QSpinBox, "points_correct_word_spinbox").value(),
        )
        config.cparser.setValue(
            "guessgame/points_wrong_word",
            widget.findChild(QSpinBox, "points_wrong_word_spinbox").value(),
        )
        config.cparser.setValue(
            "guessgame/points_complete_solve",
            widget.findChild(QSpinBox, "points_complete_solve_spinbox").value(),
        )
        config.cparser.setValue(
            "guessgame/points_first_solver",
            widget.findChild(QSpinBox, "points_first_solver_spinbox").value(),
        )

        # Advanced options
        config.cparser.setValue(
            "guessgame/auto_reveal_common_words",
            widget.findChild(QCheckBox, "auto_reveal_common_words_checkbox").isChecked(),
        )
        config.cparser.setValue(
            "guessgame/time_bonus_enabled",
            widget.findChild(QCheckBox, "time_bonus_enabled_checkbox").isChecked(),
        )

        logging.info("Guess game settings saved")

    def update_guessgame_settings(self, config):  # pylint: disable=unused-argument,no-self-use
        """Update guess game settings (placeholder for future dynamic updates)"""
        # This could be used to validate settings or trigger reloads
        logging.debug("Guess game settings updated")

    def clear_leaderboards(self):
        """Handle Clear Leaderboards button click"""
        # Show confirmation dialog
        reply = QMessageBox.question(
            self.widget,
            "Clear Leaderboards",
            "Are you sure you want to clear ALL leaderboard data?\n\n"
            "This will delete all user scores and cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            # Create temporary guessgame instance to access database
            config = self.uihelp.config if self.uihelp else None
            guessgame = nowplaying.guessgame.GuessGame(config=config)

            # Clear leaderboards (synchronous)
            try:
                success = guessgame.clear_leaderboards()

                if success:
                    QMessageBox.information(
                        self.widget, "Success", "All leaderboards have been cleared."
                    )
                    logging.info("User cleared all leaderboards via settings UI")
                else:
                    QMessageBox.warning(
                        self.widget,
                        "Error",
                        "Failed to clear leaderboards. Check logs for details.",
                    )
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.error("Exception while clearing leaderboards: %s", error)
                QMessageBox.warning(
                    self.widget,
                    "Error",
                    f"Failed to clear leaderboards: {error}",
                )
