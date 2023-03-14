#!/usr/bin/env python3
''' A _very_ simple and incomplete parser for Serato Live session files '''

import logging
import os
import pathlib
import sqlite3

import aiosqlite

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

from nowplaying.exceptions import PluginVerifyError
from .m3u import Plugin as M3UPlugin

PLAYLIST = ['name', 'filename']


class Plugin(M3UPlugin):
    ''' handler for NowPlaying '''

    def __init__(self, config=None, m3udir=None, qsettings=None):
        super().__init__(config=config, m3udir=m3udir, qsettings=qsettings)
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.CacheLocation)[0]).joinpath(
                    'virtualdj', 'virtualdj.db')
        self.database = None

    def initdb(self):
        ''' initialize the db '''
        if not self.databasefile.exists():
            self.rewrite_db()

    @staticmethod
    def _write_playlist(sqlcursor, playlist, filelist):
        ''' take the collections XML and save the playlists off '''
        sql = 'INSERT INTO playlists (name,filename) VALUES (?,?)'
        for filename in filelist:
            datatuple = playlist, filename
            sqlcursor.execute(sql, datatuple)

    def rewrite_db(self, playlistdir=None):
        ''' erase and update the old db '''
        if not playlistdir:
            playlistdir = self.config.cparser.value('virtualdj/playlists')

        if not playlistdir:
            logging.error('VDJ Playlists not defined')
            return

        playlistdirpath = pathlib.Path(playlistdir)
        if not playlistdirpath.exists():
            logging.error('playlistdir (%s) does not exist', playlistdir)
            return

        self.databasefile.parent.mkdir(parents=True, exist_ok=True)
        if self.databasefile.exists():
            self.databasefile.unlink()

        with sqlite3.connect(self.databasefile) as connection:
            cursor = connection.cursor()
            sql = 'CREATE TABLE IF NOT EXISTS playlists ('
            sql += ' TEXT, '.join(PLAYLIST) + ' TEXT, '
            sql += 'id INTEGER PRIMARY KEY AUTOINCREMENT)'
            cursor.execute(sql)
            connection.commit()

            for filepath in list(playlistdirpath.rglob('*.m3u')):
                logging.debug('Reading %s', filepath)
                content = self._read_full_file(filepath)
                self._write_playlist(cursor, filepath.stem, content)
            connection.commit()

    def install(self):
        ''' locate Virtual DJ '''
        vdjdir = pathlib.Path.home().joinpath('Documents', 'VirtualDJ')
        if vdjdir.exists():
            self.config.cparser.value('settings/input', 'virtualdj')
            self.config.cparser.value('virtualdj/history',
                                      str(vdjdir.joinpath('History')))
            self.config.cparser.value('virtualdj/playlists',
                                      str(vdjdir.joinpath('Playlists')))
            return True

        return False

    async def start(self):
        ''' setup the watcher to run in a separate thread '''
        await self.setup_watcher('virtualdj/history')

    async def getplayingtrack(self):
        ''' wrapper to call getplayingtrack '''

        # just in case called without calling start...
        await self.start()
        return Plugin.metadata

    async def getrandomtrack(self, playlist):
        ''' return the contents of a playlist '''
        async with aiosqlite.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute(
                    '''SELECT filename FROM playlists WHERE name=? ORDER BY random() LIMIT 1''',
                    (playlist, ))
            except sqlite3.OperationalError as error:
                logging.error(error)
                return None

            row = await cursor.fetchone()
            if not row:
                logging.debug('no match')
                return None
            return row['filename']

    async def stop(self):
        ''' stop the m3u plugin '''
        self._reset_meta()
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def defaults(self, qsettings):
        ''' (re-)set the default configuration values for this plugin '''
        vdjdir = pathlib.Path.home().joinpath('Documents', 'VirtualDJ')
        qsettings.setValue('virtualdj/history',
                           str(vdjdir.joinpath('History')))
        qsettings.setValue('virtualdj/playlists',
                           str(vdjdir.joinpath('Playlists')))

    def on_playlist_reread_button(self):
        ''' user clicked re-read collections '''
        self.rewrite_db(playlistdir=self.qwidget.playlistdir_lineedit.text())

    def on_playlistdir_button(self):
        ''' filename button clicked action'''
        startdir = self.qwidget.playlistdir_lineedit.text()
        if not startdir:
            startdir = str(pathlib.Path.home().joinpath(
                'Documents', 'VirtualDJ'))
        if filename := QFileDialog.getExistingDirectory(
                self.qwidget, 'Select directory', startdir):
            self.qwidget.playlistdir_lineedit.setText(filename[0])

    def on_history_dir_button(self):
        ''' filename button clicked action'''
        if self.qwidget.historydir_lineedit.text():
            startdir = self.qwidget.historydir_lineedit.text()
        else:
            startdir = str(pathlib.Path.home().joinpath(
                'Documents', 'VirtualDJ', 'History'))
        if dirname := QFileDialog.getExistingDirectory(self.qwidget,
                                                       'Select directory',
                                                       startdir):
            self.qwidget.historydir_lineedit.setText(dirname)

    def connect_settingsui(self, qwidget, uihelp):
        ''' connect m3u button to filename picker'''
        self.qwidget = qwidget
        self.uihelp = uihelp
        qwidget.historydir_button.clicked.connect(self.on_history_dir_button)
        qwidget.playlistdir_button.clicked.connect(self.on_playlistdir_button)
        qwidget.playlist_reread_button.clicked.connect(
            self.on_playlist_reread_button)

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        qwidget.historydir_lineedit.setText(
            self.config.cparser.value('virtualdj/history'))
        qwidget.playlistdir_lineedit.setText(
            self.config.cparser.value('virtualdj/playlists'))

    def verify_settingsui(self, qwidget):
        ''' verify settings '''
        if not os.path.exists(qwidget.historydir_lineedit.text()):
            raise PluginVerifyError(
                r'Virtual DJ History directory must exist.')
        if not os.path.exists(qwidget.playlistdir_lineedit.text()):
            raise PluginVerifyError(
                r'Virtual DJ Playlists directory must exist.')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('virtualdj/history',
                                     qwidget.historydir_lineedit.text())
        self.config.cparser.setValue('virtualdj/playlists',
                                     qwidget.playlistdir_lineedit.text())

    def desc_settingsui(self, qwidget):
        ''' description '''
        qwidget.setText('For Virtual DJ Support')
