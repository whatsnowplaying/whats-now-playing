#!/usr/bin/env python3
''' twitch request handling '''

import asyncio
import logging
import traceback

from twitchAPI.pubsub import PubSub
from twitchAPI.helper import first
from twitchAPI.types import AuthScope

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.metadata
import nowplaying.trackrequests
import nowplaying.twitch.utils

USER_SCOPE = [AuthScope.CHANNEL_READ_REDEMPTIONS, AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]


class TwitchRedemptions:  #pylint: disable=too-many-instance-attributes
    ''' handle twitch redemptions


        Note that different methods are being called by different parts of the system
        presently.  Should probably split them out between UI/non-UI if possible,
        since UI code can't call async code.

    '''

    def __init__(self, config=None, stopevent=None):
        self.config = config
        self.stopevent = stopevent
        self.filelists = None
        self.chat = None
        self.uuid = None
        self.pubsub = None
        self.requests = nowplaying.trackrequests.Requests(config=config, stopevent=stopevent)
        self.widgets = None
        self.watcher = None
        self.twitch = None

    async def callback_redemption(self, uuid, data):  # pylint: disable=unused-argument
        ''' handle the channel point redemption '''
        redemptitle = data['data']['redemption']['reward']['title']
        user = data['data']['redemption']['user']['display_name']
        if data['data']['redemption'].get('user_input'):
            user_input = data['data']['redemption'].get('user_input')
        else:
            user_input = None

        reqdata = {}

        if setting := await self.requests.find_twitchtext(redemptitle):
            setting['userimage'] = await nowplaying.twitch.utils.get_user_image(self.twitch, user)
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
        ''' twitch redemptions '''

        # stop sleep loop if:
        #
        # stopevent is set -> end
        #
        # or both
        #
        # self.config.cparser.value('twitchbot/redemptions', type=bool) = true
        # self.config.cparser.value('twitchbot/redemptions', type=bool) = true
        # -> stat redemption request support
        #

        while not self.stopevent.is_set() and (
                not self.config.cparser.value('twitchbot/redemptions', type=bool)
                or not self.config.cparser.value('settings/requests', type=bool)):
            await asyncio.sleep(1)
            self.config.get()

        if self.stopevent.is_set():
            return

        self.chat = chat
        loggedin = False
        while not self.stopevent.is_set() and not loggedin:
            await asyncio.sleep(5)
            if self.stopevent.is_set():
                break

            if loggedin and self.pubsub and not self.pubsub.is_connected():
                logging.debug('Was logged in; but not connected to pubsub anymore')
                await self.stop()
                loggedin = False

            if loggedin:
                continue

            await asyncio.sleep(4)

            try:
                self.twitch = await twitchlogin.api_login()
                if not self.twitch:
                    logging.debug("something happened getting twitch api_login; aborting")
                    await twitchlogin.cache_token_del()
                    continue
                # starting up PubSub
                self.pubsub = PubSub(self.twitch)
                self.pubsub.start()
            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                logging.error('pubsub failed to start')
                await twitchlogin.cache_token_del()
                await asyncio.sleep(60)
                continue

            user = None
            try:
                user = await first(
                    self.twitch.get_users(logins=[self.config.cparser.value('twitchbot/channel')]))
            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                logging.error('pubsub getusers failed')
                await twitchlogin.cache_token_del()
                continue

            if not user:
                logging.error('pubusb getusers failed')
                await twitchlogin.cache_token_del()
                continue

            # you can either start listening before or after you started pubsub.
            try:
                self.uuid = await self.pubsub.listen_channel_points(user.id,
                                                                    self.callback_redemption)
                loggedin = True
            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                logging.error('pubsub listen_channel_points failed')
                await twitchlogin.cache_token_del()
                loggedin = False

    async def stop(self):
        ''' stop the twitch redemption support '''
        if self.pubsub:
            if self.uuid:
                await self.pubsub.unlisten(self.uuid)
            self.pubsub.stop()
            logging.debug('pubsub stopped')
