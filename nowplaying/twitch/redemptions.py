#!/usr/bin/env python3
''' twitch request handling using EventSub WebSockets '''

import asyncio
import logging
import traceback

# Suppress noisy TwitchAPI websocket keepalive logging
logging.getLogger('twitchAPI.eventsub.websocket').setLevel(logging.INFO)

from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.helper import first
from twitchAPI.object.eventsub import ChannelPointsCustomRewardRedemptionAddEvent

import nowplaying.trackrequests
import nowplaying.twitch.utils
import nowplaying.utils


class TwitchRedemptions:  #pylint: disable=too-many-instance-attributes
    ''' handle twitch redemptions using EventSub WebSockets

        Converted from deprecated PubSub to EventSub WebSockets.
        Different methods are being called by different parts of the system
        presently. Should probably split them out between UI/non-UI if possible,
        since UI code can't call async code.
    '''

    def __init__(self, config=None, stopevent=None):
        self.config = config
        self.stopevent = stopevent
        self.filelists = None
        self.chat = None
        self.eventsub = None
        self.requests = nowplaying.trackrequests.Requests(config=config, stopevent=stopevent)
        self.widgets = None
        self.watcher = None
        self.twitch = None
        self.user_id = None

    async def callback_redemption(self, data: ChannelPointsCustomRewardRedemptionAddEvent):
        ''' handle the channel point redemption '''
        redemptitle = data.event.reward.title
        user = data.event.user_name
        user_input = data.event.user_input if data.event.user_input else None

        reqdata = {}

        if setting := await self.requests.find_twitchtext(redemptitle):
            # Get user image using the OAuth client instead of twitch API object
            if hasattr(self.twitch, '_oauth_client'):
                oauth_client = self.twitch._oauth_client
            else:
                # Fallback - create a simple object with required attributes
                class SimpleOAuth:

                    def __init__(self, twitch_obj):
                        # TwitchAPI library attribute names
                        self.access_token = getattr(twitch_obj, '_user_auth_token', None)
                        self.client_id = getattr(twitch_obj, '_app_id',
                                                 getattr(twitch_obj, 'app_id', None))
                        self.API_HOST = 'https://api.twitch.tv/helix'

                oauth_client = SimpleOAuth(self.twitch)

            setting['userimage'] = await nowplaying.twitch.utils.get_user_image(oauth_client, user)

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

    async def run_redemptions(self, twitchlogin, chat):  # pylint: disable=too-many-branches
        ''' twitch redemptions using EventSub WebSockets '''

        # Wait until both redemptions and requests are enabled
        while not nowplaying.utils.safe_stopevent_check(self.stopevent) and (
                not self.config.cparser.value('twitchbot/redemptions', type=bool)
                or not self.config.cparser.value('settings/requests', type=bool)):
            await asyncio.sleep(1)
            self.config.get()

        if nowplaying.utils.safe_stopevent_check(self.stopevent):
            return

        self.chat = chat
        loggedin = False

        while not nowplaying.utils.safe_stopevent_check(self.stopevent) and not loggedin:
            await asyncio.sleep(5)
            if nowplaying.utils.safe_stopevent_check(self.stopevent):
                break

            # Check if we were connected but lost connection
            if loggedin and self.eventsub and not self.eventsub._running:
                logging.debug('Was logged in; but not connected to EventSub anymore')
                await self.stop()
                loggedin = False

            if loggedin:
                continue

            await asyncio.sleep(4)

            try:
                # Create dedicated TwitchLogin for redemptions (broadcaster account only)
                # Don't use shared twitchlogin as it might switch to chat bot token
                redemption_login = nowplaying.twitch.utils.TwitchLogin(self.config)
                self.twitch = await redemption_login.api_login()
                if not self.twitch:
                    logging.debug("something happened getting twitch api_login; aborting")
                    await redemption_login.cache_token_del()
                    continue

                # Get authenticated user info (must be broadcaster for channel points)
                user = None
                try:
                    # Get the authenticated user (token owner) instead of channel config
                    users_gen = self.twitch.get_users()
                    user = await first(users_gen)
                except Exception:  # pylint: disable=broad-except
                    for line in traceback.format_exc().splitlines():
                        logging.error(line)
                    logging.error('EventSub get authenticated user failed')
                    await redemption_login.cache_token_del()
                    continue

                if not user:
                    logging.error('EventSub get authenticated user failed')
                    await redemption_login.cache_token_del()
                    continue

                self.user_id = user.id

                # Check what custom rewards exist and which ones we can access
                try:
                    # Get all custom rewards for this broadcaster
                    rewards_response = await self.twitch.get_custom_reward(
                        broadcaster_id=self.user_id, only_manageable_rewards=True)
                    # Handle both async iterator and list responses from TwitchAPI
                    if hasattr(rewards_response, '__aiter__'):
                        manageable_rewards = [reward async for reward in rewards_response]
                    else:
                        manageable_rewards = list(rewards_response) if rewards_response else []

                    # Get all rewards (including ones we can't manage)
                    all_rewards_response = await self.twitch.get_custom_reward(
                        broadcaster_id=self.user_id, only_manageable_rewards=False)
                    # Handle both async iterator and list responses from TwitchAPI
                    if hasattr(all_rewards_response, '__aiter__'):
                        all_rewards = [reward async for reward in all_rewards_response]
                    else:
                        all_rewards = list(all_rewards_response) if all_rewards_response else []

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

                except Exception as reward_error:  # pylint: disable=broad-except
                    logging.warning('Could not check custom rewards: %s', reward_error)

                # Verify the authenticated user matches the configured channel
                configured_channel = self.config.cparser.value('twitchbot/channel')
                if configured_channel and user.login.lower() != configured_channel.lower():
                    logging.error(
                        'EventSub auth mismatch: OAuth token is for user "%s" but channel is '
                        'set to "%s". For channel points redemptions, the OAuth token must be '
                        'for the broadcaster\'s account.', user.login, configured_channel)
                    # Don't immediately revoke token - just log and continue to next iteration
                    await asyncio.sleep(60)
                    continue

                # Create EventSub WebSocket connection
                self.eventsub = EventSubWebsocket(self.twitch)

                # Start the EventSub WebSocket
                self.eventsub.start()

                # Wait for connection to be established
                await asyncio.sleep(2)

                if not self.eventsub._running:
                    logging.error('EventSub failed to connect')
                    await twitchlogin.cache_token_del()
                    continue

                # Listen for channel points redemptions
                try:
                    await self.eventsub.listen_channel_points_custom_reward_redemption_add(
                        self.user_id, self.callback_redemption)
                    logging.info('EventSub listening for channel points redemptions')
                    loggedin = True
                except Exception as callback_error:  # pylint: disable=broad-except
                    logging.error('Failed to register EventSub callback: %s', callback_error)
                    # Don't clear tokens for callback registration errors
                    await asyncio.sleep(10)
                    continue

            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                logging.error('EventSub failed to start')
                await redemption_login.cache_token_del()
                await asyncio.sleep(60)
                continue

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
