#!/usr/bin/env python3
"""
StagelinQ Protocol Handler

This module handles the low-level StagelinQ protocol parsing, message formatting,
and protocol constants. It encapsulates all the protocol-specific details.
"""

import json
import logging
import os
import struct

from .types import (
    DISCOVERY_MAGIC,
    MSG_REFERENCE,
    MSG_SERVICE_ANNOUNCEMENT,
    MSG_SERVICES_REQUEST,
    SMAA_MAGIC,
    STATE_EMIT_MAGIC,
    STATE_SUBSCRIBE_MAGIC,
    DenonDevice,
    DenonService,
    DenonState,
    StagelinqError,
)


class StagelinqProtocol:
    """Handles StagelinQ protocol message parsing and formatting"""

    @staticmethod
    def generate_token() -> bytes:
        """Generate a random 16-byte token (MSb must be 0)"""
        token = bytearray(os.urandom(16))
        # Critical: Ensure MSb is 0 as per protocol requirement
        token[0] = token[0] & 0x7F
        return bytes(token)

    @staticmethod
    def pack_utf16_string(string: str) -> bytes:
        """Pack a string as UTF-16 BigEndian with length prefix"""
        encoded = string.encode("utf-16be")
        return struct.pack(">I", len(encoded)) + encoded

    @staticmethod
    def unpack_utf16_string(data: bytes, offset: int = 0) -> tuple[str, int]:
        """Unpack a UTF-16 BigEndian string with length prefix"""
        if len(data) < offset + 4:
            raise StagelinqError("Insufficient data for string length")

        length: int = struct.unpack(">I", data[offset : offset + 4])[0]
        if len(data) < offset + 4 + length:
            raise StagelinqError("Insufficient data for string content")

        string_data = data[offset + 4 : offset + 4 + length]
        decoded = string_data.decode("utf-16be")
        return decoded, offset + 4 + length

    @staticmethod
    def create_discovery_message(token: bytes, device_name: str, software_version: str) -> bytes:
        """Create a discovery announcement message"""
        message = DISCOVERY_MAGIC  # "airD"
        message += token
        message += StagelinqProtocol.pack_utf16_string(device_name)
        message += StagelinqProtocol.pack_utf16_string("DISCOVERER_HOWDY_")
        message += StagelinqProtocol.pack_utf16_string("WhatsNowPlaying")
        message += StagelinqProtocol.pack_utf16_string(software_version)
        message += struct.pack(">H", 0)  # Port (0 for client)
        return message

    @staticmethod
    def parse_discovery_message(data: bytes, ipaddr: str) -> DenonDevice | None:
        """Parse a discovery message from UDP broadcast"""
        if len(data) < 4 or data[:4] != DISCOVERY_MAGIC:
            return None

        try:
            offset = 4

            # Read token (16 bytes)
            if len(data) < offset + 16:
                return None
            token = data[offset : offset + 16]
            offset += 16

            # Read device name
            device_name, offset = StagelinqProtocol.unpack_utf16_string(data, offset)

            # Read action
            action, offset = StagelinqProtocol.unpack_utf16_string(data, offset)

            # Read software name
            software_name, offset = StagelinqProtocol.unpack_utf16_string(data, offset)

            # Read software version
            software_version, offset = StagelinqProtocol.unpack_utf16_string(data, offset)

            # Read port
            if len(data) < offset + 2:
                return None
            port = struct.unpack(">H", data[offset : offset + 2])[0]

            # Only return devices that are present
            if action == "DISCOVERER_HOWDY_":
                return DenonDevice(
                    ipaddr=ipaddr,
                    port=port,
                    name=device_name,
                    software_name=software_name,
                    software_version=software_version,
                    token=token,
                )

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Error parsing discovery message: %s", err)

        return None

    @staticmethod
    def create_services_request(token: bytes) -> bytes:
        """Create a services request message"""
        return struct.pack(">I", MSG_SERVICES_REQUEST) + token

    @staticmethod
    def create_reference_message(our_token: bytes, target_token: bytes) -> bytes:
        """Create a reference message to keep connection alive"""
        return struct.pack(">I", MSG_REFERENCE) + our_token + target_token + struct.pack(">q", 0)

    @staticmethod
    def create_service_announcement(token: bytes, service_name: str, port: int) -> bytes:
        """Create a service announcement message"""
        return (
            struct.pack(">I", MSG_SERVICE_ANNOUNCEMENT)
            + token
            + StagelinqProtocol.pack_utf16_string(service_name)
            + struct.pack(">H", port)
        )

    @staticmethod
    def create_state_subscription(state_path: str) -> bytes:
        """Create a state subscription message"""
        content = SMAA_MAGIC + STATE_SUBSCRIBE_MAGIC
        content += StagelinqProtocol.pack_utf16_string(state_path)
        content += struct.pack(">I", 0)  # Interval
        return struct.pack(">I", len(content)) + content

    @staticmethod
    def parse_service_announcement(
        data: bytes, offset: int = 0
    ) -> tuple[DenonService | None, int]:
        """Parse a service announcement message"""
        try:
            # Skip token (16 bytes)
            offset += 16

            # Read service name
            service_name, offset = StagelinqProtocol.unpack_utf16_string(data, offset)

            # Read port
            if len(data) < offset + 2:
                return None, offset
            port = struct.unpack(">H", data[offset : offset + 2])[0]
            offset += 2

            return DenonService(name=service_name, port=port), offset

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Error parsing service announcement: %s", err)
            return None, offset

    @staticmethod
    def parse_state_emit_message(data: bytes) -> DenonState | None:
        """Parse a state emit message"""
        try:
            # Check for SMAA magic and state emit magic
            if len(data) < 8:
                return None

            if data[:4] != SMAA_MAGIC or data[4:8] != STATE_EMIT_MAGIC:
                return None

            offset = 8

            # Read state name
            name, offset = StagelinqProtocol.unpack_utf16_string(data, offset)

            # Read JSON value
            json_str, offset = StagelinqProtocol.unpack_utf16_string(data, offset)

            # Parse JSON
            value = json.loads(json_str)

            return DenonState(name=name, value=value)

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Error parsing state emit message: %s", err)
            return None
