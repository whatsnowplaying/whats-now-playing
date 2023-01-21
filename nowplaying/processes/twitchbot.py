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
import nowplaying.frozen
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

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
    else:
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname='debug.log',
                                                rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir,
                                          logpath=logpath,
                                          testmode=testmode)
    logging.info('boot up')
    try:
        twitchbot = nowplaying.twitch.TwitchSupport(stopevent=stopevent,
                                                    config=config)  # pylint: disable=unused-variable
        twitchbot.start()
    except Exception as error:  #pylint: disable=broad-except
        logging.error('TrackPoll crashed: %s', error, exc_info=True)
        sys.exit(1)
    logging.info('shutting down twitchbot v%s',
                 nowplaying.version.get_versions()['version'])
