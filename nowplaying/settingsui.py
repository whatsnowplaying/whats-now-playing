#!/usr/bin/env python3
''' user interface to configure '''

import logging
import os
import pathlib
import socket

from PySide2.QtCore import Slot, QFile, Qt  # pylint: disable=no-name-in-module
from PySide2.QtWidgets import QErrorMessage, QFileDialog, QWidget  # pylint: disable=no-name-in-module
from PySide2.QtGui import QIcon  # pylint: disable=no-name-in-module
from PySide2.QtUiTools import QUiLoader  # pylint: disable=no-name-in-module
import PySide2.QtXml  # pylint: disable=unused-import, import-error, no-name-in-module

import nowplaying.config


# settings UI
class SettingsUI(QWidget):
    ''' create settings form window '''

    # Need to keep track of these values get changed by the
    # user.  These will get set in init.  If these values
    # change, then trigger the webthread to reset itself
    # to pick up the new values...
    httpenabled = None
    httpport = None

    def __init__(self, tray, version):

        self.config = nowplaying.config.ConfigFile()
        self.iconfile = self.config.iconfile
        self.tray = tray
        self.version = version
        super(SettingsUI, self).__init__()
        self.qtui = None
        self.errormessage = None
        self.widgets = {}
        self.load_qtui()

        if not self.config.iconfile:
            self.tray.cleanquit()
        self.qtui.setWindowIcon(QIcon(self.iconfile))

        SettingsUI.httpenabled = self.config.cparser.value(
            'weboutput/httpenabled', type=bool)
        SettingsUI.httpport = self.config.cparser.value('weboutput/httpport',
                                                        type=int)

        # make connections. Note that radio button flipping, etc
        # should be in the ui file itself

    def load_qtui(self):
        ''' load the base UI and wire it up '''
        def _load_ui(name):
            ''' load a UI file into a widget '''
            loader = QUiLoader()
            path = os.path.join(self.config.uidir, f'{name}_ui.ui')
            ui_file = QFile(path)
            ui_file.open(QFile.ReadOnly)
            qwidget = loader.load(ui_file)
            ui_file.close()
            return qwidget

        self.qtui = _load_ui('settings')

        baseuis = ['general', 'source', 'webserver', 'obsws']
        pluginuis = [
            key.replace('nowplaying.inputs.', '')
            for key in self.config.plugins.keys()
        ]

        for uiname in baseuis + pluginuis:
            self.widgets[uiname] = _load_ui(f'{uiname}')
            try:
                qobject_connector = getattr(self, f'_connect_{uiname}_widget')
                qobject_connector(self.widgets[uiname])
            except AttributeError:
                pass

            self.qtui.settings_stack.addWidget(self.widgets[uiname])
            self._load_list_item(f'{uiname}', self.widgets[uiname])

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
            displayname = name.capitalize()
        self.qtui.settings_list.addItem(displayname)

    def _set_stacked_display(self, index):
        self.qtui.settings_stack.setCurrentIndex(index)

    def _connect_webserver_widget(self, qobject):
        ''' file in the hostname/ip and connect the template button'''
        try:
            hostname = socket.gethostname()
            hostip = socket.gethostbyname(hostname)
        except:  # pylint: disable = bare-except
            pass

        if hostname:
            qobject.hostname_label.setText(hostname)
        if hostip:
            qobject.hostip_label.setText(hostip)

        qobject.template_button.clicked.connect(self.on_html_template_button)

    def _connect_general_widget(self, qobject):
        ''' connect the general buttons to non-built-ins '''
        qobject.texttemplate_button.clicked.connect(
            self.on_text_template_button)
        qobject.textoutput_button.clicked.connect(self.on_text_saveas_button)

    def _connect_serato_widget(self, qobject):
        ''' connect serato local dir button '''
        qobject.local_dir_button.clicked.connect(self.on_serato_lib_button)

    def _connect_obsws_widget(self, qobject):
        ''' connect serato tab to non-built-ins.  UI file
            properly enables/disables based upon local/remote '''

        qobject.template_button.clicked.connect(self.on_obsws_template_button)

    def _connect_source_widget(self, qobject):
        ''' populate the input group box '''
        for text in ['Serato', 'MPRIS2']:
            qobject.sourcelist.addItem(text)
        qobject.sourcelist.currentRowChanged.connect(
            self._set_source_description)

    def _set_source_description(self, index):
        item = self.widgets['source'].sourcelist.item(index)
        plugin = item.text().lower()
        self.config.plugins_description(plugin,
                                        self.widgets['source'].description)

    def upd_win(self):
        ''' update the settings window '''
        self.config.get()

        self.widgets['general'].textoutput_lineedit.setText(self.config.file)
        self.widgets['general'].texttemplate_lineedit.setText(
            self.config.txttemplate)

        self.widgets['serato'].remote_poll_lineedit.setText(
            str(self.config.interval))
        self.widgets['general'].read_delay_lineedit.setText(
            str(self.config.delay))
        self.widgets['general'].notify_checkbox.setChecked(self.config.notif)

        self._upd_win_input()
        self._upd_win_plugins()
        self._upd_win_webserver()
        self._upd_win_obsws()

    def _upd_win_input(self):
        ''' this is totally wrong and will need to get dealt
            with as part of ui code redesign '''
        currentinput = self.config.cparser.value('settings/input')
        curbutton = self.widgets['source'].sourcelist.findItems(
            currentinput, Qt.MatchContains)
        if curbutton:
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
        if self.config.cparser.value('obsws/freetype2', type=bool):
            self.widgets['obsws'].freetype2_button.setChecked(True)
            self.widgets['obsws'].gdi_button.setChecked(False)
        else:
            self.widgets['obsws'].freetype2_button.setChecked(False)
            self.widgets['obsws'].gdi_button.setChecked(True)

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

    def _upd_win_plugins(self):
        ''' tell config to trigger plugins to update windows '''
        self.config.plugins_load_settingsui(self.widgets)

    def disable_web(self):
        ''' if the web server gets in trouble, this gets called '''
        self.widgets['webserver'].enable_checkbox.setChecked(False)
        self.upd_conf()
        self.upd_win()
        self.errormessage.showMessage(
            'HTTP Server settings are invalid. Bad port?')

    def disable_obsws(self):
        ''' if the OBS WebSocket gets in trouble, this gets called '''
        self.widgets['obsws'].enable_checkbox.setChecked(False)
        self.upd_conf()
        self.upd_win()
        self.errormessage.showMessage(
            'OBS WebServer settings are invalid. Bad port? Wrong password?')

    def upd_conf(self):
        ''' update the configuration '''

        interval = float(self.widgets['serato'].remote_poll_lineedit.text())
        delay = float(self.widgets['general'].read_delay_lineedit.text())
        loglevel = self.widgets['general'].logging_combobox.currentText()

        self._upd_conf_input()

        self.config.put(
            initialized=True,
            file=self.widgets['general'].textoutput_lineedit.text(),
            txttemplate=self.widgets['general'].texttemplate_lineedit.text(),
            interval=interval,
            delay=delay,
            notif=self.widgets['general'].notify_checkbox.isChecked(),
            loglevel=loglevel)

        logging.getLogger().setLevel(loglevel)

        self._upd_conf_input()
        self._upd_conf_webserver()
        self._upd_conf_obsws()
        self._upd_conf_plugins()

    def _upd_conf_input(self):
        ''' find the text of the currently selected handler '''
        curbutton = self.widgets['source'].sourcelist.currentItem()
        if curbutton:
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


        if SettingsUI.httpport != httpport or \
           SettingsUI.httpenabled != httpenabled:
            self.tray.restart_webprocess()
            SettingsUI.httpport = httpport
            SettingsUI.httpenabled = httpenabled

    def _upd_conf_obsws(self):
        ''' update the obsws settings '''
        self.config.cparser.setValue(
            'obsws/freetype2',
            self.widgets['obsws'].freetype2_button.isChecked())
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
        self.config.cparser.setValue(
            'obsws/enabled', self.widgets['obsws'].enable_checkbox.isChecked())

    @Slot()
    def on_text_saveas_button(self):
        ''' file button clicked action '''
        startfile = self.widgets['general'].textoutput_lineedit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = '.'
        filename = QFileDialog.getSaveFileName(self, 'Open file', startdir,
                                               '*.txt')
        if filename:
            self.widgets['general'].textoutput_lineedit.setText(filename[0])

    @Slot()
    def on_text_template_button(self):
        ''' file button clicked action '''
        startfile = self.widgets['general'].texttemplate_lineedit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = os.path.join(self.config.getbundledir(), "templates")
        filename = QFileDialog.getOpenFileName(self.qtui, 'Open file',
                                               startdir, '*.txt')
        if filename:
            self.widgets['general'].texttemplate_lineedit.setText(filename[0])

    @Slot()
    def on_obsws_template_button(self):
        ''' file button clicked action '''
        startfile = self.widgets['obsws'].template_lineedit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = os.path.join(self.config.getbundledir(), "templates")
        filename = QFileDialog.getOpenFileName(self.qtui, 'Open file',
                                               startdir, '*.txt')
        if filename:
            self.widgets['obsws'].template_lineedit.setText(filename[0])

    @Slot()
    def on_serato_lib_button(self):
        ''' lib button clicked action'''
        startdir = self.widgets['serato'].local_dir_lineedit.text()
        if not startdir:
            startdir = str(pathlib.Path.home())
        libdir = QFileDialog.getExistingDirectory(self.qtui,
                                                  'Select directory', startdir)
        if libdir:
            self.widgets['serato'].local_dir_lineedit.setText(libdir)

    @Slot()
    def on_html_template_button(self):
        ''' file button clicked action '''
        startfile = self.widgets['webserver'].template_lineedit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = os.path.join(self.config.getbundledir(), "templates")
        filename = QFileDialog.getOpenFileName(self.qtui, 'Open file',
                                               startdir, '*.htm *.html')
        if filename:
            self.widgets['webserver'].template_lineedit.setText(filename[0])

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
        curbutton = self.widgets['source'].sourcelist.currentItem()
        if curbutton:
            inputtext = curbutton.text().lower()

        if inputtext == 'serato':
            if self.widgets['serato'].remote_button.isChecked() and (
                    'https://serato.com/playlists' not in
                    self.self.widgets['serato'].remote_url_lineedit.text()
                    and 'https://www.serato.com/playlists'
                    not in self.widgets['serato'].remote_url_lineedit.text()
                    or len(self.widgets['serato'].remote_url_lineedit.text()) <
                    30):
                self.errormessage.showMessage(
                    'Serato Live Playlist URL is invalid')
                return

            if self.widgets['serato'].local_button.isChecked() and (
                    '_Serato_'
                    not in self.widgets['serato'].local_dir_lineedit.text()):
                self.errormessage.showMessage(
                    r'Serato Library Path is required.  Should point to "\_Serato\_" folder'
                )
                return

        if self.widgets['general'].textoutput_lineedit.text() == "":
            self.errormessage.showMessage('File to write is required')
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
