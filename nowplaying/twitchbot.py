#!/usr/bin/env python3
'''

This code originally:

Copyright 2017 Amazon.com, Inc. or its affiliates. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License"). You may not
use this file except in compliance with the License. A copy of the License
is located at

    http://aws.amazon.com/apache2.0/

or in the "license" file accompanying this file. This file is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied. See the License for the specific language governing permissions and
limitations under the License.
'''

import logging
import logging.config
import logging.handlers
import os
import pathlib
import secrets
import signal
import string
import sys
import textwrap
import threading
import time

import irc.bot
import jinja2

from PySide6.QtCore import QCoreApplication, QStandardPaths  # pylint: disable=no-name-in-module

#
# quiet down our imports
#

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

#pylint: disable=wrong-import-position

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.version

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

LASTANNOUNCED = {'artist': None, 'title': None}


class TwitchBot(irc.bot.SingleServerIRCBot):  # pylint: disable=too-many-instance-attributes
    ''' twitch bot '''

    def __init__(self, username, client_id, token, channel):
        self.username = username
        self.token = token.removeprefix("oauth:")
        self.channel = f'#{channel.lower()}'
        # some counter is wildly inaccurate and sometimes text bigger than
        # this will be let through.  safety first though and under 450 appears
        # to be safe.
        self.maxsize = 450
        self.watcher = None
        self.client_id = client_id
        self.templatedir = os.path.join(
            QStandardPaths.standardLocations(
                QStandardPaths.DocumentsLocation)[0],
            QCoreApplication.applicationName(), 'templates')
        self.metadb = nowplaying.db.MetadataDB()
        self.config = nowplaying.config.ConfigFile()
        self.magiccommand = ''.join(
            secrets.choice(string.ascii_letters) for _ in range(32))

        logging.info('Secret command to quit twitchbot: %s', self.magiccommand)

        self.jinja2 = self.setup_jinja2(self.templatedir)

        # Create IRC bot connection
        server = 'irc.chat.twitch.tv'
        port = 6667
        logging.info('Connecting to %s on port %d', server, port)
        irc.bot.SingleServerIRCBot.__init__(
            self,
            [(server, port, f'oauth:{self.token}')],
            self.username,
            self.username,
        )

    def _finalize(self, variable):  # pylint: disable=no-self-use
        ''' helper routine to avoid NoneType exceptions '''
        if variable:
            return variable
        return ''

    def setup_jinja2(self, directory):
        ''' set up the environment '''
        return jinja2.Environment(loader=jinja2.FileSystemLoader(directory),
                                  finalize=self._finalize,
                                  trim_blocks=True)

    def _setup_timer(self):
        self.watcher = self.metadb.watcher()
        self.watcher.start(customhandler=self._announce_track)
        self._announce_track(None)

    def _delay_write(self):
        try:
            delay = self.config.cparser.value('twitchbot/announcedelay',
                                              type=float,
                                              defaultValue=1.0)
        except ValueError:
            delay = 1.0
        logging.debug('got delay of %s', delay)
        time.sleep(delay)

    def _announce_track(self, event):  # pylint: disable=unused-argument
        ''' announce new tracks '''
        global LASTANNOUNCED  # pylint: disable=global-statement, global-variable-not-assigned

        self.config.get()

        anntemplate = self.config.cparser.value('twitchbot/announce')
        if not anntemplate:
            return

        if not pathlib.Path(anntemplate).exists():
            logging.error('Annoucement template %s does not exist.',
                          anntemplate)
            return

        metadata = self.metadb.read_last_meta()

        if not metadata:
            return

        # don't announce empty content
        if not metadata['artist'] and not metadata['title']:
            logging.warning(
                'Both artist and title are empty; skipping announcement')
            return

        if metadata['artist'] == LASTANNOUNCED['artist'] and \
           metadata['title'] == LASTANNOUNCED['title']:
            logging.warning(
                'Same artist and title or doubled event notification; skipping announcement.'
            )
            return

        LASTANNOUNCED['artist'] = metadata['artist']
        LASTANNOUNCED['title'] = metadata['title']

        self._delay_write()

        logging.info('Announcing %s',
                     self.config.cparser.value('twitchbot/announce'))
        if not self.config.cparser.value('twitchbot/enabled', type=bool):
            self.shutdown()
        self._post_template(
            os.path.basename(self.config.cparser.value('twitchbot/announce')))

    def on_welcome(self, connection, event):  # pylint: disable=unused-argument
        ''' join the IRC channel and set up our stuff '''
        threading.current_thread().name = 'TwitchBot'
        logging.info('Joining %s', self.channel)

        # You must request specific capabilities before you can use them
        connection.cap('REQ', ':twitch.tv/membership')
        connection.cap('REQ', ':twitch.tv/tags')
        connection.cap('REQ', ':twitch.tv/commands')
        connection.join(self.channel)
        logging.info('Successfully joined %s', self.channel)
        self._setup_timer()

    def on_pubmsg(self, connection, event):  # pylint: disable=unused-argument
        ''' find commands '''
        self.config.get()
        commandchar = self.config.cparser.value('twitchbot/commandchar')
        if not self.config.cparser.value('twitchbot/enabled', type=bool):
            self.shutdown()
        if not commandchar:
            commandchar = '!'
            self.config.cparser.setValue('twitchbot/commandchar', '!')
        if event.arguments[0][:1] == commandchar:
            cmd = event.arguments[0].split(' ')[0][1:]
            logging.info('Received command: %s', cmd)
            self.do_command(event, cmd)

    def _build_user_profile(self, event):  #pylint: disable=no-self-use
        # Get the channel id, we will need this for v5 API calls
        tags = event.tags
        result = {entry['key']: entry['value'] for entry in tags}
        logging.debug('chat profile: %s', result)
        # frankly, twitch's information that they share on IRC
        # seems pretty dumb. the only way to figure out the status
        # of someone is to check the badge, but then they don't
        # seem to actually publish a list of badges that are available
        # so you have to do a lot of guesswork to figure out what
        # does/doesn't work
        #
        # in any case, this code takes the badges field and breaks
        # it apart and tries to make it easier to deal with later on
        if 'badges' in result and result['badges']:
            result['badgesdict'] = {}
            for badge in result['badges'].split(','):
                badgetype, number = badge.split('/')
                number = int(number)
                result['badgesdict'][badgetype.lower()] = number
        return result

    def _send_text(self, message):
        message = message.replace('\n', ' ')
        message = message.replace('\r', ' ')
        message = str(message).strip()
        for text in textwrap.TextWrapper(width=self.maxsize).wrap(message):
            try:
                self.connection.privmsg(self.channel, text)
            except Exception as error:  # pylint: disable=broad-except
                logging.error(error)

    def _post_template(self, template=None, moremetadata=None):
        if not template:
            return
        metadata = self.metadb.read_last_meta()
        if not metadata:
            metadata = {}
        if 'coverimageraw' in metadata:
            del metadata['coverimageraw']
        metadata['cmdtarget'] = None

        if moremetadata:
            metadata.update(moremetadata)

        if os.path.isfile(os.path.join(self.templatedir, template)):
            template = self.jinja2.get_template(template)
            message = template.render(metadata)
            self._send_text(message)

    def check_command_perms(self, profile, command):
        ''' given the profile, check if the command is allowed to be executed '''
        self.config.get()

        # shortcut the 'anyone' commands
        if self.config.cparser.value(f'twitchbot-command-{command}/anyone',
                                     type=bool):
            return True

        self.config.cparser.beginGroup(f'twitchbot-command-{command}')
        perms = {
            key: self.config.cparser.value(key, type=bool)
            for key in self.config.cparser.childKeys()
        }
        self.config.cparser.endGroup()

        if perms:
            return any(
                'badgesdict' in profile and usertype in profile['badgesdict']
                for usertype in perms.items())

        return True

    def do_command(self, event, command):  # pylint: disable=unused-argument
        ''' process a command '''
        fullstring = event.arguments[0]
        profile = self._build_user_profile(event)
        metadata = {'cmduser': profile['display-name']}
        commands = fullstring.split()
        commands[0] = commands[0][1:]

        if commands[0] == 'whatsnowplayingversion':
            inputsource = self.config.cparser.value('settings/input')
            version = nowplaying.version.get_versions()['version']
            self._send_text(f'whatsnowplaying v{version} by @modernmeerkat. ' +
                            f'Using {inputsource} on {sys.platform}.')
            return

        metadata['cmdtarget'] = []
        if len(commands) > 1:
            for usercheck in commands[1:]:
                if usercheck[0] == '@':
                    metadata['cmdtarget'].append(usercheck[1:])
                else:
                    metadata['cmdtarget'].append(usercheck)

        cmdfile = f'twitchbot_{commands[0]}.txt'

        if not self.check_command_perms(profile, commands[0]):
            return

        if commands[0] == self.magiccommand:
            self.shutdown()

        self._post_template(cmdfile, moremetadata=metadata)

    def shutdown(self):  # pylint: disable=no-self-use
        ''' shutdown '''
        if self.watcher:
            self.watcher.stop()


class TwitchBotHandler():
    ''' Now Playing built-in twitch bot custom handler '''

    def __init__(self, config=None):
        self.config = config
        self.server = None
        self.endthread = False
        signal.signal(signal.SIGINT, self.stop)

    def run(self):  # pylint: disable=too-many-branches, too-many-statements
        '''
            run & configure a twitch bot

            The sleeps are here to make sure we don't
            tie up a CPU constantly checking on
            status.  If we cannot open the port or
            some other situation, we bring everything
            to a halt by triggering pause.

            But in general:

                - web server thread starts
                - check if web serving is running
                - if so, open ANOTHER thread (MixIn) that will
                  serve connections concurrently
                - if the settings change, then another thread
                  will call into this one via stop() to
                  shutdown the (blocking) serve_forever()
                - after serve_forever, effectively restart
                  the loop, checking what values changed, and
                  doing whatever is necessary
                - land back into serve_forever
                - rinse/repeat

        '''
        threading.current_thread().name = 'TwitchBotControl'

        while not self.endthread:
            logging.debug('Starting main loop')

            while not self.isconfigured():
                time.sleep(5)
                if self.endthread:
                    break

            if self.endthread:
                self.stop()
                break
            try:
                self.server = TwitchBot(
                    self.config.cparser.value('twitchbot/username'),
                    self.config.cparser.value('twitchbot/clientid'),
                    self.config.cparser.value('twitchbot/token'),
                    self.config.cparser.value('twitchbot/channel'))
            except Exception as error:  # pylint: disable=broad-except
                logging.error('TwitchBot threw exception on create: %s', error)

            try:
                self.server.start()
            except KeyboardInterrupt:
                pass
            except Exception as error:  # pylint: disable=broad-except
                logging.error('TwitchBot threw exception after forever: %s',
                              error,
                              exc_info=True)
            finally:
                if self.server:
                    self.server.shutdown()

    def isconfigured(self):
        ''' need everything configured! '''
        return bool(
            self.config.cparser.value('twitchbot/enabled', type=bool)
            and self.config.cparser.value('twitchbot/username')
            and self.config.cparser.value('twitchbot/clientid')
            and self.config.cparser.value('twitchbot/token')
            and self.config.cparser.value('twitchbot/channel'))

    def stop(self, signum=None, frame=None):  #pylint: disable=unused-argument
        ''' method to stop the thread '''
        logging.debug('asked to stop or reconfigure')
        if self.server:
            self.server.shutdown()

    def __del__(self):
        logging.debug('thread is being killed!')
        self.endthread = True
        self.stop()


def stop(pid):
    ''' stop this process '''
    logging.info('sending INT to %s', pid)
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        pass


def start(logpath, bundledir):
    ''' multiprocessing start hook '''
    threading.current_thread().name = 'TwitchBot'

    if not bundledir:
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            bundledir = getattr(sys, '_MEIPASS',
                                os.path.abspath(os.path.dirname(__file__)))
        else:
            bundledir = os.path.abspath(os.path.dirname(__file__))

    nowplaying.bootstrap.set_qt_names()
    nowplaying.bootstrap.setuplogging(logpath)

    config = nowplaying.config.ConfigFile(bundledir=bundledir)
    logging.info('boot up')
    twitchbot = TwitchBotHandler(config)  # pylint: disable=unused-variable
    twitchbot.run()


def main():
    ''' integration test '''
    if len(sys.argv) != 5:
        print("Usage: twitchbot <username> <client id> <token> <channel>")
        sys.exit(1)

    username = sys.argv[1]
    client_id = sys.argv[2]
    token = sys.argv[3]
    channel = sys.argv[4]

    bundledir = os.path.abspath(os.path.dirname(__file__))

    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names()
    # need to make sure config is initialized with something
    nowplaying.config.ConfigFile(bundledir=bundledir)
    bot = TwitchBot(username, client_id, token, channel)
    bot.start()


if __name__ == "__main__":
    main()
