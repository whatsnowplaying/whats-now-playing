#!/usr/bin/env python3
"""
Shared data types and constants for StagelinQ protocol

This module contains all the data classes, constants, and exceptions
used throughout the Denon StagelinQ implementation.
"""

from dataclasses import dataclass
from typing import Any

# Protocol constants
DISCOVERY_PORT = 51337
DISCOVERY_MAGIC = b"airD"
SMAA_MAGIC = b"smaa"

# Message IDs
MSG_SERVICE_ANNOUNCEMENT = 0x00000000
MSG_REFERENCE = 0x00000001
MSG_SERVICES_REQUEST = 0x00000002

# Device roles derived from discovery software names
ROLE_PLAYER = "player"
ROLE_CONTROLLER = "controller"  # all-in-one: engine decks + mixer in one StateMap
ROLE_MIXER = "mixer"
ROLE_OTHER = "other"


@dataclass(frozen=True)
class DenonModel:
    """Known hardware model information keyed by discovery software name"""

    model: str
    role: str
    deck_count: int


# Software name codes observed in StagelinQ discovery announcements,
# from the Engine OS firmware assignment files and the StageLinq
# reference implementations
DEVICE_MODELS: dict[str, DenonModel] = {
    "JP07": DenonModel("SC5000", ROLE_PLAYER, 2),
    "JP08": DenonModel("SC5000M", ROLE_PLAYER, 2),
    "JP13": DenonModel("SC6000", ROLE_PLAYER, 2),
    "JP14": DenonModel("SC6000M", ROLE_PLAYER, 2),
    "JC11": DenonModel("PRIME 4", ROLE_CONTROLLER, 4),
    "JC16": DenonModel("PRIME 2", ROLE_CONTROLLER, 2),
    "JP11": DenonModel("PRIME GO", ROLE_CONTROLLER, 2),
    "JP20": DenonModel("SC LIVE 2", ROLE_CONTROLLER, 2),
    "JP21": DenonModel("SC LIVE 4", ROLE_CONTROLLER, 4),
    "NH08": DenonModel("MIXSTREAM PRO", ROLE_CONTROLLER, 2),
    "NH09": DenonModel("MIXSTREAM PRO+", ROLE_CONTROLLER, 2),
    "NH10": DenonModel("MIXSTREAM PRO GO", ROLE_CONTROLLER, 2),
    "JM08": DenonModel("DN-X1800 Prime", ROLE_MIXER, 0),
    "JM10": DenonModel("DN-X1850 Prime", ROLE_MIXER, 0),
    "JC20": DenonModel("LC6000", ROLE_OTHER, 0),
}

# Non-hardware StagelinQ announcers that never offer usable services
# (Engine OS runs several of these alongside the actual player software;
# SoundSwitchEmbedded and friends are covered by the SoundSwitch prefix)
IGNORED_SOFTWARE_NAMES = {"OfflineAnalyzer"}
IGNORED_SOFTWARE_PREFIXES = ("SoundSwitch", "Resolume", "SSS")

# State message magic bytes
STATE_SUBSCRIBE_MAGIC = b"\x00\x00\x07\xd2"
STATE_EMIT_MAGIC = b"\x00\x00\x00\x00"


@dataclass
class DenonDevice:
    """Information about a discovered StagelinQ device"""

    ipaddr: str
    port: int
    name: str
    software_name: str
    software_version: str
    token: bytes

    @property
    def model(self) -> DenonModel | None:
        """Known hardware model for this device's software name, if any"""
        return DEVICE_MODELS.get(self.software_name)

    def is_connectable(self) -> bool:
        """True if this device is worth a StateMap connection.

        Players and controllers carry track state. Mixers refuse inbound
        connections and instead push fader data into the players' own
        StateMaps (ExternalMixerVolume), so they are never connected.
        Known non-hardware announcers are skipped; unknown software names
        are assumed to be future hardware and tried.
        """
        if model := DEVICE_MODELS.get(self.software_name):
            return model.role in {ROLE_PLAYER, ROLE_CONTROLLER}
        if self.software_name in IGNORED_SOFTWARE_NAMES:
            return False
        return not self.software_name.startswith(IGNORED_SOFTWARE_PREFIXES)


@dataclass
class DenonService:
    """Information about a service provided by a device"""

    name: str
    port: int


@dataclass
class DenonState:
    """State value update from StateMap service"""

    name: str
    value: dict[str, Any]


class StagelinqError(Exception):
    """Base exception for StagelinQ protocol errors"""
