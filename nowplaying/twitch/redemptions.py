#!/usr/bin/env python3
''' twitch request handling '''

import asyncio
import logging

import requests

from twitchAPI.pubsub import PubSub
from twitchAPI.helper import first
from twitchAPI.types import AuthScope

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.metadata
import nowplaying.trackrequests
import nowplaying.version

USER_SCOPE = [
    AuthScope.CHANNEL_READ_REDEMPTIONS, AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT
]


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
        self.uuid = None
        self.pubsub = None
        self.requests = nowplaying.trackrequests.Requests(config=config,
                                                          stopevent=stopevent)
        self.widgets = None
        self.watcher = None
        self.twitch = None

    async def _get_user_image(self, loginname):
        ''' ask twitch for the user profile image '''
        image = None
        try:
            user = await first(self.twitch.get_users(logins=loginname))
            req = requests.get(user.profile_image_url, timeout=5)
            image = nowplaying.utils.image2png(req.content)
        except Exception as error:  #pylint: disable=broad-except
            logging.debug(error)
        return image

    async def user_roulette_request(self,
                                    setting,
                                    user,
                                    user_input,
                                    reqid=None):
        ''' roulette request '''

        if not setting.get('playlist'):
            logging.error('%s does not have a playlist defined',
                          setting.get('displayname'))
            return

        logging.debug('%s requested roulette %s | %s', user,
                      setting['playlist'], user_input)

        plugin = self.config.cparser.value('settings/input')
        roulette = await self.config.pluginobjs['inputs'][
            f'nowplaying.inputs.{plugin}'].getrandomtrack(setting['playlist'])
        metadata = await nowplaying.metadata.MetadataProcessors(
            config=self.config
        ).getmoremetadata(metadata={'filename': roulette}, skipplugins=True)
        data = {
            'username': user,
            'artist': metadata.get('artist'),
            'filename': metadata['filename'],
            'title': metadata.get('title'),
            'type': 'Roulette',
            'playlist': setting['playlist'],
            'userimage': setting.get('userimage'),
            'displayname': setting.get('displayname'),
        }
        if reqid:
            data['reqid'] = reqid
        await self.requests.add_to_db(data)

    async def callback_redemption(self, uuid, data):  # pylint: disable=unused-argument
        ''' handle the channel point redemption '''
        redemptitle = data['data']['redemption']['reward']['title']
        user = data['data']['redemption']['user']['display_name']
        if data['data']['redemption'].get('user_input'):
            user_input = data['data']['redemption'].get('user_input')
        else:
            user_input = None

        if setting := await self.requests.find_twitchtext(redemptitle):
            setting['userimage'] = self._get_user_image(user)
            if setting.get('type') == 'Generic':
                await self.requests.user_track_request(setting, user,
                                                       user_input)
            elif setting.get('type') == 'Roulette':
                await self.user_roulette_request(setting, user, user_input)

    async def run_redemptions(self, twitch=None):
        ''' twitch redemptions '''

        if not twitch:
            logging.error(
                'No Twitch credentials to start redemptions. Exiting.')
            return

        while not self.config.cparser.value(
                'twitchbot/redemptions') and not self.stopevent.is_set():
            await asyncio.sleep(1)

        if self.stopevent.is_set():
            return

        loop = asyncio.get_running_loop()
        loop.create_task(self.requests.watch_for_respin())
        self.twitch = twitch
        # starting up PubSub
        self.pubsub = PubSub(twitch)
        self.pubsub.start()

        user = await first(
            twitch.get_users(
                logins=[self.config.cparser.value('twitchbot/channel')]))

        # you can either start listening before or after you started pubsub.
        self.uuid = await self.pubsub.listen_channel_points(
            user.id, self.callback_redemption)

    async def stop(self):
        ''' stop the twitch redemption support '''
        if self.pubsub:
            await self.pubsub.unlisten(self.uuid)
            self.pubsub.stop()
