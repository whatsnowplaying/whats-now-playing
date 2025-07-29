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
