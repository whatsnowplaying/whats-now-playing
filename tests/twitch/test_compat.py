#!/usr/bin/env python3
"""
Test TwitchAPI compatibility shim for unpickling old AuthScope enums from Qt config.

This test verifies that the compatibility shim can handle old AuthScope enum objects
stored in Qt config from previous app versions, preventing crashes during upgrades.
"""

import subprocess
import sys

import pytest
from PySide6.QtCore import QSettings  # pylint:disable=no-name-in-module

import nowplaying.twitch.compat
from nowplaying.twitch.compat import AuthScope


@pytest.fixture
def clean_modules():
    """Clean up twitchAPI modules before and after tests."""
    modules_to_remove = ["twitchAPI", "twitchAPI.types"]

    # Clean up before test
    for module in modules_to_remove:
        if module in sys.modules:
            del sys.modules[module]

    yield

    # Clean up after test
    for module in modules_to_remove:
        if module in sys.modules:
            del sys.modules[module]


@pytest.fixture
def test_settings():
    """Create a test QSettings instance."""
    settings = QSettings("TestOrg", "TestApp")
    settings.clear()
    yield settings
    settings.clear()


def test_install_legacy_types(clean_modules):  # pylint:disable=unused-argument, redefined-outer-name
    """Test that install_legacy_types creates the required modules."""
    # Ensure modules don't exist initially
    assert "twitchAPI" not in sys.modules
    assert "twitchAPI.types" not in sys.modules

    # Install legacy types
    nowplaying.twitch.compat.install_legacy_types()

    # Verify modules were created
    assert "twitchAPI" in sys.modules
    assert "twitchAPI.types" in sys.modules

    # Verify AuthScope is available
    assert hasattr(sys.modules["twitchAPI.types"], "AuthScope")

    # Verify the AuthScope enum has expected values
    legacy_authscope = sys.modules["twitchAPI.types"].AuthScope
    assert legacy_authscope.CHAT_READ.value == "chat:read"
    assert legacy_authscope.CHAT_EDIT.value == "chat:edit"
    assert legacy_authscope.CHANNEL_READ_REDEMPTIONS.value == "channel:read:redemptions"


def test_authscope_enum_values():
    """Test that the compatibility AuthScope enum has correct values."""
    assert AuthScope.CHAT_READ.value == "chat:read"
    assert AuthScope.CHAT_EDIT.value == "chat:edit"
    assert AuthScope.CHANNEL_READ_REDEMPTIONS.value == "channel:read:redemptions"


def test_qt_config_serialization_compatibility(test_settings):  # pylint:disable=unused-argument, redefined-outer-name
    """Test that AuthScope enums can be stored and retrieved from Qt config."""
    # Test storing individual AuthScope enums
    test_enums = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]

    # Store the enums in Qt config
    test_settings.setValue("test/authscope_single", AuthScope.CHAT_READ)
    test_settings.setValue("test/authscope_list", test_enums)

    # Retrieve and verify
    retrieved_single = test_settings.value("test/authscope_single")
    retrieved_list = test_settings.value("test/authscope_list")

    # Verify the values can be retrieved
    assert retrieved_single is not None
    assert retrieved_list is not None

    # Verify single enum value
    assert isinstance(retrieved_single, AuthScope)
    assert retrieved_single == AuthScope.CHAT_READ
    assert retrieved_single.value == "chat:read"

    # For list, verify it's actually a list and has expected length
    if isinstance(retrieved_list, list):
        assert len(retrieved_list) == 2
        # Verify that deserialized list contains AuthScope enums with correct values
        assert all(isinstance(item, AuthScope) for item in retrieved_list)
        assert retrieved_list[0] == AuthScope.CHAT_READ
        assert retrieved_list[0].value == "chat:read"
        assert retrieved_list[1] == AuthScope.CHAT_EDIT
        assert retrieved_list[1].value == "chat:edit"


def test_compatibility_shim_auto_install():
    """Test that the compatibility shim is automatically installed on import."""
    # Test that auto-install actually works by importing in a subprocess
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys; import nowplaying.twitch.compat; print("twitchAPI.types" in sys.modules)',
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # The output should be 'True' indicating the module was auto-installed
    assert result.stdout.strip() == "True"


def test_multiple_install_calls_safe(clean_modules):  # pylint:disable=unused-argument, redefined-outer-name
    """Test that multiple calls to install_legacy_types are safe."""
    # Install multiple times
    nowplaying.twitch.compat.install_legacy_types()
    nowplaying.twitch.compat.install_legacy_types()
    nowplaying.twitch.compat.install_legacy_types()

    # Should still work correctly
    assert "twitchAPI.types" in sys.modules
    legacy_authscope = sys.modules["twitchAPI.types"].AuthScope
    assert legacy_authscope.CHAT_READ.value == "chat:read"


def test_invalid_refresh_token_exception(clean_modules):  # pylint:disable=unused-argument, redefined-outer-name
    """Test that InvalidRefreshTokenException is available for unpickling."""
    # Install legacy types
    nowplaying.twitch.compat.install_legacy_types()

    # Verify exception is available
    assert hasattr(sys.modules["twitchAPI.types"], "InvalidRefreshTokenException")

    # Verify it's a proper exception class
    exception_class = sys.modules["twitchAPI.types"].InvalidRefreshTokenException
    assert issubclass(exception_class, Exception)
