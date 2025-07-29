#!/usr/bin/env python3
"""
StagelinQ Metadata Processor

This module handles track selection logic, fader calculations, and metadata extraction.
It contains all the business logic for determining which track is "now playing"
based on mixer state and configuration.
"""

import time
from typing import Any

from nowplaying.types import TrackMetadata

from .types import DenonState

# Minimum effective volume considered "audible" (0.0-1.0 scale)
AUDIBLE_VOLUME_THRESHOLD = 0.1



class MetadataProcessor:
    """Processes StagelinQ state data to determine currently playing track"""

    def __init__(self, config):
        self.config = config
        self.current_metadata: dict[str, dict[str, Any]] = {}
        self._deck_play_times: dict[int, float] = {}
        self._mixmode = "newest"

    def update_state(self, state: DenonState) -> None:
        """Update internal state with new StagelinQ data"""
        self.current_metadata[state.name] = state.value

    def set_mixmode(self, mixmode: str) -> str:
        """Set the mix mode"""
        if mixmode in {"newest", "oldest"}:
            self._mixmode = mixmode
        return self._mixmode

    def get_mixmode(self) -> str:
        """Get the current mix mode"""
        return self._mixmode

    def get_playing_track(self) -> TrackMetadata | None:
        """Get the currently playing track metadata"""
        if not self.current_metadata:
            return None

        playing_decks = self._get_audible_playing_decks()
        if not playing_decks:
            return None

        selected_deck = self._select_deck_by_mix_mode(playing_decks)
        return self._build_track_metadata(selected_deck)

    def _get_deck_skip_list(self) -> list[str]:
        """Get the list of decks to skip"""
        deckskip = self.config.cparser.value("denon/deckskip")
        if deckskip and not isinstance(deckskip, list):
            deckskip = list(deckskip)
        return deckskip or []

    def _get_audible_playing_decks(self) -> list[dict]:
        """Find all currently playing and audible decks"""
        deckskip = self._get_deck_skip_list()
        playing_decks = []
        crossfader_pos = self._get_crossfader_position()

        for deck_num in range(1, 5):
            if str(deck_num) in deckskip:
                continue

            if deck_info := self._analyze_deck(deck_num, crossfader_pos):
                playing_decks.append(deck_info)
            elif deck_num in self._deck_play_times:
                # Deck stopped playing, remove from tracking
                del self._deck_play_times[deck_num]

        return playing_decks

    def _analyze_deck(self, deck_num: int, crossfader_pos: float) -> dict | None:
        """Analyze a single deck to see if it's playing and audible"""
        state_keys = self._get_deck_state_keys(deck_num)

        # Check if required metadata exists
        if any(key not in self.current_metadata for key in state_keys[:3]):
            return None

        play_state = self.current_metadata.get(state_keys[2], {})
        if not (isinstance(play_state, dict) and play_state.get("state") is True):
            return None

        # Get track metadata
        artist_data = self.current_metadata.get(state_keys[0], {})
        title_data = self.current_metadata.get(state_keys[1], {})
        fader_data = self.current_metadata.get(state_keys[3], {})

        if not (isinstance(artist_data, dict) and isinstance(title_data, dict)):
            return None

        # Calculate effective volume
        fader_pos = self._extract_numeric_value(fader_data)
        effective_volume = self._calculate_effective_volume(deck_num, fader_pos, crossfader_pos)

        if effective_volume <= AUDIBLE_VOLUME_THRESHOLD:  # Not audible enough
            return None

        # Track is playing and audible
        if deck_num not in self._deck_play_times:
            self._deck_play_times[deck_num] = time.time()

        return {
            "deck": deck_num,
            "artist": artist_data.get("string", ""),
            "title": title_data.get("string", ""),
            "start_time": self._deck_play_times[deck_num],
            "effective_volume": effective_volume,
        }

    @staticmethod
    def _get_deck_state_keys(deck_num: int) -> list[str]:
        """Get the state keys for a specific deck"""
        return [
            f"/Engine/Deck{deck_num}/Track/ArtistName",
            f"/Engine/Deck{deck_num}/Track/SongName",
            f"/Engine/Deck{deck_num}/Play",
            f"/Mixer/CH{deck_num}faderPosition",
        ]

    def _select_deck_by_mix_mode(self, playing_decks: list[dict]) -> dict:
        """Select which deck to use based on mix mode and volume, with deterministic tie-breaking"""
        if len(playing_decks) == 1:
            return playing_decks[0]

        # Multiple audible decks - use volume-weighted selection
        max_volume = max(d["effective_volume"] for d in playing_decks)
        loudest_decks = [d for d in playing_decks if d["effective_volume"] >= max_volume * 0.8]

        if self._mixmode == "newest":
            # Find decks with the latest start_time
            max_start_time = max(d["start_time"] for d in loudest_decks)
            newest_decks = [d for d in loudest_decks if d["start_time"] == max_start_time]
            # Tie-breaker: lowest deck number
            return min(newest_decks, key=lambda d: d["deck"])
        # Find decks with the earliest start_time
        min_start_time = min(d["start_time"] for d in loudest_decks)
        oldest_decks = [d for d in loudest_decks if d["start_time"] == min_start_time]
        # Tie-breaker: lowest deck number
        return min(oldest_decks, key=lambda d: d["deck"])

    def _build_track_metadata(self, selected_deck: dict) -> TrackMetadata:
        """Build the final track metadata dictionary"""
        metadata: TrackMetadata = {
            "artist": selected_deck["artist"],
            "title": selected_deck["title"],
        }

        deck_num = selected_deck["deck"]
        self._add_optional_metadata(metadata, deck_num)
        return metadata

    def _add_optional_metadata(self, metadata: dict, deck_num: int) -> None:
        """Add optional metadata fields if available"""
        optional_fields = [
            (f"/Engine/Deck{deck_num}/Track/AlbumName", "album", "string"),
            (f"/Engine/Deck{deck_num}/Track/BPM", "bpm", "data"),
            (f"/Engine/Deck{deck_num}/Track/Genre", "genre", "string"),
        ]

        for key, field_name, data_key in optional_fields:
            if key in self.current_metadata:
                data = self.current_metadata[key]
                if isinstance(data, dict) and data.get(data_key):
                    value = data.get(data_key, "")
                    if field_name == "bpm":
                        value = str(value)
                    metadata[field_name] = value

    def _get_crossfader_position(self) -> float:
        """Get crossfader position (0.0 = full left, 0.5 = center, 1.0 = full right)"""
        crossfader_data = self.current_metadata.get("/Mixer/CrossfaderPosition", {})
        return self._extract_numeric_value(crossfader_data, default=0.5)  # Default to center

    @staticmethod
    def _extract_numeric_value(data: dict, default: float = 0.0) -> float:
        """Extract numeric value from StagelinQ data dict"""
        if not isinstance(data, dict):
            return default

        # Try different possible numeric field names
        for field in ["data", "value", "number", "float"]:
            if field in data:
                try:
                    return float(data[field])
                except (ValueError, TypeError):
                    continue

        return default

    @staticmethod
    def _calculate_effective_volume(
        deck_num: int, fader_pos: float, crossfader_pos: float
    ) -> float:
        """Calculate effective volume considering channel fader and crossfader position"""
        if fader_pos <= 0.0:
            return 0.0

        # Simple crossfader logic:
        # Decks 1&3 are typically on left side (crossfader 0.0)
        # Decks 2&4 are typically on right side (crossfader 1.0)
        # When crossfader is in center (0.5), both sides are audible

        if deck_num in {1, 3}:  # Left side decks
            if crossfader_pos > 0.8:  # Crossfader strongly to right
                crossfader_factor = 0.0
            elif crossfader_pos <= 0.5:  # Crossfader center or left - left side audible
                crossfader_factor = 1.0
            else:  # Crossfader transitioning to right (0.5 < pos <= 0.8)
                crossfader_factor = 1.0 - ((crossfader_pos - 0.5) / 0.3)
        elif crossfader_pos < 0.2:  # Crossfader strongly to left
            crossfader_factor = 0.0
        elif crossfader_pos >= 0.5:  # Crossfader center or right - right side audible
            crossfader_factor = 1.0
        else:  # Crossfader transitioning from left (0.2 <= pos < 0.5)
            crossfader_factor = (crossfader_pos - 0.2) / 0.3

        return fader_pos * crossfader_factor
