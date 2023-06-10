#!/usr/bin/env python3
''' test winmedia ... ok, not really. '''

import asyncio
import logging

import pytest
import nowplaying.twitch.chat  # pylint: disable=import-error


def setup_generic_commands(config):
    ''' setup a bunch of default commands to test against '''
    for command in nowplaying.twitch.chat.TWITCHBOT_CHECKBOXES:
        cmd = f'twitchbot-command-{command}'
        for checkbox in nowplaying.twitch.chat.TWITCHBOT_CHECKBOXES:
            if command == checkbox:
                config.cparser.setValue(f'{cmd}cmd/{checkbox}', True)
            else:
                config.cparser.setValue(f'{cmd}cmd/{checkbox}', False)


@pytest.mark.asyncio
async def test_twitchchat_perms(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test twitchbot perms '''
    config = bootstrap
    stopevent = asyncio.Event()

    setup_generic_commands(config)
    config.cparser.sync()
    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)

    streamerprofile = {'broadcaster': '1', 'subscriber': '9'}
    moderatorprofile = {'moderator': '1', 'subscriber': '24'}
    hypetrainprofile = {'vip': '1', 'subscriber': '3012', 'hype-train': '1'}

    for profile in [streamerprofile, moderatorprofile, hypetrainprofile]:
        for box in nowplaying.twitch.chat.TWITCHBOT_CHECKBOXES:
            logging.debug('Checking %s vs %s', profile, box)
            if box == 'anyone' or profile.get(box):
                assert chat.check_command_perms(profile, f'{box}cmd')
            else:
                assert not chat.check_command_perms(profile, f'{box}cmd')

    stopevent.set()
