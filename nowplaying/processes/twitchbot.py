#!/usr/bin/env python3
'''

Driver for the Twitch support code

'''

import logging
import logging.config
import logging.handlers
import os
import signal
import sys
import threading

import nowplaying.bootstrap
import nowplaying.twitch

# 1. create a bot account, be sure to enable multiple logins per email
# 2. enable 2FA
# 3. go to dev.twitch.tv to register your application
#   1. name (this will be the login username for the bot, the name in chat will be the account name)
#   2. http://localhost
#   3. Category: Chat bot
#   4. Create
#   5. go into manage  clientid is now there
# username and clientid  comes from https://dev.twitch.tv/console/apps/create
# token comes from http://twitchapps.com/tmi/
#


def stop(pid):
    ''' stop the web server -- called from Tray '''
    logging.info('sending INT to %s', pid)
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        pass


def start(stopevent, bundledir, testmode=False):  #pylint: disable=unused-argument
    ''' multiprocessing start hook '''
    threading.current_thread().name = 'TwitchBot'

    if not bundledir:
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            bundledir = getattr(sys, '_MEIPASS',
                                os.path.abspath(os.path.dirname(__file__)))
        else:
            bundledir = os.path.abspath(os.path.dirname(__file__))

    nowplaying.bootstrap.set_qt_names()
    nowplaying.bootstrap.setuplogging(rotate=False)

    config = nowplaying.config.ConfigFile(bundledir=bundledir)
    logging.info('boot up')
    twitchbot = nowplaying.twitch.TwitchSupport(stopevent=stopevent,
                                                config=config)  # pylint: disable=unused-variable
    twitchbot.start()
