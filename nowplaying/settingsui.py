#!/usr/bin/env python3
''' user interface to configure '''

import fnmatch
import logging
import os
import pathlib
import re

# pylint: disable=no-name-in-module
from PySide6.QtCore import Slot, QFile, Qt
from PySide6.QtWidgets import (QCheckBox, QErrorMessage, QFileDialog,
                               QListWidgetItem, QTableWidgetItem, QWidget)
from PySide6.QtGui import QIcon
from PySide6.QtUiTools import QUiLoader
import PySide6.QtXml  # pylint: disable=unused-import, import-error

import nowplaying.config
import nowplaying.hostmeta
from nowplaying.exceptions import PluginVerifyError
try:
    import nowplaying.qtrc  # pylint: disable=import-error, no-name-in-module
except ModuleNotFoundError:
    pass
import nowplaying.utils

# needs to match ui file
TWITCHBOT_CHECKBOXES = [
    'anyone', 'broadcaster', 'moderator', 'subscriber', 'founder', 'conductor',
    'vip', 'bits'
]


# settings UI
class SettingsUI(QWidget):  # pylint: disable=too-many-public-methods
    ''' create settings form window '''

    def __init__(self, tray, version):

        self.config = nowplaying.config.ConfigFile()
        self.iconfile = self.config.iconfile
        self.tray = tray
        self.version = version
        super().__init__()
        self.qtui = None
        self.errormessage = None
        self.widgets = {}
        self.load_qtui()

        if not self.config.iconfile:
            self.tray.cleanquit()
        self.qtui.setWindowIcon(QIcon(str(self.iconfile)))

    def load_qtui(self):
        ''' load the base UI and wire it up '''

        def _load_ui(name):
            ''' load a UI file into a widget '''
            loader = QUiLoader()
            path = self.config.uidir.joinpath(f'{name}_ui.ui')
            if not path.exists():
                return None

            ui_file = QFile(str(path))
            ui_file.open(QFile.ReadOnly)
            try:
                qwidget = loader.load(ui_file)
            except RuntimeError as error:
                logging.warning('Unable to load the UI for %s: %s', name,
                                error)
            ui_file.close()
            return qwidget

        self.qtui = _load_ui('settings')

        baseuis = [
            'general', 'source', 'filter', 'webserver', 'twitchbot',
            'artistextras', 'obsws', 'quirks'
        ]

        pluginuis = {}
        pluginuinames = []
        for plugintype, pluginlist in self.config.plugins.items():
            pluginuis[plugintype] = []
            for key in pluginlist:
                pkey = key.replace(f'nowplaying.{plugintype}.', '')
                pluginuis[plugintype].append(pkey)
                pluginuinames.append(f'{plugintype}_{pkey}')

        for uiname in baseuis + pluginuinames + ['about']:
            self.widgets[uiname] = _load_ui(f'{uiname}')
            if not self.widgets[uiname]:
                continue
            try:
                qobject_connector = getattr(self, f'_connect_{uiname}_widget')
                qobject_connector(self.widgets[uiname])
            except AttributeError:
                pass

            self.qtui.settings_stack.addWidget(self.widgets[uiname])
            self._load_list_item(f'{uiname}', self.widgets[uiname])

        for uiname in pluginuinames:
            if 'inputs' not in uiname or not self.widgets[uiname]:
                continue
            displayname = self.widgets[uiname].property('displayName')
            if not displayname:
                displayname = uiname.split('_')[1].capitalize()
            self.widgets['source'].sourcelist.addItem(displayname)
            self.widgets['source'].sourcelist.currentRowChanged.connect(
                self._set_source_description)

        self._connect_plugins()

        self.qtui.settings_list.currentRowChanged.connect(
            self._set_stacked_display)
        self.qtui.cancel_button.clicked.connect(self.on_cancel_button)
        self.qtui.reset_button.clicked.connect(self.on_reset_button)
        self.qtui.save_button.clicked.connect(self.on_save_button)
        self.errormessage = QErrorMessage(self.qtui)
        curbutton = self.qtui.settings_list.findItems('general',
                                                      Qt.MatchContains)
        if curbutton:
            self.qtui.settings_list.setCurrentItem(curbutton[0])

    def _load_list_item(self, name, qobject):
        displayname = qobject.property('displayName')
        if not displayname:
            if '_' in name:
                displayname = name.split('_')[1].capitalize()
            else:
                displayname = name.capitalize()
        self.qtui.settings_list.addItem(displayname)

    def _set_stacked_display(self, index):
        self.qtui.settings_stack.setCurrentIndex(index)

    def _connect_webserver_widget(self, qobject):
        ''' file in the hostname/ip and connect the template button'''

        data = nowplaying.hostmeta.gethostmeta()

        if data['hostfqdn']:
            qobject.hostname_label.setText(data['hostfqdn'])
        if data['hostip']:
            qobject.hostip_label.setText(data['hostip'])

        qobject.template_button.clicked.connect(self.on_html_template_button)

    def _connect_general_widget(self, qobject):
        ''' connect the general buttons to non-built-ins '''
        qobject.texttemplate_button.clicked.connect(
            self.on_text_template_button)
        qobject.textoutput_button.clicked.connect(self.on_text_saveas_button)

    def _connect_artistextras_widget(self, qobject):
        ''' connect the artistextras buttons to non-built-ins '''
        qobject.clearcache_button.clicked.connect(
            self.on_artistextras_clearcache_button)

    def _connect_obsws_widget(self, qobject):
        ''' connect obsws button to template picker'''
        qobject.template_button.clicked.connect(self.on_obsws_template_button)

    def _connect_twitchbot_widget(self, qobject):
        '''  connect twitchbot announce to template picker'''
        qobject.announce_button.clicked.connect(
            self.on_twitchbot_announce_button)
        qobject.add_button.clicked.connect(self.on_twitchbot_add_button)
        qobject.del_button.clicked.connect(self.on_twitchbot_del_button)

    def _connect_filter_widget(self, qobject):
        '''  connect regex filter to template picker'''
        qobject.add_recommended_button.clicked.connect(
            self.on_filter_add_recommended_button)
        qobject.test_button.clicked.connect(self.on_filter_test_button)
        qobject.add_button.clicked.connect(self.on_filter_regex_add_button)
        qobject.del_button.clicked.connect(self.on_filter_regex_del_button)

    def _connect_plugins(self):
        ''' tell config to trigger plugins to update windows '''
        self.config.plugins_connect_settingsui(self.widgets)

    def _set_source_description(self, index):
        item = self.widgets['source'].sourcelist.item(index)
        plugin = item.text().lower()
        self.config.plugins_description('inputs', plugin,
                                        self.widgets['source'].description)

    def upd_win(self):
        ''' update the settings window '''
        self.config.get()
        self.widgets['about'].program_label.setText(
            f'<html><head/><body><p><img src="{self.iconfile}"/>'
            f'<span style=" font-size:14pt;"> Now Playing v{self.version}'
            '</span></p></body></html>')

        self.widgets['general'].textoutput_lineedit.setText(self.config.file)
        self.widgets['general'].texttemplate_lineedit.setText(
            self.config.txttemplate)

        self.widgets['general'].delay_lineedit.setText(
            str(self.config.cparser.value('settings/delay')))
        self.widgets['general'].notify_checkbox.setChecked(self.config.notif)
        self.widgets['general'].setlist_checkbox.setChecked(
            self.config.cparser.value('setlist/enabled', type=bool))

        self._upd_win_artistextras()
        self._upd_win_filters()
        self._upd_win_recognition()
        self._upd_win_input()
        self._upd_win_plugins()
        self._upd_win_webserver()
        self._upd_win_obsws()
        self._upd_win_twitchbot()
        self._upd_win_quirks()

    def _upd_win_artistextras(self):
        self.widgets['artistextras'].artistextras_checkbox.setChecked(
            self.config.cparser.value('artistextras/enabled', type=bool))
        self.widgets['artistextras'].missingfanart_checkbox.setChecked(
            self.config.cparser.value('artistextras/coverfornofanart',
                                      type=bool))
        self.widgets['artistextras'].missinglogos_checkbox.setChecked(
            self.config.cparser.value('artistextras/coverfornologos',
                                      type=bool))
        self.widgets['artistextras'].missingthumbs_checkbox.setChecked(
            self.config.cparser.value('artistextras/coverfornothumbs',
                                      type=bool))

        for art in [
                'banners', 'processes', 'fanart', 'logos', 'thumbnails',
                'sizelimit'
        ]:
            guiattr = getattr(self.widgets['artistextras'], f'{art}_spin')
            guiattr.setValue(
                self.config.cparser.value(f'artistextras/{art}', type=int))

    def _upd_win_filters(self):
        ''' update the filter settings '''
        self.widgets['filter'].stripextras_checkbox.setChecked(
            self.config.cparser.value('settings/stripextras', type=bool))

        self.widgets['filter'].regex_list.clear()

        for configitem in self.config.cparser.allKeys():
            if 'regex_filter/' in configitem:
                self._filter_regex_load(
                    regex=self.config.cparser.value(configitem))

    def _upd_win_recognition(self):
        self.widgets['general'].recog_title_checkbox.setChecked(
            self.config.cparser.value('recognition/replacetitle', type=bool))
        self.widgets['general'].recog_artist_checkbox.setChecked(
            self.config.cparser.value('recognition/replaceartist', type=bool))
        self.widgets['general'].recog_artistwebsites_checkbox.setChecked(
            self.config.cparser.value('recognition/replaceartistwebsites',
                                      type=bool))

    def _upd_win_input(self):
        ''' this is totally wrong and will need to get dealt
            with as part of ui code redesign '''
        currentinput = self.config.cparser.value('settings/input')
        if curbutton := self.widgets['source'].sourcelist.findItems(
                currentinput, Qt.MatchContains):
            self.widgets['source'].sourcelist.setCurrentItem(curbutton[0])

    def _upd_win_webserver(self):
        ''' update the webserver settings to match config '''
        self.widgets['webserver'].enable_checkbox.setChecked(
            self.config.cparser.value('weboutput/httpenabled', type=bool))
        self.widgets['webserver'].port_lineedit.setText(
            str(self.config.cparser.value('weboutput/httpport')))
        self.widgets['webserver'].template_lineedit.setText(
            self.config.cparser.value('weboutput/htmltemplate'))
        self.widgets['webserver'].once_checkbox.setChecked(
            self.config.cparser.value('weboutput/once', type=bool))

    def _upd_win_obsws(self):
        ''' update the obsws settings to match config '''
        self.widgets['obsws'].enable_checkbox.setChecked(
            self.config.cparser.value('obsws/enabled', type=bool))
        self.widgets['obsws'].source_lineedit.setText(
            self.config.cparser.value('obsws/source'))
        self.widgets['obsws'].host_lineedit.setText(
            self.config.cparser.value('obsws/host'))
        self.widgets['obsws'].port_lineedit.setText(
            str(self.config.cparser.value('obsws/port')))
        self.widgets['obsws'].secret_lineedit.setText(
            self.config.cparser.value('obsws/secret'))
        self.widgets['obsws'].template_lineedit.setText(
            self.config.cparser.value('obsws/template'))

    def _upd_win_twitchbot(self):
        ''' update the twitch settings '''

        def clear_table(widget):
            widget.clearContents()
            rows = widget.rowCount()
            for row in range(rows, -1, -1):
                widget.removeRow(row)

        clear_table(self.widgets['twitchbot'].command_perm_table)

        for configitem in self.config.cparser.childGroups():
            setting = {}
            if 'twitchbot-command-' in configitem:
                command = configitem.replace('twitchbot-command-', '')
                setting['command'] = command
                for box in TWITCHBOT_CHECKBOXES:
                    setting[box] = self.config.cparser.value(
                        f'{configitem}/{box}', defaultValue=False, type=bool)
                self._twitchbot_command_load(**setting)

        self.widgets['twitchbot'].enable_checkbox.setChecked(
            self.config.cparser.value('twitchbot/enabled', type=bool))
        self.widgets['twitchbot'].clientid_lineedit.setText(
            self.config.cparser.value('twitchbot/clientid'))
        self.widgets['twitchbot'].channel_lineedit.setText(
            self.config.cparser.value('twitchbot/channel'))
        self.widgets['twitchbot'].username_lineedit.setText(
            self.config.cparser.value('twitchbot/username'))
        self.widgets['twitchbot'].token_lineedit.setText(
            self.config.cparser.value('twitchbot/token'))
        self.widgets['twitchbot'].announce_lineedit.setText(
            self.config.cparser.value('twitchbot/announce'))
        self.widgets['twitchbot'].commandchar_lineedit.setText(
            self.config.cparser.value('twitchbot/commandchar'))
        self.widgets['twitchbot'].announce_delay_lineedit.setText(
            self.config.cparser.value('twitchbot/announcedelay'))

    def _upd_win_quirks(self):
        ''' update the quirks settings to match config '''

        # file system notification method
        if self.config.cparser.value('quirks/pollingobserver', type=bool):
            self.widgets['quirks'].fs_events_button.setChecked(False)
            self.widgets['quirks'].fs_poll_button.setChecked(True)
        else:
            self.widgets['quirks'].fs_events_button.setChecked(True)
            self.widgets['quirks'].fs_poll_button.setChecked(False)

        # s,in,out,g
        self.widgets['quirks'].song_subst_checkbox.setChecked(
            self.config.cparser.value('quirks/filesubst', type=bool))
        self.widgets['quirks'].song_in_path_lineedit.setText(
            self.config.cparser.value('quirks/filesubstin'))
        self.widgets['quirks'].song_out_path_lineedit.setText(
            self.config.cparser.value('quirks/filesubstout'))

        slashmode = self.config.cparser.value('quirks/slashmode')

        if not slashmode:
            slashmode = 'nochange'

        if slashmode == 'nochange':
            self.widgets['quirks'].slash_nochange.setChecked(True)
            self.widgets['quirks'].slash_toback.setChecked(False)
            self.widgets['quirks'].slash_toforward.setChecked(False)

        if slashmode == 'toforward':
            self.widgets['quirks'].slash_nochange.setChecked(False)
            self.widgets['quirks'].slash_toback.setChecked(False)
            self.widgets['quirks'].slash_toforward.setChecked(True)

        if slashmode == 'toback':
            self.widgets['quirks'].slash_nochange.setChecked(False)
            self.widgets['quirks'].slash_toback.setChecked(True)
            self.widgets['quirks'].slash_toforward.setChecked(False)

    def _upd_win_plugins(self):
        ''' tell config to trigger plugins to update windows '''
        self.config.plugins_load_settingsui(self.widgets)

    def disable_web(self):
        ''' if the web server gets in trouble, this gets called '''
        self.upd_win()
        self.widgets['webserver'].enable_checkbox.setChecked(False)
        self.upd_conf()
        self.errormessage.showMessage(
            'HTTP Server settings are invalid. Bad port?')

    def disable_obsws(self):
        ''' if the OBS WebSocket gets in trouble, this gets called '''
        self.upd_win()
        self.widgets['obsws'].enable_checkbox.setChecked(False)
        self.upd_conf()
        self.upd_win()
        self.errormessage.showMessage(
            'OBS WebServer settings are invalid. Bad port? Wrong password?')

    def upd_conf(self):
        ''' update the configuration '''

        self.config.cparser.setValue(
            'settings/delay', self.widgets['general'].delay_lineedit.text())
        loglevel = self.widgets['general'].logging_combobox.currentText()
        self.config.cparser.setValue(
            'setlist/enabled',
            self.widgets['general'].setlist_checkbox.isChecked())

        self._upd_conf_input()

        self.config.put(
            initialized=True,
            file=self.widgets['general'].textoutput_lineedit.text(),
            txttemplate=self.widgets['general'].texttemplate_lineedit.text(),
            notif=self.widgets['general'].notify_checkbox.isChecked(),
            loglevel=loglevel)

        logging.getLogger().setLevel(loglevel)

        self._upd_conf_artistextras()
        self._upd_conf_filters()
        self._upd_conf_recognition()
        self._upd_conf_input()
        self._upd_conf_webserver()
        self._upd_conf_obsws()
        self._upd_conf_twitchbot()
        self._upd_conf_quirks()
        self._upd_conf_plugins()
        self.config.cparser.sync()

    def _upd_conf_artistextras(self):
        self.config.cparser.setValue(
            'artistextras/enabled',
            self.widgets['artistextras'].artistextras_checkbox.isChecked())
        self.config.cparser.setValue(
            'artistextras/coverfornofanart',
            self.widgets['artistextras'].missingfanart_checkbox.isChecked())
        self.config.cparser.setValue(
            'artistextras/coverfornologos',
            self.widgets['artistextras'].missinglogos_checkbox.isChecked())
        self.config.cparser.setValue(
            'artistextras/coverfornothumbs',
            self.widgets['artistextras'].missingthumbs_checkbox.isChecked())

        for art in [
                'banners', 'processes', 'fanart', 'logos', 'thumbnails',
                'fanartdelay'
        ]:
            guiattr = getattr(self.widgets['artistextras'], f'{art}_spin')
            self.config.cparser.setValue(f'artistextras/{art}',
                                         guiattr.value())

    def _upd_conf_recognition(self):
        self.config.cparser.setValue(
            'recognition/replacetitle',
            self.widgets['general'].recog_title_checkbox.isChecked())
        self.config.cparser.setValue(
            'recognition/replaceartist',
            self.widgets['general'].recog_artist_checkbox.isChecked())
        self.config.cparser.setValue(
            'recognition/replaceartistwebsites',
            self.widgets['general'].recog_artistwebsites_checkbox.isChecked())

    def _upd_conf_input(self):
        ''' find the text of the currently selected handler '''
        if curbutton := self.widgets['source'].sourcelist.currentItem():
            inputtext = curbutton.text().lower()
            self.config.cparser.setValue('settings/input', inputtext)

    def _upd_conf_plugins(self):
        ''' tell config to trigger plugins to update '''
        self.config.plugins_save_settingsui(self.widgets)

    def _upd_conf_webserver(self):
        ''' update the webserver settings '''
        # Check to see if our web settings changed
        # from what we initially had.  if so
        # need to trigger the webthread to reset
        # itself.  Hitting stop makes it go through
        # the loop again

        oldenabled = self.config.cparser.value('weboutput/httpenabled',
                                               type=bool)
        oldport = self.config.cparser.value('weboutput/httpport', type=int)

        httpenabled = self.widgets['webserver'].enable_checkbox.isChecked()
        httpport = int(self.widgets['webserver'].port_lineedit.text())

        self.config.cparser.setValue('weboutput/httpenabled', httpenabled)
        self.config.cparser.setValue('weboutput/httpport', httpport)
        self.config.cparser.setValue(
            'weboutput/htmltemplate',
            self.widgets['webserver'].template_lineedit.text())
        self.config.cparser.setValue(
            'weboutput/once',
            self.widgets['webserver'].once_checkbox.isChecked())

        if oldenabled != httpenabled or oldport != httpport:
            self.tray.subprocesses.restart_webserver()

    def _upd_conf_obsws(self):
        ''' update the obsws settings '''

        oldenabled = self.config.cparser.value('obsws/enabled', type=bool)
        newenabled = self.widgets['obsws'].enable_checkbox.isChecked()

        self.config.cparser.setValue(
            'obsws/source', self.widgets['obsws'].source_lineedit.text())
        self.config.cparser.setValue(
            'obsws/host', self.widgets['obsws'].host_lineedit.text())
        self.config.cparser.setValue(
            'obsws/port', self.widgets['obsws'].port_lineedit.text())
        self.config.cparser.setValue(
            'obsws/secret', self.widgets['obsws'].secret_lineedit.text())
        self.config.cparser.setValue(
            'obsws/template', self.widgets['obsws'].template_lineedit.text())
        self.config.cparser.setValue('obsws/enabled', newenabled)

        if oldenabled != newenabled:
            self.tray.subprocesses.restart_obsws()

    def verify_regex_filters(self):
        ''' verify the regex filters are real '''
        widget = self.widgets['filter'].regex_list

        rowcount = widget.count()
        for row in range(rowcount):
            item = self.widgets['filter'].regex_list.item(row).text()
            try:
                re.compile(item)
            except re.error as error:
                self.errormessage.showMessage(
                    f'Filter error with \'{item}\': {error.msg}')
                return False
        return True

    def _upd_conf_filters(self):
        ''' update the filter settings '''

        def reset_filters(widget, config):

            for configitem in config.allKeys():
                if 'regex_filter/' in configitem:
                    config.remove(configitem)

            rowcount = widget.count()
            for row in range(rowcount):
                item = widget.item(row)
                config.setValue(f'regex_filter/{row}', item.text())

        if not self.verify_regex_filters():
            return

        self.config.cparser.setValue(
            'settings/stripextras',
            self.widgets['filter'].stripextras_checkbox.isChecked())
        reset_filters(self.widgets['filter'].regex_list, self.config.cparser)

    def _upd_conf_twitchbot(self):
        ''' update the twitch settings '''

        def reset_commands(widget, config):

            for configitem in config.allKeys():
                if 'twitchbot-command-' in configitem:
                    config.remove(configitem)

            rowcount = widget.rowCount()
            for row in range(rowcount):
                item = widget.item(row, 0)
                cmd = item.text()
                cmd = f'twitchbot-command-{cmd}'
                for column, cbtype in enumerate(TWITCHBOT_CHECKBOXES):
                    item = widget.cellWidget(row, column + 1)
                    value = item.isChecked()
                    config.setValue(f'{cmd}/{cbtype}', value)

        oldenabled = self.config.cparser.value('twitchbot/enabled', type=bool)
        newenabled = self.widgets['twitchbot'].enable_checkbox.isChecked()

        self.config.cparser.setValue('twitchbot/enabled', newenabled)
        self.config.cparser.setValue(
            'twitchbot/clientid',
            self.widgets['twitchbot'].clientid_lineedit.text())
        self.config.cparser.setValue(
            'twitchbot/channel',
            self.widgets['twitchbot'].channel_lineedit.text())
        self.config.cparser.setValue(
            'twitchbot/username',
            self.widgets['twitchbot'].username_lineedit.text())
        self.config.cparser.setValue(
            'twitchbot/token', self.widgets['twitchbot'].token_lineedit.text())
        self.config.cparser.setValue(
            'twitchbot/announce',
            self.widgets['twitchbot'].announce_lineedit.text())
        self.config.cparser.setValue(
            'twitchbot/commandchar',
            self.widgets['twitchbot'].commandchar_lineedit.text())

        self.config.cparser.setValue(
            'twitchbot/announcedelay',
            self.widgets['twitchbot'].announce_delay_lineedit.text())

        reset_commands(self.widgets['twitchbot'].command_perm_table,
                       self.config.cparser)

        if oldenabled != newenabled:
            self.tray.subprocesses.restart_twitchbot()

    def _upd_conf_quirks(self):
        ''' update the quirks settings to match config '''

        # file system notification method
        self.config.cparser.value(
            'quirks/pollingobserver',
            self.widgets['quirks'].fs_poll_button.isChecked())

        # s,in,out,g
        self.config.cparser.setValue(
            'quirks/filesubst',
            self.widgets['quirks'].song_subst_checkbox.isChecked())

        if self.widgets['quirks'].slash_toback.isChecked():
            self.config.cparser.setValue('quirks/slashmode', 'toback')
        if self.widgets['quirks'].slash_toforward.isChecked():
            self.config.cparser.setValue('quirks/slashmode', 'toforward')
        if self.widgets['quirks'].slash_nochange.isChecked():
            self.config.cparser.setValue('quirks/slashmode', 'nochange')

        self.config.cparser.setValue(
            'quirks/filesubstin',
            self.widgets['quirks'].song_in_path_lineedit.text())
        self.config.cparser.setValue(
            'quirks/filesubstout',
            self.widgets['quirks'].song_out_path_lineedit.text())

    @Slot()
    def on_text_saveas_button(self):
        ''' file button clicked action '''
        if startfile := self.widgets['general'].textoutput_lineedit.text():
            startdir = os.path.dirname(startfile)
        else:
            startdir = '.'
        if filename := QFileDialog.getSaveFileName(self, 'Open file', startdir,
                                                   '*.txt'):
            self.widgets['general'].textoutput_lineedit.setText(filename[0])

    @Slot()
    def on_artistextras_clearcache_button(self):
        ''' clear the cache button was pushed '''
        cachedbfile = self.config.cparser.value('artistextras/cachedbfile')
        if not cachedbfile:
            return

        cachedbfilepath = pathlib.Path(cachedbfile)
        if cachedbfilepath.exists() and 'imagecache' in str(cachedbfile):
            logging.debug('Deleting %s', cachedbfilepath)
            cachedbfilepath.unlink()

    def template_picker(self, startfile=None, startdir=None, limit='*.txt'):
        ''' generic code to pick a template file '''
        if startfile:
            startdir = os.path.dirname(startfile)
        elif not startdir:
            startdir = os.path.join(self.config.templatedir, "templates")
        if filename := QFileDialog.getOpenFileName(self.qtui, 'Open file',
                                                   startdir, limit):
            return filename[0]
        return None

    def template_picker_lineedit(self, qwidget, limit='*.txt'):
        ''' generic code to pick a template file '''
        if filename := self.template_picker(startfile=qwidget.text(),
                                            limit=limit):
            qwidget.setText(filename)

    @Slot()
    def on_text_template_button(self):
        ''' file template button clicked action '''
        self.template_picker_lineedit(
            self.widgets['general'].texttemplate_lineedit)

    @Slot()
    def on_obsws_template_button(self):
        ''' obsws template button clicked action '''
        self.template_picker_lineedit(self.widgets['obsws'].template_lineedit)

    @Slot()
    def on_html_template_button(self):
        ''' html template button clicked action '''
        self.template_picker_lineedit(
            self.widgets['webserver'].template_lineedit, limit='*.htm *.html')

    @Slot()
    def on_twitchbot_announce_button(self):
        ''' twitchbot announce button clicked action '''
        self.template_picker_lineedit(
            self.widgets['twitchbot'].announce_lineedit,
            limit='twitchbot_*.txt')

    def _twitchbot_command_load(self, command=None, **kwargs):
        if not command:
            return

        row = self.widgets['twitchbot'].command_perm_table.rowCount()
        self.widgets['twitchbot'].command_perm_table.insertRow(row)
        cmditem = QTableWidgetItem(command)
        self.widgets['twitchbot'].command_perm_table.setItem(row, 0, cmditem)

        checkbox = []
        for column, cbtype in enumerate(TWITCHBOT_CHECKBOXES):  # pylint: disable=unused-variable
            checkbox = QCheckBox()
            if cbtype in kwargs:
                checkbox.setChecked(kwargs[cbtype])
            else:
                checkbox.setChecked(True)
            self.widgets['twitchbot'].command_perm_table.setCellWidget(
                row, column + 1, checkbox)

    @Slot()
    def on_twitchbot_add_button(self):
        ''' twitchbot add button clicked action '''
        filename = self.template_picker(limit='twitchbot_*.txt')
        if not filename:
            return

        filename = os.path.basename(filename)
        filename = filename.replace('twitchbot_', '')
        command = filename.replace('.txt', '')

        self._twitchbot_command_load(command)

    @Slot()
    def on_twitchbot_del_button(self):
        ''' twitchbot del button clicked action '''
        if items := self.widgets[
                'twitchbot'].command_perm_table.selectedIndexes():
            self.widgets['twitchbot'].command_perm_table.removeRow(
                items[0].row())

    def _filter_regex_load(self, regex=None):
        ''' setup the filter table '''
        regexitem = QListWidgetItem()
        if regex:
            regexitem.setText(regex)
        regexitem.setFlags(Qt.ItemIsEditable
                           | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled
                           | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        self.widgets['filter'].regex_list.addItem(regexitem)

    @Slot()
    def on_filter_regex_add_button(self):
        ''' filter add button clicked action '''
        self._filter_regex_load('new')

    @Slot()
    def on_filter_regex_del_button(self):
        ''' filter del button clicked action '''
        if items := self.widgets['filter'].regex_list.selectedItems():
            for item in items:
                self.widgets['filter'].regex_list.takeItem(
                    self.widgets['filter'].regex_list.row(item))

    @Slot()
    def on_filter_test_button(self):
        ''' filter add button clicked action '''

        if not self.verify_regex_filters():
            return

        title = self.widgets['filter'].test_lineedit.text()
        striprelist = []
        rowcount = self.widgets['filter'].regex_list.count()
        for row in range(rowcount):
            item = self.widgets['filter'].regex_list.item(row).text()
            striprelist.append(re.compile(item))
        result = nowplaying.utils.titlestripper_advanced(
            title=title, title_regex_list=striprelist)
        self.widgets['filter'].result_label.setText(result)
        result = nowplaying.utils.titlestripper_advanced(
            title=title, title_regex_list=self.config.getregexlist())
        self.widgets['filter'].existing_label.setText(result)
        self.widgets['filter'].result_label.update()

    @Slot()
    def on_filter_add_recommended_button(self):
        ''' load some recommended settings '''
        stripworldlist = ['clean', 'dirty', 'explicit', 'official music video']
        joinlist = '|'.join(stripworldlist)

        self._filter_regex_load(f' \\((?i:{joinlist})\\)')
        self._filter_regex_load(f' - (?i:{joinlist}$)')
        self._filter_regex_load(f' \\[(?i:{joinlist})\\]')

    @Slot()
    def on_cancel_button(self):
        ''' cancel button clicked action '''
        if self.tray:
            self.tray.action_config.setEnabled(True)
        self.upd_win()
        self.qtui.close()

        if not self.config.file:
            self.tray.cleanquit()

    @Slot()
    def on_reset_button(self):
        ''' cancel button clicked action '''
        self.config.reset()
        SettingsUI.httpenabled = self.config.cparser.value(
            'weboutput/httpenabled', type=bool)
        SettingsUI.httpport = self.config.cparser.value('weboutput/httpport',
                                                        type=int)
        self.upd_win()

    @Slot()
    def on_save_button(self):
        ''' save button clicked action '''
        inputtext = None
        if curbutton := self.widgets['source'].sourcelist.currentItem():
            inputtext = curbutton.text().lower()

        try:
            self.config.plugins_verify_settingsui(inputtext, self.widgets)
        except PluginVerifyError as error:
            self.errormessage.showMessage(error.message)
            return

        if self.widgets['general'].textoutput_lineedit.text() == "":
            self.errormessage.showMessage('File to write is required')
            return

        if not self.verify_regex_filters():
            return

        self.config.unpause()
        self.upd_conf()
        self.close()
        self.tray.fix_mixmode_menu()
        self.tray.action_pause.setText('Pause')
        self.tray.action_pause.setEnabled(True)

    def show(self):
        ''' show the system tram '''
        if self.tray:
            self.tray.action_config.setEnabled(False)
        self.upd_win()
        self.qtui.show()
        self.qtui.setFocus()

    def close(self):
        ''' close the system tray '''
        self.tray.action_config.setEnabled(True)
        self.qtui.hide()

    def exit(self):
        ''' exit the tray '''
        self.qtui.close()


def update_twitchbot_commands(config):
    ''' make sure all twitchbot_ files have a config entry '''
    filelist = os.listdir(config.templatedir)
    existing = config.cparser.childGroups()

    for file in filelist:
        if not fnmatch.fnmatch(file, 'twitchbot_*.txt'):
            continue

        command = file.replace('twitchbot_', '').replace('.txt', '')
        command = f'twitchbot-command-{command}'

        if command not in existing:
            config.cparser.setValue('settings/newtwitchbot', True)
            logging.debug('creating %s', command)
            for box in TWITCHBOT_CHECKBOXES:
                config.cparser.setValue(f'{command}/{box}', False)
