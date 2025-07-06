#!/usr/bin/env python3
''' twitch request handling using EventSub WebSockets '''

import asyncio
import logging
import traceback
from typing import TYPE_CHECKING, Any

from twitchAPI.object.api import TwitchUser
from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.helper import first
from twitchAPI.object.eventsub import ChannelPointsCustomRewardRedemptionAddEvent
from twitchAPI.twitch import Twitch

import nowplaying.config
import nowplaying.trackrequests
import nowplaying.twitch.oauth2
import nowplaying.twitch.utils
import nowplaying.utils

if TYPE_CHECKING:
    import nowplaying.twitch.chat

# Suppress noisy TwitchAPI websocket keepalive logging
logging.getLogger('twitchAPI.eventsub.websocket').setLevel(logging.INFO)




class TwitchRedemptions:  #pylint: disable=too-many-instance-attributes
    ''' handle twitch redemptions using EventSub WebSockets

        Converted from deprecated PubSub to EventSub WebSockets.
        Different methods are being called by different parts of the system
        presently. Should probably split them out between UI/non-UI if possible,
        since UI code can't call async code.
    '''

    def __init__(self, config: nowplaying.config.ConfigFile | None = None, stopevent=None):
        self.config = config
        self.stopevent = stopevent
        self.filelists = None
        self.chat = None
        self.eventsub: EventSubWebsocket | None = None
        self.requests = nowplaying.trackrequests.Requests(config=config, stopevent=stopevent)
        self.widgets = None
        self.watcher = None
        self.twitch: Twitch | None = None
        self.user_id: str | None = None

    async def callback_redemption(self, data: ChannelPointsCustomRewardRedemptionAddEvent):
        ''' handle the channel point redemption '''
        redemptitle = data.event.reward.title
        user = data.event.user_name
        user_input = data.event.user_input or None

        reqdata = {}

        if setting := await self.requests.find_twitchtext(redemptitle):
            # Get user image using the OAuth2 client
            oauth_client = nowplaying.twitch.oauth2.TwitchOAuth2(self.config)

            # Get current tokens for API calls
            access_token, _ = oauth_client.get_stored_tokens()
            if access_token:
                # Set the token in the OAuth client for API calls
                oauth_client.access_token = access_token
                setting['userimage'] = await nowplaying.twitch.utils.get_user_image(
                    oauth_client, user)
            else:
                # No token available for user image lookup
                setting['userimage'] = None
                logging.warning('No OAuth token available for user image lookup')

            if setting.get('type') == 'Generic':
                reqdata = await self.requests.user_track_request(setting, user, user_input)
            elif setting.get('type') == 'Roulette':
                reqdata = await self.requests.user_roulette_request(setting, user, user_input)
            elif setting.get('type') == 'Twofer':
                reqdata = await self.requests.twofer_request(setting, user, user_input)
            elif setting.get('type') == 'GifWords':
                reqdata = await self.requests.gifwords_request(setting, user, user_input)

            if self.chat and setting.get('command'):
                await self.chat.redemption_to_chat_request_bridge(setting['command'], reqdata)

    async def run_redemptions(self,
                              chat: 'nowplaying.twitch.chat.TwitchChat | None'):
        ''' twitch redemptions using EventSub WebSockets '''
        # Wait until both redemptions and requests are enabled
        await self._wait_for_redemptions_enabled()

        if nowplaying.utils.safe_stopevent_check(self.stopevent):
            return

        self.chat = chat
        loggedin = False

        while not nowplaying.utils.safe_stopevent_check(self.stopevent) and not loggedin:
            await asyncio.sleep(5)
            if nowplaying.utils.safe_stopevent_check(self.stopevent):
                break


            # Check if we were connected but lost connection
            if loggedin and self.eventsub and not self._is_eventsub_running():
                logging.debug('Was logged in; but not connected to EventSub anymore')
                await self.stop()
                loggedin = False

            if loggedin:
                continue

            await asyncio.sleep(4)

            try:
                if await self._setup_eventsub_connection():
                    loggedin = True
                else:
                    await asyncio.sleep(60)
            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                logging.error('EventSub failed to start')
                await asyncio.sleep(60)
                continue

    async def _wait_for_redemptions_enabled(self):
        ''' Wait until both redemptions and requests are enabled '''
        if not self.config:
            return
        while not nowplaying.utils.safe_stopevent_check(self.stopevent) and (
                not self.config.cparser.value('twitchbot/redemptions', type=bool)
                or not self.config.cparser.value('settings/requests', type=bool)):
            await asyncio.sleep(1)
            self.config.get()

    def _is_eventsub_running(self) -> bool:
        ''' Check if EventSub WebSocket is running '''
        if not self.eventsub:
            return False
        return self.eventsub._running  # pylint: disable=protected-access

    async def _setup_eventsub_connection(self) -> bool:
        ''' Set up EventSub connection and authentication '''
        # Create dedicated TwitchLogin for redemptions (broadcaster account only)
        redemption_login = nowplaying.twitch.utils.TwitchLogin(self.config)
        self.twitch = await redemption_login.api_login()
        if not self.twitch:
            logging.debug("something happened getting twitch api_login; aborting")
            await redemption_login.cache_token_del()
            return False

        # Get authenticated user info
        user = await self._get_authenticated_user(redemption_login)
        if not user:
            return False

        self.user_id = user.id

        # Check custom rewards
        await self._check_custom_rewards(user)

        # Verify channel configuration
        if not await self._verify_channel_config(user):
            return False

        # Set up EventSub WebSocket
        return await self._setup_eventsub_websocket()

    async def _get_authenticated_user(
            self, redemption_login: nowplaying.twitch.utils.TwitchLogin) -> TwitchUser | None:
        ''' Get authenticated user info (must be broadcaster for channel points) '''
        try:
            # Get the authenticated user (token owner) instead of channel config
            if self.twitch:
                users_gen = self.twitch.get_users()
                return await first(users_gen)
        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            logging.error('EventSub get authenticated user failed')
            await redemption_login.cache_token_del()
        return None

    async def _check_custom_rewards(self, user: TwitchUser):
        ''' Check what custom rewards exist and which ones we can access '''
        if not self.twitch or not self.user_id:
            return
        try:
            # Get manageable rewards
            rewards_response = await self.twitch.get_custom_reward(broadcaster_id=self.user_id,
                                                                   only_manageable_rewards=True)
            manageable_rewards = await self._process_rewards_response(rewards_response)

            # Get all rewards
            all_rewards_response = await self.twitch.get_custom_reward(
                broadcaster_id=self.user_id, only_manageable_rewards=False)
            all_rewards = await self._process_rewards_response(all_rewards_response)

            self._log_rewards_info(user, manageable_rewards, all_rewards)
        except Exception as reward_error:  # pylint: disable=broad-except
            logging.warning('Could not check custom rewards: %s', reward_error)

    @staticmethod
    async def _process_rewards_response(rewards_response: Any) -> list[Any]:
        ''' Process rewards response (handle both async iterator and list) '''
        if hasattr(rewards_response, '__aiter__'):
            return [reward async for reward in rewards_response]
        return list(rewards_response) if rewards_response else []

    @staticmethod
    def _log_rewards_info(user: TwitchUser, manageable_rewards: list[Any], all_rewards: list[Any]):
        ''' Log information about available rewards '''
        logging.info('Channel point rewards check for user "%s":', user.login)
        logging.info('  Total rewards: %d', len(all_rewards))
        logging.info('  Manageable by our app: %d', len(manageable_rewards))

        if manageable_rewards:
            logging.info('  Rewards we can monitor:')
            for reward in manageable_rewards:
                logging.info('    - "%s" (ID: %s)', reward.title, reward.id)
        else:
            logging.warning('  No rewards manageable by our OAuth app!')
            if all_rewards:
                logging.warning('  Existing rewards (created by other apps):')
                for reward in all_rewards:
                    logging.warning('    - "%s" (not accessible)', reward.title)
            logging.warning('  To use channel points, create rewards through this app '
                            'or use rewards created with the same OAuth client ID.')

    async def _verify_channel_config(self, user: TwitchUser) -> bool:
        ''' Verify the authenticated user matches the configured channel '''
        if not self.config:
            return False
        configured_channel = self.config.cparser.value('twitchbot/channel')
        if configured_channel and user.login.lower() != configured_channel.lower():
            logging.error(
                'EventSub auth mismatch: OAuth token is for user "%s" but channel is '
                'set to "%s". For channel points redemptions, the OAuth token must be '
                'for the broadcaster\'s account.', user.login, configured_channel)
            # Don't immediately revoke token - just log and continue to next iteration
            await asyncio.sleep(60)
            return False
        return True

    async def _setup_eventsub_websocket(self) -> bool:
        ''' Set up EventSub WebSocket connection and register callback '''
        if not self.twitch or not self.user_id:
            return False
        # Create EventSub WebSocket connection
        self.eventsub = EventSubWebsocket(self.twitch)

        # Start the EventSub WebSocket
        self.eventsub.start()

        # Wait for connection to be established
        await asyncio.sleep(2)

        if not self._is_eventsub_running():
            logging.error('EventSub failed to connect')
            return False

        # Listen for channel points redemptions
        try:
            await self.eventsub.listen_channel_points_custom_reward_redemption_add(
                self.user_id, self.callback_redemption)
            logging.info('EventSub listening for channel points redemptions')
            return True
        except Exception as callback_error:  # pylint: disable=broad-except
            logging.error('Failed to register EventSub callback: %s', callback_error)
            # Don't clear tokens for callback registration errors
            await asyncio.sleep(10)
            return False

    async def stop(self):
        ''' stop the twitch redemption support '''
        if self.eventsub:
            try:
                # Stop EventSub WebSocket
                await self.eventsub.stop()
                logging.debug('EventSub stopped')
            except Exception as error:  # pylint: disable=broad-except
                logging.error('Error stopping EventSub: %s', error)
            finally:
                self.eventsub = None
