#!/usr/bin/env python3
"""Filter utilities for title stripping"""

from __future__ import annotations

import base64
import re
import time

# Default filters that are enabled by default (common unwanted phrases)
SIMPLE_FILTER_DEFAULT_ON = [
    "1080p",
    "480p",
    "4k",
    "720p",
    "ce",
    "clean version",
    "clean",
    "cs",
    "dirty",
    "explicit version",
    "explicit",
    "hd",
    "high quality",
    "hq",
    "lyric video",
    "lyrics video",
    "music video",
    "official audio",
    "official music video",
    "official trailer",
    "official video",
    "remaster",
    "remastered",
]

# Additional filters that are available but off by default
SIMPLE_FILTER_DEFAULT_OFF = [
    "acoustic version",
    "acoustic",
    "anniversary edition",
    "bonus track",
    "club mix",
    "deluxe edition",
    "demo version",
    "demo",
    "extended mix",
    "extended version",
    "instrumental",
    "live version",
    "live",
    "radio edit",
    "radio version",
    "remix",
    "special edition",
    "studio version",
    "unreleased",
]

# Combined list of all predefined available phrases
SIMPLE_FILTER_PHRASES = SIMPLE_FILTER_DEFAULT_ON + SIMPLE_FILTER_DEFAULT_OFF

# Global cache for FilterManager to avoid recreation on every titlestripper call
_cached_filter_manager: FilterManager | None = None
_cache_last_load_date: int = 0


class FilterManager:
    """Manages simple filter phrase selection and regex generation"""

    def __init__(self):
        # {phrase: {"dash": bool, "paren": bool, "bracket": bool}}
        self.phrase_format_selections: dict[str, dict[str, bool]] = {}
        # Set to track custom phrases added by user
        self.custom_phrases: set[str] = set()
        # Cached compiled patterns for performance
        self._compiled_patterns: list[re.Pattern] = []
        self._patterns_dirty = True
        # Complex regex patterns (from manual regex entries)
        self.regex_patterns: list[re.Pattern] = []

    def set_phrase_format(self, phrase: str, format_type: str, enabled: bool):
        """Set whether a phrase should be filtered in a specific format"""
        if phrase not in self.phrase_format_selections:
            self.phrase_format_selections[phrase] = {
                "dash": False,
                "paren": False,
                "bracket": False,
                "plain": False,
            }
        self.phrase_format_selections[phrase][format_type] = enabled
        self._patterns_dirty = True

    def get_phrase_format(self, phrase: str, format_type: str) -> bool:
        """Get whether a phrase is enabled for a specific format"""
        return self.phrase_format_selections.get(phrase, {}).get(format_type, False)

    def add_custom_phrase(  # pylint: disable=too-many-return-statements
        self, phrase: str
    ) -> tuple[bool, str]:
        """Add a custom phrase. Returns (success, error_message)"""
        if not phrase or not phrase.strip():
            return False, "Phrase cannot be empty"

        phrase = phrase.strip().lower()

        # Validate phrase content
        if len(phrase) < 2:
            return False, "Phrase must be at least 2 characters"

        if len(phrase) > 50:
            return False, "Phrase must be 50 characters or less"

        # Check for invalid characters that would break regex
        invalid_chars = set(phrase) & {
            "(",
            ")",
            "[",
            "]",
            "\\",
            "^",
            "$",
            "|",
            "*",
            "+",
            "?",
            "{",
            "}",
        }
        if invalid_chars:
            return False, f"Phrase contains invalid characters: {', '.join(sorted(invalid_chars))}"

        # Check if phrase already exists in predefined phrases (case insensitive)
        if phrase in [p.lower() for p in SIMPLE_FILTER_PHRASES]:
            return False, "This phrase already exists in the predefined list"

        # Check if phrase already exists in custom phrases
        if phrase in self.custom_phrases:
            return False, "This custom phrase already exists"

        self.custom_phrases.add(phrase)
        # Initialize with all formats disabled by default
        self.phrase_format_selections[phrase] = {
            "dash": False,
            "paren": False,
            "bracket": False,
            "plain": False,
        }
        self._patterns_dirty = True
        return True, ""

    def remove_custom_phrase(self, phrase: str) -> bool:
        """Remove a custom phrase. Returns True if removed, False if not found or predefined"""
        phrase = phrase.strip().lower()

        # Cannot remove predefined phrases
        if phrase in SIMPLE_FILTER_PHRASES:
            return False

        if phrase in self.custom_phrases:
            self.custom_phrases.remove(phrase)
            self.phrase_format_selections.pop(phrase, None)
            self._patterns_dirty = True
            return True

        return False

    def get_all_phrases(self) -> list[str]:
        """Get all phrases (predefined + custom) sorted alphabetically"""
        all_phrases = list(SIMPLE_FILTER_PHRASES) + list(self.custom_phrases)
        return sorted(all_phrases)

    def is_custom_phrase(self, phrase: str) -> bool:
        """Check if a phrase is a custom phrase (user-added)"""
        return phrase in self.custom_phrases

    def generate_regex_patterns(self) -> list[str]:
        """Generate regex patterns from current selections"""
        patterns = []

        # Group phrases by format type
        dash_phrases = []
        paren_phrases = []
        bracket_phrases = []

        for phrase, formats in self.phrase_format_selections.items():
            if formats.get("dash", False):
                dash_phrases.append(phrase)
            if formats.get("paren", False):
                paren_phrases.append(phrase)
            if formats.get("bracket", False):
                bracket_phrases.append(phrase)

        # Generate patterns for each format
        if dash_phrases:
            self._create_regex_pattern(dash_phrases, patterns, " - (", ")$")
        if paren_phrases:
            self._create_regex_pattern(paren_phrases, patterns, " \\((", ")\\)")
        if bracket_phrases:
            self._create_regex_pattern(bracket_phrases, patterns, " \\[(", ")\\]")
        return patterns

    @staticmethod
    def _create_regex_pattern(phrases: list, patterns: list, first: str, last: str):
        # Sort by length (longest first) for proper regex precedence
        phrases.sort(key=len, reverse=True)
        escaped_phrases = [re.escape(phrase) for phrase in phrases]
        joinlist = "|".join(escaped_phrases)
        patterns.append(f"{first}{joinlist}{last}")

    def get_compiled_regex_list(self) -> list[re.Pattern]:
        """Get compiled regex patterns with caching for performance"""
        if self._patterns_dirty or not self._compiled_patterns:
            patterns = self.generate_regex_patterns()
            self._compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            self._patterns_dirty = False
        return self._compiled_patterns

    def set_regex_patterns(self, patterns: list[re.Pattern]):
        """Set the complex regex patterns"""
        self.regex_patterns = patterns.copy()

    def get_regex_patterns(self) -> list[re.Pattern]:
        """Get the complex regex patterns"""
        return self.regex_patterns.copy()

    def apply_all_filters(self, title: str | None) -> str | None:
        """Apply both simple phrase filters and complex regex patterns to a title"""
        if not title:
            return None

        # Apply per-phrase filtering based on format selections
        for phrase, formats in self.phrase_format_selections.items():
            # Apply plain string matching first (fastest)
            if formats.get("plain", False):
                title_lower = title.lower()
                phrase_lower = phrase.lower()
                if phrase_lower in title_lower:
                    start_idx = title_lower.find(phrase_lower)
                    if start_idx != -1:
                        title = title[:start_idx] + title[start_idx + len(phrase) :]

        # Apply formatted patterns using cached compiled regex
        for pattern in self.get_compiled_regex_list():
            title = pattern.sub("", title)

        # Apply complex regex patterns
        for pattern in self.regex_patterns:
            title = pattern.sub("", title)

        return title

    def load_from_config(self, config):
        """Load selections from Qt config"""
        self.phrase_format_selections.clear()
        self.custom_phrases.clear()
        self._patterns_dirty = True

        # Check if we have any simple filter config at all
        has_simple_config = any(key.startswith("simple_filter") for key in config.allKeys())

        # If no simple filter config exists, set up defaults
        if not has_simple_config:
            # Enable all formats for default-on phrases
            for phrase in SIMPLE_FILTER_DEFAULT_ON:
                self.set_phrase_format(phrase, "dash", True)
                self.set_phrase_format(phrase, "paren", True)
                self.set_phrase_format(phrase, "bracket", True)
            return

        # Load custom phrases first
        for configitem in config.allKeys():
            if configitem.startswith("simple_filter_custom/"):
                # Format: simple_filter_custom/{base64_encoded_phrase}
                base64_phrase = configitem.replace("simple_filter_custom/", "")
                try:
                    phrase = base64.b64decode(base64_phrase.encode("utf-8")).decode("utf-8")
                    if config.value(configitem, type=bool):
                        self.custom_phrases.add(phrase)
                except ValueError:
                    # Skip invalid base64 entries
                    continue

        # Load phrase format selections
        for configitem in config.allKeys():
            if configitem.startswith("simple_filter/"):
                # Format: simple_filter/{base64_encoded_phrase}_{format}
                remaining = configitem.replace("simple_filter/", "")
                parts = remaining.split("_")
                if len(parts) == 2:
                    base64_phrase = parts[0]
                    format_type = parts[1]
                    try:
                        phrase = base64.b64decode(base64_phrase.encode("utf-8")).decode("utf-8")
                        # Allow both predefined and custom phrases
                        if (
                            phrase in SIMPLE_FILTER_PHRASES or phrase in self.custom_phrases
                        ) and format_type in [
                            "dash",
                            "paren",
                            "bracket",
                            "plain",
                        ]:
                            enabled = config.value(configitem, type=bool)
                            self.set_phrase_format(phrase, format_type, enabled)
                    except ValueError:
                        # Skip invalid base64 entries
                        continue

    def reset_to_defaults(self):
        """Reset to default filter configuration"""
        self.phrase_format_selections.clear()
        self.custom_phrases.clear()
        self._patterns_dirty = True

        # Enable all formats for default-on phrases
        for phrase in SIMPLE_FILTER_DEFAULT_ON:
            self.set_phrase_format(phrase, "dash", True)
            self.set_phrase_format(phrase, "paren", True)
            self.set_phrase_format(phrase, "bracket", True)

    def save_to_config(self, config):
        """Save selections to Qt config"""
        # Clear existing simple filter settings
        for configitem in list(config.allKeys()):
            if configitem.startswith("simple_filter/") or configitem.startswith(
                "simple_filter_custom/"
            ):
                config.remove(configitem)

        # Save custom phrases
        for phrase in self.custom_phrases:
            base64_phrase = base64.b64encode(phrase.encode("utf-8")).decode("utf-8")
            config_key = f"simple_filter_custom/{base64_phrase}"
            config.setValue(config_key, True)

        # Save current selections
        for phrase, formats in self.phrase_format_selections.items():
            base64_phrase = base64.b64encode(phrase.encode("utf-8")).decode("utf-8")
            for format_type, enabled in formats.items():
                if enabled:
                    config_key = f"simple_filter/{base64_phrase}_{format_type}"
                    config.setValue(config_key, True)

        # Update lastsavedate to invalidate cached FilterManager
        config.setValue("settings/lastsavedate", time.strftime("%Y%m%d%H%M%S"))


def clear_titlestripper_cache():
    """Clear the global FilterManager cache for testing"""
    global _cached_filter_manager, _cache_last_load_date  # pylint: disable=global-statement
    _cached_filter_manager = None
    _cache_last_load_date = 0


def titlestripper_with_manager(
    filter_manager: FilterManager, title: str | None = None
) -> str | None:
    """
    Apply filtering using a FilterManager instance directly.

    This is used by the settings UI for testing and by titlestripper() internally.

    Args:
        filter_manager: FilterManager instance with configured filters
        title: The title to strip

    Returns:
        Stripped title or None if input was None
    """
    if not title:
        return None

    return filter_manager.apply_all_filters(title)


def titlestripper(config: "nowplaying.config.ConfigFile", title: str | None = None) -> str | None:
    """
    Unified title stripping function that handles all filtering logic internally.

    This is the ONLY function that should be used for title stripping throughout
    the codebase. It centralizes all decision-making about which filters to apply.

    Args:
        config: Config object (required)
        title: The title to strip

    Returns:
        Stripped title or None if input was None
    """
    global _cached_filter_manager, _cache_last_load_date  # pylint: disable=global-statement

    if not title:
        return None

    # Check if title stripping is enabled in config
    if not config.cparser.value("settings/stripextras", type=bool):
        return title  # Return unchanged if stripping is disabled

    # Sync config to ensure we have latest data
    config.cparser.sync()

    # Check if config has changed since last load
    current_save_date = config.cparser.value("settings/lastsavedate", type=int) or 0

    # Use cached FilterManager or create new one
    if _cached_filter_manager is None:
        _cached_filter_manager = FilterManager()

    if _cache_last_load_date < current_save_date or current_save_date == 0:
        # Reload from config when it has changed
        _cached_filter_manager.load_from_config(config.cparser)
        # Also load complex regex patterns from config
        _cached_filter_manager.set_regex_patterns(config.getregexlist())
        _cache_last_load_date = current_save_date

    # Use the FilterManager to apply all filters
    return titlestripper_with_manager(_cached_filter_manager, title)
