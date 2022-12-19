#!/usr/bin/env python3
''' request handling '''

import asyncio
import logging
import pathlib
import re
import sqlite3

import aiosqlite

from PySide6.QtCore import Slot, QFile, QFileSystemWatcher, QStandardPaths  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import QCheckBox, QHeaderView, QTableWidgetItem  # pylint: disable=no-name-in-module
from PySide6.QtUiTools import QUiLoader  # pylint: disable=no-name-in-module

import nowplaying.metadata
from nowplaying.exceptions import PluginVerifyError
from nowplaying.utils import TRANSPARENT_PNG_BIN

USERREQUEST_TEXT = [
    'artist',
    'title',
    'displayname',
    'type',
    'playlist',
    'username',
    'filename',
]

USERREQUEST_BLOB = ['userimage']

REQUEST_WINDOW_FIELDS = [
    'artist', 'title', 'type', 'playlist', 'username', 'filename', 'timestamp',
    'reqid'
]

REQUEST_SETTING_MAPPING = {
    'command': 'Chat Command',
    'twitchtext': 'Twitch Text',
    'type': 'Roulette',
    'displayname': 'Display Name',
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


class Requests:  #pylint: disable=too-many-instance-attributes
    ''' handle requests


        Note that different methods are being called by different parts of the system
        presently.  Should probably split them out between UI/non-UI if possible,
        since UI code can't call async code.

    '''

    def __init__(self, config=None, stopevent=None):
        self.config = config
        self.stopevent = stopevent
        self.filelists = None
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.CacheLocation)[0]).joinpath(
                    'requests', 'request.db')
        self.widgets = None
        self.watcher = None
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

    async def add_to_db(self, data):
        ''' add an entry to the db '''
        if not self.databasefile.exists():
            logging.error('%s does not exist, refusing to add.',
                          self.databasefile)
            return

        if data.get('reqid'):
            reqid = data['reqid']
            del data['reqid']
            del data['username']
            del data['playlist']
            del data['type']
            del data['displayname']
            sql = 'UPDATE userrequest SET ' + '= ? , '.join(data.keys())
            sql += '= ? WHERE reqid=? '
            datatuple = list(data.values()) + [reqid]
        else:
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

    def respin_a_reqid(self, reqid):
        ''' given a reqid, set to respin '''
        if not self.databasefile.exists():
            logging.error('%s does not exist, refusing to respin.',
                          self.databasefile)
            return

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
            logging.error('%s does not exist, refusing to erase.',
                          self.databasefile)
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
            'displayname': setting.get('displayname'),
        }
        if reqid:
            data['reqid'] = reqid
        await self.add_to_db(data)
        return {
            'requester': user,
            'requestdisplayname': setting.get('displayname')
        }

    async def _get_request_lookup(self, sql, datatuple):
        ''' run sql for request '''
        if not self.databasefile.exists():
            logging.error('%s does not exist, refusing to lookup.',
                          self.databasefile)
            return None

        try:
            async with aiosqlite.connect(self.databasefile) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()
                await cursor.execute(sql, datatuple)
                row = await cursor.fetchone()
                if row:
                    self.erase_id(row['reqid'])
                    return {
                        'requester': row['username'],
                        'requesterimageraw': row['userimage'],
                        'requestdisplayname': row['displayname'],
                    }
        except Exception as error:  #pylint: disable=broad-except
            logging.debug(error)
        return None

    async def get_request(self, metadata):
        ''' if a track gets played, finish out the request '''
        if not self.config.cparser.value('settings/requests'):
            return None

        newdata = None
        if metadata.get('filename'):
            logging.debug('trying filename %s', metadata['filename'])
            sql = 'SELECT * FROM userrequest WHERE filename=?'
            datatuple = (metadata['filename'], )
            newdata = await self._get_request_lookup(sql, datatuple)

        if not newdata and metadata.get('artist') and metadata.get('title'):
            logging.debug('trying artist %s / title %s', metadata['artist'],
                          metadata['title'])
            sql = 'SELECT * FROM userrequest WHERE artist=? AND title=? COLLATE NOCASE'
            datatuple = metadata['artist'], metadata['title']

            newdata = await self._get_request_lookup(sql, datatuple)

        if not newdata:
            logging.debug('not a request')
            return None

        if not newdata.get('requesterimageraw'):
            newdata['requesterimageraw'] = TRANSPARENT_PNG_BIN

        return newdata

    async def watch_for_respin(self):
        ''' startup a watcher to handle respins '''
        datatuple = (RESPIN_TEXT, )
        while not self.stopevent.is_set():
            await asyncio.sleep(10)
            if not self.databasefile.exists():
                continue

            try:
                async with aiosqlite.connect(self.databasefile) as connection:
                    connection.row_factory = sqlite3.Row
                    cursor = await connection.cursor()
                    await cursor.execute(
                        'SELECT * from userrequest WHERE filename=? ORDER BY timestamp DESC',
                        datatuple)
                    while row := await cursor.fetchone():
                        logging.debug(
                            'calling user_roulette_request: %s %s %s',
                            row['username'], row['playlist'], row['reqid'])
                        await self.user_roulette_request(
                            {'playlist': row['playlist']}, row['username'], '',
                            row['reqid'])
            except Exception as error:  #pylint: disable=broad-except
                logging.debug(error)

    async def find_command(self, command):
        ''' locate request information based upon a command '''
        setting = {}
        if not command:
            return setting

        for configitem in self.config.cparser.childGroups():
            if 'request-' in configitem:
                tvtext = self.config.cparser.value(f'{configitem}/command')
                if tvtext == command:
                    for key in nowplaying.trackrequests.REQUEST_SETTING_MAPPING:
                        setting[key] = self.config.cparser.value(
                            f'{configitem}/{key}')
                    break
        return setting

    async def find_twitchtext(self, twitchtext):
        ''' locate request information based upon twitchtext '''
        setting = {}
        if not twitchtext:
            return setting

        for configitem in self.config.cparser.childGroups():
            if 'request-' in configitem:
                tvtext = self.config.cparser.value(f'{configitem}/twitchtext')
                if tvtext == twitchtext:
                    for key in nowplaying.trackrequests.REQUEST_SETTING_MAPPING:
                        setting[key] = self.config.cparser.value(
                            f'{configitem}/{key}')
                    break
        return setting

    async def user_track_request(self, setting, user, user_input):
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
            'username': user,
            'artist': artist,
            'title': title,
            'type': 'Generic',
            'displayname': setting.get('displayname')
        }
        await self.add_to_db(data)
        return {
            'requester': user,
            'requestartist': artist,
            'requesttitle': title,
            'requestdisplayname': setting.get('displayname')
        }

    def start_watcher(self):
        ''' start the qfilesystemwatcher '''
        self.watcher = QFileSystemWatcher()
        self.watcher.addPath(str(self.databasefile))
        self.watcher.fileChanged.connect(self.update_window)

    def _connect_request_widgets(self):
        '''  connect request buttons'''
        self.widgets.respin_button.clicked.connect(self.on_respin_button)
        self.widgets.del_button.clicked.connect(self.on_del_button)

    def on_respin_button(self):
        ''' request respin button clicked action '''
        reqidlist = []
        if items := self.widgets.request_table.selectedItems():
            for item in items:
                row = item.row()
                reqidlist.append(
                    self.widgets.request_table.item(row, 7).text())

        for reqid in reqidlist:
            try:
                self.respin_a_reqid(reqid)
            except Exception as error:  #pylint: disable=broad-except
                logging.error(error)

    def on_del_button(self):
        ''' request del button clicked action '''
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
        if not self.databasefile.exists():
            logging.error('%s does not exist, refusing to _get_dataset.',
                          self.databasefile)
            return None

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

    def _request_window_load(self, **kwargs):
        ''' fill in a row on the request window '''
        row = self.widgets.request_table.rowCount()
        self.widgets.request_table.insertRow(row)

        for column, cbtype in enumerate(REQUEST_WINDOW_FIELDS):
            if cbtype == 'displayname':
                continue
            if kwargs.get(cbtype):
                self.widgets.request_table.setItem(
                    row, column, QTableWidgetItem(str(kwargs[cbtype])))
            else:
                self.widgets.request_table.setItem(row, column,
                                                   QTableWidgetItem(''))

    def update_window(self):
        ''' redraw the request window '''
        if not self.config.cparser.value('settings/requests'):
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
            self._request_window_load(**configitem)
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
        self._connect_request_widgets()
        self.update_window()
        self.start_watcher()

    def raise_window(self):
        ''' raise the request window '''
        if not self.config.cparser.value('settings/requests'):
            return
        self.update_window()
        self.widgets.raise_()

    def close_window(self):
        ''' close the request window '''
        if self.widgets:
            self.widgets.hide()
            self.widgets.close()


class RequestSettings:
    ''' for settings UI '''

    def __init__(self):
        self.widget = None

    def connect(self, uihelp, widget):  # pylint: disable=unused-argument
        '''  connect buttons '''
        self.widget = widget
        widget.add_button.clicked.connect(self.on_add_button)
        widget.del_button.clicked.connect(self.on_del_button)

    @staticmethod
    def _row_load(widget, **kwargs):
        row = widget.request_table.rowCount()
        widget.request_table.insertRow(row)

        for column, cbtype in enumerate(
                nowplaying.trackrequests.REQUEST_SETTING_MAPPING):
            if cbtype == 'type':
                if kwargs.get('type') == 'Roulette':
                    checkbox = QCheckBox()
                    checkbox.setChecked(True)
                else:
                    checkbox = QCheckBox()
                    checkbox.setChecked(False)
                widget.request_table.setCellWidget(row, column, checkbox)
            elif kwargs.get(cbtype):
                widget.request_table.setItem(
                    row, column, QTableWidgetItem(str(kwargs.get(cbtype))))
            else:
                widget.request_table.setItem(row, column, QTableWidgetItem(''))
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
            if 'request-' in configitem:
                for key in nowplaying.trackrequests.REQUEST_SETTING_MAPPING:
                    setting[key] = config.cparser.value(f'{configitem}/{key}')
                self._row_load(widget, **setting)

        widget.request_table.resizeColumnsToContents()
        widget.enable_chat_checkbox.setChecked(
            config.cparser.value('twitchbot/chatrequests', type=bool))
        widget.enable_redemptions_checkbox.setChecked(
            config.cparser.value('twitchbot/redemptions', type=bool))
        widget.enable_checkbox.setChecked(
            config.cparser.value('settings/requests', type=bool))

    @staticmethod
    def save(config, widget):
        ''' update the twitch settings '''

        def reset_commands(widget, config):

            for configitem in config.allKeys():
                if 'request-' in configitem:
                    config.remove(configitem)

            rowcount = widget.rowCount()
            for row in range(rowcount):
                for column, cbtype in enumerate(
                        nowplaying.trackrequests.REQUEST_SETTING_MAPPING):
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
                    config.setValue(f'request-{row}/{cbtype}', value)

        config.cparser.setValue('twitchbot/redemptions',
                                widget.enable_redemptions_checkbox.isChecked())
        config.cparser.setValue('twitchbot/chatrequests',
                                widget.enable_chat_checkbox.isChecked())
        config.cparser.setValue('settings/requests',
                                widget.enable_checkbox.isChecked())
        reset_commands(widget.request_table, config.cparser)

    @staticmethod
    def verify(widget):
        ''' verify the settings are good '''

        count = widget.request_table.rowCount()
        for row in range(count):
            item0 = widget.request_table.item(row, 0)
            item1 = widget.request_table.item(row, 1)
            if not item0.text() and not item1.text():
                raise PluginVerifyError(
                    'Request must have either a command or redemption text.')

            if item := widget.request_table.cellWidget(row, 1):
                if item.isChecked():
                    playlistitem = widget.request_table.item(row, 2)
                    if not playlistitem.text():
                        raise PluginVerifyError(
                            'Roulette request has an empty playlist')

    @Slot()
    def on_add_button(self):
        ''' add button clicked action '''
        self._row_load(self.widget)

    @Slot()
    def on_del_button(self):
        ''' del button clicked action '''
        if items := self.widget.request_table.selectedIndexes():
            self.widget.request_table.removeRow(items[0].row())
