#!/usr/bin/env python3
"""test discord functionality"""
# pylint: disable=protected-access,redefined-outer-name,no-member

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import discord
import pypresence

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.processes.discordbot
from nowplaying.processes.discordbot import DiscordSupport, DiscordClients  # pylint: disable=no-name-in-module


# Skip decorators for integration tests requiring Discord credentials
skip_no_discord_bot_token = pytest.mark.skipif(
    not os.environ.get("DISCORD_BOT_TOKEN"),
    reason="DISCORD_BOT_TOKEN environment variable not set",
)

skip_no_discord_client_id = pytest.mark.skipif(
    not os.environ.get("DISCORD_CLIENT_ID"),
    reason="DISCORD_CLIENT_ID environment variable not set",
)


# DiscordClients dataclass tests
def test_discord_clients_initialization():
    """Test DiscordClients default initialization"""
    clients = DiscordClients()
    assert clients.bot is None
    assert clients.ipc is None


def test_discord_clients_initialization_with_values():
    """Test DiscordClients initialization with values"""
    mock_bot = MagicMock(spec=discord.Client)
    mock_ipc = MagicMock(spec=pypresence.AioPresence)

    clients = DiscordClients(bot=mock_bot, ipc=mock_ipc)
    assert clients.bot is mock_bot
    assert clients.ipc is mock_ipc


def test_discord_clients_assignment():
    """Test assignment of client values"""
    clients = DiscordClients()
    mock_bot = MagicMock(spec=discord.Client)
    mock_ipc = MagicMock(spec=pypresence.AioPresence)

    clients.bot = mock_bot
    clients.ipc = mock_ipc

    assert clients.bot is mock_bot
    assert clients.ipc is mock_ipc


def test_discord_clients_none_assignment():
    """Test setting clients back to None"""
    mock_bot = MagicMock(spec=discord.Client)
    mock_ipc = MagicMock(spec=pypresence.AioPresence)

    clients = DiscordClients(bot=mock_bot, ipc=mock_ipc)
    clients.bot = None
    clients.ipc = None

    assert clients.bot is None
    assert clients.ipc is None


# Test fixtures
@pytest.fixture
def mock_stopevent():
    """Create a mock stop event"""
    event = MagicMock(spec=asyncio.Event)
    event.is_set.return_value = False
    return event


@pytest.fixture
def discord_support(bootstrap, mock_stopevent):
    """Create DiscordSupport instance with real config and mocked stopevent"""
    with patch("signal.signal"):
        return DiscordSupport(config=bootstrap, stopevent=mock_stopevent)


# DiscordSupport initialization tests
def test_discord_support_initialization(bootstrap, mock_stopevent):
    """Test DiscordSupport initialization"""
    with patch("signal.signal") as mock_signal:
        support = DiscordSupport(config=bootstrap, stopevent=mock_stopevent)

        assert support.config is bootstrap
        assert support.stopevent is mock_stopevent
        assert isinstance(support.clients, DiscordClients)
        assert support.clients.bot is None
        assert support.clients.ipc is None
        assert isinstance(support.tasks, set)
        assert len(support.tasks) == 0
        mock_signal.assert_called_once()


def test_discord_support_initialization_none_params():
    """Test DiscordSupport initialization with None parameters"""
    with patch("signal.signal"):
        support = DiscordSupport(config=None, stopevent=None)

        assert support.config is None
        assert support.stopevent is None
        assert isinstance(support.clients, DiscordClients)


# Bot client setup tests
@pytest.mark.asyncio
async def test_setup_bot_client_no_config():
    """Test bot client setup with no config"""
    support = DiscordSupport(config=None, stopevent=None)
    await support._setup_bot_client()
    assert support.clients.bot is None


@pytest.mark.asyncio
async def test_setup_bot_client_no_token(discord_support):
    """Test bot client setup with no token"""
    # bootstrap config has no discord token by default
    await discord_support._setup_bot_client()
    assert discord_support.clients.bot is None


@pytest.mark.asyncio
async def test_setup_bot_client_already_exists(discord_support):
    """Test bot client setup when client already exists"""
    discord_support.config.cparser.setValue("discord/token", "fake_token")
    discord_support.clients.bot = MagicMock(spec=discord.Client)

    await discord_support._setup_bot_client()
    # Should not create a new client since one already exists
    assert discord_support.clients.bot is not None


@pytest.mark.asyncio
async def test_setup_bot_client_exception(discord_support):
    """Test bot client setup with exception during creation"""
    discord_support.config.cparser.setValue("discord/token", "fake_token")

    with patch("discord.Intents.default"), patch("discord.Client") as mock_client_class:
        mock_client_class.side_effect = Exception("Connection failed")

        await discord_support._setup_bot_client()
        assert discord_support.clients.bot is None


# IPC client setup tests
@pytest.mark.asyncio
async def test_setup_ipc_client_no_config():
    """Test IPC client setup with no config"""
    support = DiscordSupport(config=None, stopevent=None)
    await support._setup_ipc_client()
    assert support.clients.ipc is None


@pytest.mark.asyncio
async def test_setup_ipc_client_no_client_id(discord_support):
    """Test IPC client setup with no client ID"""
    # bootstrap config has no discord client ID by default
    await discord_support._setup_ipc_client()
    assert discord_support.clients.ipc is None


@pytest.mark.asyncio
async def test_setup_ipc_client_discord_not_found(discord_support):
    """Test IPC client setup when Discord client is not running"""
    discord_support.config.cparser.setValue("discord/clientid", "fake_client_id")

    with patch("asyncio.get_running_loop"), patch("pypresence.AioPresence") as mock_presence_class:
        mock_presence_class.side_effect = pypresence.exceptions.DiscordNotFound()

        await discord_support._setup_ipc_client()
        assert discord_support.clients.ipc is None


@pytest.mark.asyncio
async def test_setup_ipc_client_connection_refused(discord_support):
    """Test IPC client setup with connection refused"""
    discord_support.config.cparser.setValue("discord/clientid", "fake_client_id")

    with patch("asyncio.get_running_loop"), patch("pypresence.AioPresence") as mock_presence_class:
        mock_presence_class.side_effect = ConnectionRefusedError()

        await discord_support._setup_ipc_client()
        assert discord_support.clients.ipc is None


@pytest.mark.asyncio
async def test_setup_ipc_client_connect_failure(discord_support):
    """Test IPC client setup with connection failure"""
    discord_support.config.cparser.setValue("discord/clientid", "fake_client_id")

    with patch("asyncio.get_running_loop"), patch("pypresence.AioPresence") as mock_presence_class:
        mock_ipc = AsyncMock()
        mock_ipc.connect.side_effect = ConnectionRefusedError()
        mock_presence_class.return_value = mock_ipc

        await discord_support._setup_ipc_client()
        assert discord_support.clients.ipc is None


# Bot update tests
@pytest.mark.asyncio
async def test_update_bot_no_config():
    """Test bot update with no config"""
    support = DiscordSupport(config=None, stopevent=None)
    await support._update_bot("test message")
    # Should return early without error


@pytest.mark.asyncio
async def test_update_bot_no_client(discord_support):
    """Test bot update with no bot client"""
    await discord_support._update_bot("test message")
    # Should return early without error


@pytest.mark.asyncio
async def test_update_bot_streaming_activity(discord_support):
    """Test bot update with streaming activity"""
    discord_support.config.cparser.setValue("twitchbot/channel", "test_channel")
    discord_support.config.cparser.setValue("twitchbot/enabled", True)

    mock_bot = AsyncMock(spec=discord.Client)
    discord_support.clients.bot = mock_bot

    with patch("discord.Streaming") as mock_streaming:
        await discord_support._update_bot("test message")
        mock_streaming.assert_called_once_with(
            platform="Twitch", name="test message", url="https://twitch.tv/test_channel"
        )
        mock_bot.change_presence.assert_called_once()


@pytest.mark.asyncio
async def test_update_bot_game_activity(discord_support):
    """Test bot update with game activity"""
    # Default bootstrap config has no twitch settings, so should use Game activity
    mock_bot = AsyncMock(spec=discord.Client)
    discord_support.clients.bot = mock_bot

    with patch("discord.Game") as mock_game:
        await discord_support._update_bot("test message")
        mock_game.assert_called_once_with("test message")
        mock_bot.change_presence.assert_called_once()


@pytest.mark.asyncio
async def test_update_bot_connection_error(discord_support):
    """Test bot update with connection error"""
    mock_bot = AsyncMock(spec=discord.Client)
    mock_bot.change_presence.side_effect = ConnectionResetError()
    discord_support.clients.bot = mock_bot

    await discord_support._update_bot("test message")
    assert discord_support.clients.bot is None


# IPC update tests
@pytest.mark.asyncio
async def test_update_ipc_no_client(discord_support):
    """Test IPC update with no client"""
    await discord_support._update_ipc("test message")
    # Should return early without error


@pytest.mark.asyncio
async def test_update_ipc_success(discord_support):
    """Test successful IPC update"""
    mock_ipc = AsyncMock(spec=pypresence.AioPresence)
    discord_support.clients.ipc = mock_ipc

    await discord_support._update_ipc("test message")
    mock_ipc.update.assert_called_once_with(state="Streaming", details="test message")


@pytest.mark.asyncio
async def test_update_ipc_with_musicbrainz_cover_art(discord_support):
    """Test IPC update with MusicBrainz cover art"""
    mock_ipc = AsyncMock(spec=pypresence.AioPresence)
    discord_support.clients.ipc = mock_ipc

    metadata = {
        "title": "Test Song",
        "artist": "Test Artist",
        "musicbrainzalbumid": ["12345678-1234-1234-1234-123456789abc"],
    }

    await discord_support._update_ipc("test message", metadata)
    expected_url = "https://coverartarchive.org/release/12345678-1234-1234-1234-123456789abc/front"
    mock_ipc.update.assert_called_once_with(
        state="Streaming",
        details="test message",
        large_image=expected_url,
        large_text="♪ Test Song",
    )


@pytest.mark.asyncio
async def test_update_ipc_with_musicbrainz_cover_art_string(discord_support):
    """Test IPC update with MusicBrainz cover art as string"""
    mock_ipc = AsyncMock(spec=pypresence.AioPresence)
    discord_support.clients.ipc = mock_ipc

    metadata = {
        "title": "Test Song",
        "artist": "Test Artist",
        "musicbrainzalbumid": "12345678-1234-1234-1234-123456789abc",  # String format
    }

    await discord_support._update_ipc("test message", metadata)
    expected_url = "https://coverartarchive.org/release/12345678-1234-1234-1234-123456789abc/front"
    mock_ipc.update.assert_called_once_with(
        state="Streaming",
        details="test message",
        large_image=expected_url,
        large_text="♪ Test Song",
    )


@pytest.mark.asyncio
async def test_update_ipc_with_asset_key_fallback(discord_support):
    """Test IPC update falls back to asset key when no MusicBrainz ID"""
    discord_support.config.cparser.setValue("discord/large_image_key", "music_note")
    discord_support.config.cparser.setValue("discord/small_image_key", "app_logo")

    mock_ipc = AsyncMock(spec=pypresence.AioPresence)
    discord_support.clients.ipc = mock_ipc

    metadata = {
        "title": "Test Song",
        "artist": "Test Artist",
        # No musicbrainzalbumid
    }

    await discord_support._update_ipc("test message", metadata)
    mock_ipc.update.assert_called_once_with(
        state="Streaming",
        details="test message",
        large_image="music_note",
        large_text="♪ Test Song",
        small_image="app_logo",
        small_text="by Test Artist",
    )


@pytest.mark.asyncio
async def test_update_ipc_connection_refused(discord_support):
    """Test IPC update with connection refused"""
    mock_ipc = AsyncMock(spec=pypresence.AioPresence)
    mock_ipc.update.side_effect = ConnectionRefusedError()
    discord_support.clients.ipc = mock_ipc

    await discord_support._update_ipc("test message")
    assert discord_support.clients.ipc is None


@pytest.mark.asyncio
async def test_update_ipc_exception(discord_support):
    """Test IPC update with general exception"""
    mock_ipc = AsyncMock(spec=pypresence.AioPresence)
    mock_ipc.update.side_effect = Exception("Unknown error")
    discord_support.clients.ipc = mock_ipc

    await discord_support._update_ipc("test message")
    assert discord_support.clients.ipc is None


# Client connection tests
@pytest.mark.asyncio
async def test_connect_clients(discord_support):
    """Test client connection logic"""
    with (
        patch.object(discord_support, "_setup_bot_client") as mock_setup_bot,
        patch.object(discord_support, "_setup_ipc_client") as mock_setup_ipc,
    ):
        await discord_support.connect_clients()

        mock_setup_bot.assert_called_once()
        mock_setup_ipc.assert_called_once()


@pytest.mark.asyncio
async def test_connect_clients_existing_clients(discord_support):
    """Test client connection when clients already exist"""
    discord_support.clients.bot = MagicMock(spec=discord.Client)
    discord_support.clients.ipc = MagicMock(spec=pypresence.AioPresence)

    with (
        patch.object(discord_support, "_setup_bot_client") as mock_setup_bot,
        patch.object(discord_support, "_setup_ipc_client") as mock_setup_ipc,
    ):
        await discord_support.connect_clients()

        mock_setup_bot.assert_not_called()
        mock_setup_ipc.assert_not_called()


# Signal handling tests
def test_forced_stop_with_stopevent(discord_support, mock_stopevent):
    """Test forced stop with valid stop event"""
    discord_support.forced_stop(15, None)
    mock_stopevent.set.assert_called_once()


def test_forced_stop_no_stopevent():
    """Test forced stop with no stop event"""
    support = DiscordSupport(config=None, stopevent=None)
    # Should not raise an exception
    support.forced_stop(15, None)


# Module-level function tests
def test_stop_function():
    """Test the stop function"""
    with patch("os.kill") as mock_kill:
        nowplaying.processes.discordbot.stop(12345)
        mock_kill.assert_called_once_with(12345, 2)  # SIGINT = 2


def test_stop_function_process_not_found():
    """Test stop function with ProcessLookupError"""
    with patch("os.kill") as mock_kill:
        mock_kill.side_effect = ProcessLookupError()
        # Should not raise an exception
        nowplaying.processes.discordbot.stop(12345)


def test_start_function():
    """Test the start function"""
    mock_event = MagicMock()

    with (
        patch("nowplaying.frozen.frozen_init") as mock_frozen,
        patch("nowplaying.bootstrap.set_qt_names") as mock_qt_names,
        patch("nowplaying.bootstrap.setuplogging") as mock_logging,
        patch("nowplaying.config.ConfigFile") as mock_config,
        patch("signal.signal"),
        patch("nowplaying.db.MetadataDB") as mock_metadb,
    ):
        mock_frozen.return_value = "/fake/path"
        mock_logging.return_value = "/fake/log/path"

        # Mock the database and watcher to prevent actual DB operations
        mock_watcher = MagicMock()
        mock_metadb.return_value.watcher.return_value = mock_watcher

        # Mock the stop event to immediately return so start() completes quickly
        mock_event.is_set.return_value = True

        nowplaying.processes.discordbot.start(mock_event, "/bundle/dir", testmode=True)

        mock_frozen.assert_called_once_with("/bundle/dir")
        mock_qt_names.assert_called_once_with(appname="testsuite")
        mock_logging.assert_called_once_with(logname="debug.log", rotate=False)
        mock_config.assert_called_once()


# Integration tests that require real Discord credentials
@skip_no_discord_bot_token
@pytest.mark.asyncio
async def test_real_bot_client_setup(bootstrap):
    """Test setting up a real Discord bot client"""
    bootstrap.cparser.setValue("discord/token", os.environ["DISCORD_BOT_TOKEN"])
    bootstrap.cparser.setValue("discord/enabled", True)

    stopevent = asyncio.Event()
    support = DiscordSupport(config=bootstrap, stopevent=stopevent)

    try:
        await support._setup_bot_client()
        assert support.clients.bot is not None
        assert isinstance(support.clients.bot, discord.Client)
    finally:
        if support.clients.bot:
            await support.clients.bot.close()


@skip_no_discord_client_id
@pytest.mark.asyncio
async def test_real_ipc_client_setup(bootstrap):
    """Test setting up a real Discord IPC client"""
    bootstrap.cparser.setValue("discord/clientid", os.environ["DISCORD_CLIENT_ID"])
    bootstrap.cparser.setValue("discord/enabled", True)

    stopevent = asyncio.Event()
    support = DiscordSupport(config=bootstrap, stopevent=stopevent)

    try:
        await support._setup_ipc_client()
        # Note: This might fail if Discord client is not running locally
        # That's expected behavior and the test should handle it gracefully
        if support.clients.ipc:
            assert isinstance(support.clients.ipc, pypresence.AioPresence)
    except (pypresence.exceptions.DiscordNotFound, ConnectionRefusedError):
        # Expected if Discord client is not running
        pytest.skip("Discord client not running locally")


@skip_no_discord_bot_token
@pytest.mark.asyncio
async def test_real_bot_update(bootstrap):
    """Test updating bot status with real client"""
    bootstrap.cparser.setValue("discord/token", os.environ["DISCORD_BOT_TOKEN"])
    bootstrap.cparser.setValue("discord/enabled", True)

    stopevent = asyncio.Event()
    support = DiscordSupport(config=bootstrap, stopevent=stopevent)

    try:
        await support._setup_bot_client()
        if support.clients.bot and support.clients.bot.is_ready():
            await support._update_bot("Test Message from Unit Tests")
            # Give Discord a moment to process
            await asyncio.sleep(1)
    finally:
        if support.clients.bot:
            await support.clients.bot.close()
