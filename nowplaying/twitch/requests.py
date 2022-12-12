#!/usr/bin/env python3
''' twitch request handling '''

import asyncio
import logging
import pathlib
import re
import sqlite3

import requests
import aiosqlite  # pylint: disable=import-error

from twitchAPI.pubsub import PubSub
from twitchAPI.helper import first
from twitchAPI.types import AuthScope

from PySide6.QtCore import Slot, QFile, QFileSystemWatcher, QStandardPaths  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import QCheckBox, QHeaderView, QTableWidgetItem  # pylint: disable=no-name-in-module
from PySide6.QtUiTools import QUiLoader  # pylint: disable=no-name-in-module

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
from nowplaying.exceptions import PluginVerifyError
import nowplaying.metadata
import nowplaying.version

USER_SCOPE = [
    AuthScope.CHANNEL_READ_REDEMPTIONS, AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT
]

USERREQUEST_TEXT = [
    'artist',
    'title',
    'type',
    'playlist',
    'username',
    'filename',
]

USERREQUEST_BLOB = ['userimage']

REQUEST_SETTING_MAPPING = {
    'request': 'Twitch Text',
    'type': 'Roulette',
    'playlist': 'Playlist File'
}

RESPIN_TEXT = 'RESPIN SCHEDULED'
'''
Auto-detected formats:

artist - "title"
artist - "title" for someone
"title" - artist
"title" by artist for someone
"title"
artist

... and strips all excess whitespace

'''

ARTIST_TITLE_RE = re.compile(r'^s*(.*)\s+[-]+\s+"(.*)"\s*(for .*)*$')
TITLE_ARTIST_RE = re.compile(r'^s*"(.*)"\s+[-by]+\s+"(.*)\s*(for .*)*$')
TITLE_RE = re.compile(r'^s*"(.*)"\s*(for .*)*$')


class TwitchRequests:  #pylint: disable=too-many-instance-attributes
    ''' handle twitch requests


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
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.CacheLocation)[0]).joinpath(
                    'twitchrequests', 'request.db')
        self.widgets = None
        self.watcher = None
        self.twitch = None
        if not self.databasefile.exists():
            self.setupdb()

    def setupdb(self):
        ''' setup the database file for keeping track of requests '''
        logging.debug('Setting up the database %s', self.databasefile)
        self.databasefile.parent.mkdir(parents=True, exist_ok=True)
        if self.databasefile.exists():
            self.databasefile.unlink()

        with sqlite3.connect(self.databasefile) as connection:
            cursor = connection.cursor()
            sql = 'CREATE TABLE IF NOT EXISTS userrequest ('
            sql += ' TEXT, '.join(USERREQUEST_TEXT) + ' TEXT, '
            sql += ' BLOB, '.join(USERREQUEST_BLOB) + ' BLOB, '
            sql += 'reqid INTEGER PRIMARY KEY AUTOINCREMENT,'
            sql += 'timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)'
            cursor.execute(sql)
            connection.commit()

    async def _add_to_db(self, data):
        if data.get('reqid'):
            reqid = data['reqid']
            del data['reqid']
            del data['username']
            del data['playlist']
            del data['type']
            sql = 'UPDATE userrequest SET '
            sql += '= ? , '.join(data.keys())
            sql += '= ? WHERE reqid=? '
            datatuple = list(data.values()) + [reqid]
        else:
            try:
                user = await first(
                    self.twitch.get_users(logins=[data['username']]))
                req = requests.get(user.profile_image_url, timeout=5)
                data['userimage'] = nowplaying.utils.image2png(req.content)
            except Exception as error:  #pylint: disable=broad-except
                logging.debug(error)
                data['userimage'] = None
            sql = 'INSERT OR REPLACE INTO userrequest ('
            sql += ', '.join(data.keys()) + ') VALUES ('
            sql += '?,' * (len(data.keys()) - 1) + '?)'
            datatuple = tuple(list(data.values()))

        try:
            async with aiosqlite.connect(self.databasefile) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()
                await cursor.execute(sql, datatuple)
                await connection.commit()

        except sqlite3.OperationalError as error:
            logging.debug(error)

    def _respin_a_reqid(self, reqid):
        sql = 'UPDATE userrequest SET filename=? WHERE reqid=?'
        try:
            with sqlite3.connect(self.databasefile) as connection:
                connection.row_factory = sqlite3.Row
                cursor = connection.cursor()
                datatuple = RESPIN_TEXT, reqid
                cursor.execute(sql, datatuple)
                connection.commit()
        except sqlite3.OperationalError as error:
            logging.debug(error)

    def erase_id(self, reqid):
        ''' remove entry from requests '''
        if not self.databasefile.exists():
            return

        with sqlite3.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute('DELETE FROM userrequest WHERE reqid=?;',
                               (reqid, ))
                connection.commit()
            except sqlite3.OperationalError:
                return

    async def user_roulette_request(self,
                                    user,
                                    playlist,
                                    user_input,
                                    reqid=None):
        ''' roulette request '''
        logging.debug('%s requested roulette %s | %s', user, playlist,
                      user_input)

        plugin = self.config.cparser.value('settings/input')
        roulette = await self.config.pluginobjs['inputs'][
            f'nowplaying.inputs.{plugin}'].getrandomtrack(playlist)
        metadata = await nowplaying.metadata.MetadataProcessors(
            config=self.config
        ).getmoremetadata(metadata={'filename': roulette}, skipplugins=True)
        data = {
            'username': user,
            'artist': metadata.get('artist'),
            'filename': metadata['filename'],
            'title': metadata.get('title'),
            'type': 'Roulette',
            'playlist': playlist,
        }
        if reqid:
            data['reqid'] = reqid
        await self._add_to_db(data)

    async def get_request(self, metadata):
        ''' if a track gets played, finish out the request '''
        if metadata.get('filename'):
            sql = 'SELECT * FROM userrequest WHERE filename=?'
            datatuple = [
                metadata['filename'],
            ]
        elif metadata.get('artist') and metadata.get('title'):
            sql = 'SELECT * FROM userrequest WHERE artist=? AND title=?'
            datatuple = [
                metadata['artist'],
                metadata['title'],
            ]
        else:
            return None
        sql += ' ORDER BY timestamp ASC LIMIT 1'

        try:
            async with aiosqlite.connect(self.databasefile) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()
                await cursor.execute(
                    'SELECT * from userrequest WHERE filename=?', datatuple)
                row = await cursor.fetchone()
                if row:
                    self.erase_id(row['reqid'])
                    return {
                        'requester': row['username'],
                        'requesterimageraw': row['userimage'],
                    }
        except Exception as error:  #pylint: disable=broad-except
            logging.debug(error)
        return None

    async def _watch_for_respin(self):
        datatuple = (RESPIN_TEXT, )
        while not self.stopevent.is_set():
            await asyncio.sleep(10)
            try:
                async with aiosqlite.connect(self.databasefile) as connection:
                    connection.row_factory = sqlite3.Row
                    cursor = await connection.cursor()
                    await cursor.execute(
                        'SELECT * from userrequest WHERE filename=? ORDER BY timestamp ASC',
                        datatuple)
                    while row := await cursor.fetchone():
                        logging.debug(
                            'calling user_roulette_request: %s %s %s',
                            row['username'], row['playlist'], row['reqid'])
                        await self.user_roulette_request(
                            row['username'], row['playlist'], '', row['reqid'])
            except Exception as error:  #pylint: disable=broad-except
                logging.debug(error)

    async def user_track_request(self, user, user_input):
        ''' generic request '''
        logging.debug('%s generic requested %s', user, user_input)
        artist = None
        title = None
        if match := ARTIST_TITLE_RE.search(user_input):
            artist = match.group(1)
            title = match.group(2)
        elif match := TITLE_ARTIST_RE.search(user_input):
            title = match.group(1)
            artist = match.group(2)
        elif match := TITLE_RE.search(user_input):
            title = match.group(1)
        else:
            artist = user_input
        data = {
            'user': user,
            'artist': artist,
            'title': title,
            'type': 'Generic',
        }
        await self._add_to_db(data)

    async def callback_redemption(self, uuid, data):  # pylint: disable=unused-argument
        ''' handle the channel point redemption '''
        redemptitle = data['data']['redemption']['reward']['title']
        user = data['data']['redemption']['user']['display_name']
        if data['data']['redemption'].get('user_input'):
            user_input = data['data']['redemption'].get('user_input')
        else:
            user_input = None

        for configitem in self.config.cparser.childGroups():
            if 'twitchbot-request-' in configitem:
                setting = {
                    'request': configitem.replace('twitchbot-request-', '')
                }
                for key in REQUEST_SETTING_MAPPING:
                    setting[key] = self.config.cparser.value(
                        f'{configitem}/{key}')
                if redemptitle == setting['request']:
                    if setting.get('type') == 'Generic':
                        await self.user_track_request(user, user_input)
                    elif setting.get('type') == 'Roulette':
                        await self.user_roulette_request(
                            user, setting.get('playlist'), user_input)

    async def run_request(self, twitch=None):
        ''' twitch requests '''

        if not self.config.cparser.value('twitchbot/requests', type=bool):
            logging.error('Twitch requests have not been enabled. Exiting.')

        if not twitch:
            logging.error('No Twitch credentials to start requests. Exiting.')
            return

        loop = asyncio.get_running_loop()
        loop.create_task(self._watch_for_respin())
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

    def start_watcher(self):
        ''' start the qfilesystemwatcher '''
        self.watcher = QFileSystemWatcher()
        self.watcher.addPath(str(self.databasefile))
        self.watcher.fileChanged.connect(self.update_window)

    def _connect_twitchrequest_widgets(self):
        '''  connect twitch request'''
        self.widgets.respin_button.clicked.connect(self.on_respin_button)
        self.widgets.del_button.clicked.connect(self.on_del_button)

    def on_respin_button(self):
        ''' twitch request respin button clicked action '''
        reqidlist = []
        if items := self.widgets.request_table.selectedItems():
            for item in items:
                row = item.row()
                reqidlist.append(
                    self.widgets.request_table.item(row, 7).text())

        for reqid in reqidlist:
            try:
                self._respin_a_reqid(reqid)
            except Exception as error:  #pylint: disable=broad-except
                logging.error(error)

    def on_del_button(self):
        ''' twitch request del button clicked action '''
        reqidlist = []
        if items := self.widgets.request_table.selectedItems():
            for item in items:
                row = item.row()
                reqidlist.append(
                    self.widgets.request_table.item(row, 7).text())

        for reqid in reqidlist:
            try:
                self.erase_id(reqid)
            except Exception as error:  #pylint: disable=broad-except
                logging.error(error)

    def _get_dataset(self):
        ''' get the current request list for display '''
        with sqlite3.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute('''SELECT * FROM userrequest''')
            except sqlite3.OperationalError:
                return None

            dataset = cursor.fetchall()
            if not dataset:
                return None
        return dataset

    def _twitch_request_load(self, **kwargs):
        ''' fill in a row on the request window '''
        row = self.widgets.request_table.rowCount()
        self.widgets.request_table.insertRow(row)

        for column, cbtype in enumerate(USERREQUEST_TEXT +
                                        ['timestamp', 'reqid']):
            if not kwargs.get(cbtype):
                continue
            self.widgets.request_table.setItem(
                row, column, QTableWidgetItem(str(kwargs[cbtype])))

    def update_window(self):
        ''' redraw the request window '''
        if not self.databasefile.exists():
            return

        def clear_table(widget):
            widget.clearContents()
            rows = widget.rowCount()
            for row in range(rows, -1, -1):
                widget.removeRow(row)

        dataset = self._get_dataset()
        clear_table(self.widgets.request_table)

        if not dataset:
            return

        for configitem in dataset:
            self._twitch_request_load(**configitem)
        self.widgets.request_table.horizontalHeader().ResizeMode(
            QHeaderView.Stretch)
        self.widgets.request_table.resizeColumnsToContents()
        self.widgets.request_table.adjustSize()
        self.widgets.adjustSize()
        self.widgets.show()

    def initial_ui(self):
        ''' load the UI '''
        uipath = self.config.uidir.joinpath('request_window.ui')
        loader = QUiLoader()
        ui_file = QFile(str(uipath))
        ui_file.open(QFile.ReadOnly)
        self.widgets = loader.load(ui_file)
        self.widgets.setLayout(self.widgets.window_layout)
        self.widgets.request_table.horizontalHeader().ResizeMode(
            QHeaderView.Stretch)
        ui_file.close()
        self._connect_twitchrequest_widgets()
        self.update_window()
        self.start_watcher()

    def raise_window(self):
        ''' raise the request window '''
        self.update_window()
        self.widgets.raise_()

    def close_window(self):
        ''' close the request window '''
        if self.widgets:
            self.widgets.hide()
            self.widgets.close()

    async def stop(self):
        ''' stop the twitch request support '''
        if self.pubsub:
            await self.pubsub.unlisten(self.uuid)
            self.pubsub.stop()


class TwitchRequestSettings:
    ''' for settings UI '''

    def __init__(self):
        self.widget = None

    def connect(self, uihelp, widget):  # pylint: disable=unused-argument
        '''  connect twitchbot '''
        self.widget = widget
        widget.add_button.clicked.connect(self.on_add_button)
        widget.del_button.clicked.connect(self.on_del_button)

    @staticmethod
    def _row_load(widget, **kwargs):
        row = widget.request_table.rowCount()
        widget.request_table.insertRow(row)

        for column, cbtype in enumerate(REQUEST_SETTING_MAPPING):
            if cbtype == 'type':
                if kwargs.get('type') == 'Roulette':
                    checkbox = QCheckBox()
                    checkbox.setChecked(True)
                else:
                    checkbox = QCheckBox()
                    checkbox.setChecked(False)
                widget.request_table.setCellWidget(row, column, checkbox)
            else:
                widget.request_table.setItem(
                    row, column, QTableWidgetItem(str(kwargs.get(cbtype))))
        widget.request_table.resizeColumnsToContents()

    def load(self, config, widget):
        ''' load the settings window '''

        def clear_table(widget):
            widget.clearContents()
            rows = widget.rowCount()
            for row in range(rows, -1, -1):
                widget.removeRow(row)

        clear_table(widget.request_table)

        for configitem in config.cparser.childGroups():
            setting = {}
            if 'twitchbot-request-' in configitem:
                setting['request'] = configitem.replace(
                    'twitchbot-request-', '')
                for key in REQUEST_SETTING_MAPPING:
                    setting[key] = config.cparser.value(f'{configitem}/{key}')
                self._row_load(widget, **setting)

        widget.request_table.resizeColumnsToContents()
        widget.enable_checkbox.setChecked(
            config.cparser.value('twitchbot/requests', type=bool))

    @staticmethod
    def save(config, widget):
        ''' update the twitch settings '''

        def reset_commands(widget, config):

            for configitem in config.allKeys():
                if 'twitchbot-request-' in configitem:
                    config.remove(configitem)

            rowcount = widget.rowCount()
            for row in range(rowcount):
                item = widget.item(row, 0)
                cmd = item.text()
                cmd = f'twitchbot-request-{cmd}'
                for column, cbtype in enumerate(REQUEST_SETTING_MAPPING):
                    if cbtype == 'type':
                        item = widget.cellWidget(row, column)
                        checkv = item.isChecked()
                        if checkv:
                            value = "Roulette"
                        else:
                            value = "Generic"
                    else:
                        item = widget.item(row, column)
                        if not item:
                            continue
                        value = item.text()
                    config.setValue(f'{cmd}/{cbtype}', value)

        config.cparser.setValue('twitchbot/requests',
                                widget.enable_checkbox.isChecked())

        reset_commands(widget.request_table, config.cparser)

    @staticmethod
    def verify(widget):
        ''' verify the settings are good '''
        count = widget.request_table.rowCount()

        for row in range(count):
            text = widget.request_table.item(row, 0).text()
            if not text:
                raise PluginVerifyError('Twitch Redemption Text is empty')
            if item := widget.request_table.cellWidget(row, 1):
                if item.isChecked():
                    playlistitem = widget.request_table.item(row, 2)
                    if not playlistitem.text():
                        raise PluginVerifyError(
                            f'Twitch Redemption {text} empty playlist')

    @Slot()
    def on_add_button(self):
        ''' twitchbot add button clicked action '''
        self._row_load(self.widget,
                       request='New',
                       type='Roulette',
                       playlist='Playlist name')

    @Slot()
    def on_del_button(self):
        ''' twitchbot del button clicked action '''
        if items := self.widget.request_table.selectedIndexes():
            self.widget.request_table.removeRow(items[0].row())
