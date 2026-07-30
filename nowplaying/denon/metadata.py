#!/usr/bin/env python3
"""
StagelinQ Metadata Processor

This module handles track selection logic, audibility calculations, and metadata
extraction across all connected StagelinQ devices. It contains the business logic
for determining which track is "now playing" based on per-device deck state,
mixer signals, and configuration.
"""

import logging
import time
from typing import Any

from nowplaying.types import TrackMetadata

from .types import DenonDevice, DenonState

# Minimum effective volume considered "audible" (0.0-1.0 scale)
AUDIBLE_VOLUME_THRESHOLD = 0.1

# Decks assumed for devices whose model and DeckCount state are both unknown
DEFAULT_DECK_COUNT = 4

# Player numbers are 1-4; unknown players sort after all known ones
UNKNOWN_PLAYER_SORT_KEY = 99


class MetadataProcessor:
    """Determines the currently playing track from all connected devices' StateMaps"""

    def __init__(self, config):
        self.config = config
        # per-device state stores, keyed by the device's discovery token
        self._devices: dict[bytes, dict[str, Any]] = {}
        self._device_info: dict[bytes, DenonDevice] = {}
        # devices whose ExternalMixerVolume is being driven by a Denon
        # mixer or controller (a nonzero value has been observed)
        self._emv_active: set[bytes] = set()
        self._deck_play_times: dict[tuple[bytes, int], float] = {}
        self._mixmode = "newest"
        # player numbers already warned about as duplicated, to keep the
        # per-poll enumeration from spamming the warning
        self._warned_dup_players: set[int] = set()

    def register_device(self, device: DenonDevice) -> None:
        """Start tracking states for a connected device"""
        self._devices.setdefault(device.token, {})
        self._device_info[device.token] = device

    def unregister_device(self, token: bytes) -> None:
        """Stop tracking a disconnected device"""
        self._devices.pop(token, None)
        self._device_info.pop(token, None)
        self._emv_active.discard(token)
        for key in [key for key in self._deck_play_times if key[0] == token]:
            del self._deck_play_times[key]

    def update_state(self, token: bytes, state: DenonState) -> None:
        """Update a device's state store with new StagelinQ data"""
        states = self._devices.setdefault(token, {})
        states[state.name] = state.value

        # A mixerless player never updates ExternalMixerVolume (and may
        # report an initial 0), so the value is only trustworthy once a
        # Denon mixer/controller has demonstrably driven it nonzero
        if (
            token not in self._emv_active
            and "/ExternalMixerVolume" in state.name
            and self._extract_numeric_value(state.value) > 0.0
        ):
            self._emv_active.add(token)
            logging.info(
                "Denon mixer/controller is driving %s; using ExternalMixerVolume for audibility",
                self._device_name(token),
            )

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
        playing_decks = self._get_audible_playing_decks()
        if not playing_decks:
            return None

        selected_deck = self._select_deck_by_mix_mode(playing_decks)
        return self._build_track_metadata(selected_deck)

    def get_all_decks(self) -> list[dict]:
        """Snapshot of every loaded deck across all devices, regardless of play state.

        Groundwork for multi-deck displays: each entry carries the logical
        deck number, display label, track fields, play state, and audibility.
        deckskip is deliberately not applied - that is a now-playing
        selection concern; display consumers decide their own filtering.
        """
        decks = []
        for logical_deck, token, deck_idx in self._enumerate_logical_decks():
            if deck_info := self._deck_snapshot(logical_deck, token, deck_idx):
                decks.append(deck_info)
        return decks

    def _deck_snapshot(self, logical_deck: int, token: bytes, deck_idx: int) -> dict | None:
        """Build one deck's display snapshot, or None if nothing is loaded"""
        states = self._devices.get(token, {})
        prefix = f"/Engine/Deck{deck_idx}"
        artist = self._state_field(states, f"{prefix}/Track/ArtistName", "string")
        title = self._state_field(states, f"{prefix}/Track/SongName", "string")
        loaded_state = states.get(f"{prefix}/Track/SongLoaded")
        if not (artist or title or (isinstance(loaded_state, dict) and loaded_state.get("state"))):
            return None

        play_state = states.get(f"{prefix}/Play")
        deck_info = {
            "deck": logical_deck,
            "label": self._deck_label(
                {"token": token, "deck_idx": deck_idx, "deck": logical_deck}
            ),
            "artist": artist or "",
            "title": title or "",
            "playing": bool(isinstance(play_state, dict) and play_state.get("state") is True),
            "effective_volume": self._effective_volume(token, deck_idx),
        }
        if album := self._state_field(states, f"{prefix}/Track/AlbumName", "string"):
            deck_info["album"] = album
        if bpm := self._state_field(states, f"{prefix}/Track/BPM", "data"):
            deck_info["bpm"] = str(bpm)
        if genre := self._state_field(states, f"{prefix}/Track/Genre", "string"):
            deck_info["genre"] = genre
        return deck_info

    def _get_deck_skip_list(self) -> list[str]:
        """Get the list of logical deck numbers to skip"""
        deckskip = self.config.cparser.value("denon/deckskip")
        if deckskip and not isinstance(deckskip, list):
            deckskip = list(deckskip)
        return deckskip or []

    def _device_name(self, token: bytes) -> str:
        """Human-readable device name for logging, falling back to the token"""
        if info := self._device_info.get(token):
            return info.name
        return token.hex()[:8]

    def _player_number(self, token: bytes) -> int | None:
        """DJ-assigned player number (1-4) from /Client/Preferences/Player"""
        value = self._devices.get(token, {}).get("/Client/Preferences/Player")
        if isinstance(value, dict) and (number := value.get("string")):
            try:
                return int(number)
            except (ValueError, TypeError):
                return None
        return None

    def _deck_count(self, token: bytes) -> int:
        """Decks on a device: DeckCount state, then model table, then default"""
        value = self._devices.get(token, {}).get("/Engine/DeckCount")
        if isinstance(value, dict):
            if count := int(self._extract_numeric_value(value)):
                return count
        info = self._device_info.get(token)
        if info and info.model and info.model.deck_count:
            return info.model.deck_count
        return DEFAULT_DECK_COUNT

    def _enumerate_logical_decks(self) -> list[tuple[int, bytes, int]]:
        """Enumerate (logical deck number, token, device deck index) across devices.

        Devices sort by DJ-assigned player number (unknown numbers last,
        stable by token); each device then contributes its decks in order.
        A single 4-deck controller maps to logical decks 1-4 exactly as a
        single-device setup always has; two dual-layer players map to
        player 1 layers A/B -> decks 1/2 and player 2 layers A/B -> 3/4.
        """
        self._warn_duplicate_player_numbers()
        ordered = sorted(
            self._devices,
            key=lambda tok: (self._player_number(tok) or UNKNOWN_PLAYER_SORT_KEY, tok),
        )
        logical = []
        deck_number = 1
        for token in ordered:
            for deck_idx in range(1, self._deck_count(token) + 1):
                logical.append((deck_number, token, deck_idx))
                deck_number += 1
        return logical

    def _warn_duplicate_player_numbers(self) -> None:
        """Warn (once per composition) when devices share a player number.

        Deck numbering and deck labels are keyed by the DJ-assigned player
        number; two units left at the factory default of 1 get an arbitrary
        (token-based) ordering and indistinguishable labels.
        """
        assigned: dict[int, int] = {}
        for token in self._devices:
            if (number := self._player_number(token)) is not None:
                assigned[number] = assigned.get(number, 0) + 1
        duplicated = {number for number, count in assigned.items() if count > 1}

        if new_dups := duplicated - self._warned_dup_players:
            logging.warning(
                "Multiple Denon players report the same player number %s; "
                "deck numbering will use an arbitrary order and deck labels "
                "will repeat - assign a distinct player number to each unit",
                sorted(new_dups),
            )
        self._warned_dup_players = duplicated

    def _get_audible_playing_decks(self) -> list[dict]:
        """Find all currently playing and audible decks across all devices"""
        deckskip = self._get_deck_skip_list()
        playing_decks = []

        for logical_deck, token, deck_idx in self._enumerate_logical_decks():
            if str(logical_deck) in deckskip:
                continue

            if deck_info := self._analyze_deck(logical_deck, token, deck_idx):
                playing_decks.append(deck_info)
            elif self._deck_play_times.pop((token, deck_idx), None):
                logging.debug(
                    "Deck %d on %s no longer playing/audible",
                    logical_deck,
                    self._device_name(token),
                )

        return playing_decks

    def _analyze_deck(self, logical_deck: int, token: bytes, deck_idx: int) -> dict | None:
        """Analyze a single device deck to see if it's playing and audible"""
        states = self._devices.get(token, {})
        artist_data = states.get(f"/Engine/Deck{deck_idx}/Track/ArtistName")
        title_data = states.get(f"/Engine/Deck{deck_idx}/Track/SongName")
        play_state = states.get(f"/Engine/Deck{deck_idx}/Play")

        if artist_data is None or title_data is None or play_state is None:
            return None

        if not (isinstance(play_state, dict) and play_state.get("state") is True):
            return None

        if not (isinstance(artist_data, dict) and isinstance(title_data, dict)):
            return None

        effective_volume = self._effective_volume(token, deck_idx)
        if effective_volume <= AUDIBLE_VOLUME_THRESHOLD:  # Not audible enough
            return None

        # Track is playing and audible
        play_key = (token, deck_idx)
        if play_key not in self._deck_play_times:
            self._deck_play_times[play_key] = time.time()
            logging.debug(
                "Deck %d on %s started playing: %s - %s (volume %.2f)",
                logical_deck,
                self._device_name(token),
                artist_data.get("string", ""),
                title_data.get("string", ""),
                effective_volume,
            )

        return {
            "deck": logical_deck,
            "token": token,
            "deck_idx": deck_idx,
            "artist": artist_data.get("string", ""),
            "title": title_data.get("string", ""),
            "start_time": self._deck_play_times[play_key],
            "effective_volume": effective_volume,
        }

    def _effective_volume(self, token: bytes, deck_idx: int) -> float:
        """Per-deck audibility ladder.

        1. Raw mixer states (all-in-one controllers emit fader and
           crossfader in their own StateMap): combine them as before.
        2. ExternalMixerVolume, once a Denon mixer/controller has been
           observed driving it: the mixer computes fader x crossfader
           and pushes the result into the player's StateMap.
        3. No mixer signal at all (analog mixer, or nothing moved yet):
           assume the deck is audible.
        """
        states = self._devices.get(token, {})

        fader_data = states.get(f"/Mixer/CH{deck_idx}faderPosition")
        if fader_data is not None:
            fader_pos = self._extract_numeric_value(fader_data)
            crossfader_pos = self._extract_numeric_value(
                states.get("/Mixer/CrossfaderPosition", {}), default=0.5
            )
            return self._calculate_effective_volume(deck_idx, fader_pos, crossfader_pos)

        emv_data = states.get(f"/Engine/Deck{deck_idx}/ExternalMixerVolume")
        if token in self._emv_active and emv_data is not None:
            return self._extract_numeric_value(emv_data)

        return 1.0

    def _select_deck_by_mix_mode(self, playing_decks: list[dict]) -> dict:
        """Select which deck to use based on mix mode and volume, with deterministic tie-break"""
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
            "deck": self._deck_label(selected_deck),
        }

        states = self._devices.get(selected_deck["token"], {})
        deck_idx = selected_deck["deck_idx"]
        if album := self._state_field(states, f"/Engine/Deck{deck_idx}/Track/AlbumName", "string"):
            metadata["album"] = album
        if bpm := self._state_field(states, f"/Engine/Deck{deck_idx}/Track/BPM", "data"):
            metadata["bpm"] = str(bpm)
        if genre := self._state_field(states, f"/Engine/Deck{deck_idx}/Track/Genre", "string"):
            metadata["genre"] = genre
        return metadata

    def _deck_label(self, selected_deck: dict) -> str:
        """Human deck label: player number + layer letter when known, e.g. '2B'"""
        if player := self._player_number(selected_deck["token"]):
            layer = chr(ord("A") + selected_deck["deck_idx"] - 1)
            return f"{player}{layer}"
        return str(selected_deck["deck"])

    @staticmethod
    def _state_field(states: dict[str, Any], key: str, field: str) -> Any:
        """Read one field out of a state value dict, or None"""
        data = states.get(key)
        if isinstance(data, dict):
            return data.get(field) or None
        return None

    @staticmethod
    def _extract_numeric_value(data: Any, default: float = 0.0) -> float:
        """Extract numeric value from StagelinQ data dict"""
        if not isinstance(data, dict):
            return default

        # Try different possible numeric field names
        for field in ["data", "value", "number", "float", "string"]:
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
