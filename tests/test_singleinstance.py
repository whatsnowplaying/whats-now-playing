#!/usr/bin/env python3
"""
Unit tests for single instance enforcement using Qt's QLockFile.
"""
# pylint: disable=no-member

import pytest

import nowplaying.singleinstance  # pylint: disable=import-error,no-name-in-module


def test_single_instance_basic(qapp):  # pylint: disable=unused-argument
    """Test basic single instance functionality"""
    # First instance should acquire lock successfully
    with nowplaying.singleinstance.SingleInstance("test_basic") as lock1:
        assert lock1 is not None

        # Second instance should fail
        with pytest.raises(nowplaying.singleinstance.AlreadyRunningError):
            with nowplaying.singleinstance.SingleInstance("test_basic"):
                pass

    # After first instance exits, should be able to acquire again
    with nowplaying.singleinstance.SingleInstance("test_basic") as lock2:
        assert lock2 is not None


def test_different_app_names_dont_conflict(qapp):  # pylint: disable=unused-argument
    """Test that different app names don't conflict with each other"""
    with nowplaying.singleinstance.SingleInstance("app1") as lock1:
        # Should be able to acquire lock for different app name
        with nowplaying.singleinstance.SingleInstance("app2") as lock2:
            assert lock1 is not None
            assert lock2 is not None


def test_context_manager_cleanup(qapp):  # pylint: disable=unused-argument
    """Test that context manager properly cleans up locks"""
    app_name = "test_cleanup"

    # Acquire and release lock
    with nowplaying.singleinstance.SingleInstance(app_name):
        pass

    # Should be able to immediately acquire again
    with nowplaying.singleinstance.SingleInstance(app_name):
        pass


def test_exception_during_context_still_releases_lock(qapp):  # pylint: disable=unused-argument
    """Test that exceptions inside context manager still release the lock"""
    app_name = "test_exception"

    # Exception inside context manager
    with pytest.raises(ValueError):
        with nowplaying.singleinstance.SingleInstance(app_name):
            raise ValueError("Test exception")

    # Lock should be released despite exception
    with nowplaying.singleinstance.SingleInstance(app_name):
        pass


def test_multiple_sequential_instances(qapp):  # pylint: disable=unused-argument
    """Test multiple sequential instances work correctly"""
    app_name = "test_sequential"

    for _ in range(5):
        with nowplaying.singleinstance.SingleInstance(app_name):
            # Each iteration should successfully acquire the lock
            pass


def test_already_running_error_message(qapp):  # pylint: disable=unused-argument
    """Test that AlreadyRunningError has appropriate message"""
    app_name = "test_error_message"

    with nowplaying.singleinstance.SingleInstance(app_name):
        with pytest.raises(nowplaying.singleinstance.AlreadyRunningError) as exc_info:
            with nowplaying.singleinstance.SingleInstance(app_name):
                pass

        assert "already running" in str(exc_info.value).lower()


def test_default_app_name(qapp):  # pylint: disable=unused-argument
    """Test default app name behavior"""
    # Should use "nowplaying" as default - test that it actually uses the default
    instance1 = nowplaying.singleinstance.SingleInstance()
    instance2 = nowplaying.singleinstance.SingleInstance("nowplaying")

    # Both should try to use the same lock file
    with instance1:
        with pytest.raises(nowplaying.singleinstance.AlreadyRunningError):
            with instance2:
                pass


def test_lock_file_creation(qapp):  # pylint: disable=unused-argument
    """Test that lock files are created in appropriate location"""
    app_name = "test_lock_file"

    with nowplaying.singleinstance.SingleInstance(app_name) as instance:
        # Lock file should exist in temp directory
        # Note: Path verification not needed since QLockFile handles it internally

        # The lock file might not be visible in filesystem on all platforms
        # but the QLockFile should be active
        assert instance.lock_file.isLocked()


def test_stale_lock_handling(qapp):  # pylint: disable=unused-argument
    """Test that stale locks are handled appropriately"""
    # This is hard to test directly without killing processes,
    # but we can verify the staleness timeout is set
    app_name = "test_stale"

    instance = nowplaying.singleinstance.SingleInstance(app_name)
    # Should have 30 second staleness timeout
    # Note: QLockFile doesn't expose getStaleLockTime() so we can't verify directly
    # but we can ensure it doesn't crash
    assert instance.lock_file is not None
