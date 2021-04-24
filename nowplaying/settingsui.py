#!/usr/bin/env python3
''' user interface to configure '''

import logging
import os
import pathlib
import socket

from PySide2.QtCore import Slot, QFile  # pylint: disable=no-name-in-module
from PySide2.QtWidgets import QFileDialog, QWidget  # pylint: disable=no-name-in-module
from PySide2.QtGui import QIcon  # pylint: disable=no-name-in-module
from PySide2.QtUiTools import QUiLoader  # pylint: disable=no-name-in-module
import PySide2.QtXml  # pylint: disable=unused-import, import-error, no-name-in-module

import nowplaying.config


# settings UI
class SettingsUI(QWidget):  #pylint: disable=too-many-public-methods
    ''' create settings form window '''

    # Need to keep track of these values get changed by the
    # user.  These will get set in init.  If these values
    # change, then trigger the webthread to reset itself
    # to pick up the new values...
    httpdir = None
    httpenabled = None
    httpport = None

    def __init__(self, tray, version):

        self.config = nowplaying.config.ConfigFile()
        self.iconfile = self.config.iconfile
        self.tray = tray
        self.version = version
        super(SettingsUI, self).__init__()
        self.load_qtui()

        if not self.config.iconfile:
            self.tray.cleanquit()
        self.qtui.setWindowIcon(QIcon(self.iconfile))

        SettingsUI.httpenabled = self.config.httpenabled
        SettingsUI.httpport = self.config.httpport
        SettingsUI.httpdir = self.config.httpdir

        try:
            hostname = socket.gethostname()
            hostip = socket.gethostbyname(hostname)
        except:  # pylint: disable = bare-except
            hostname = 'Unknown Hostname'
            hostip = 'Unknown IP'

        self.qtui.network_info_label.setText(
            f'Hostname: {hostname} / IP: {hostip}')

        # make connections. Note that radio button flipping, etc
        # should be in the ui file itself

        self.connect_general_tab()
        self.connect_webserver_tab()
        self.connect_serato_tab()

    def load_qtui(self):
        ''' Load the QtDesigner UI file '''
        loader = QUiLoader()
        path = os.path.join(self.config.uifile)
        ui_file = QFile(path)
        ui_file.open(QFile.ReadOnly)
        self.qtui = loader.load(ui_file)
        ui_file.close()

    def connect_general_tab(self):
        ''' hook up the general tab to non-built-ins '''
        self.qtui.cancel_button.clicked.connect(self.on_cancel_button)
        self.qtui.reset_button.clicked.connect(self.on_reset_button)
        self.qtui.save_button.clicked.connect(self.on_save_button)

        self.qtui.text_template_button.clicked.connect(
            self.on_text_template_button)
        self.qtui.text_saveas_button.clicked.connect(
            self.on_text_saveas_button)

    def connect_webserver_tab(self):
        ''' connect webserver tab to non-built-ins. Note that
            the UI file does the enable/disable of the fields here
            based upon the Enable button '''
        self.qtui.http_serverpath_button.clicked.connect(
            self.on_httpdirbutton_clicked)
        self.qtui.html_template_button.clicked.connect(
            self.on_html_template_button)

    def connect_serato_tab(self):
        ''' connect serato tab to non-built-ins.  UI file
            properly enables/disables based upon local/remote '''

        self.qtui.serato_local_browsebutton.clicked.connect(
            self.on_serato_lib_button)

    def connect_obsws_tab(self):
        ''' connect serato tab to non-built-ins.  UI file
            properly enables/disables based upon local/remote '''

        self.qtui.obsws_template_button.clicked.connect(
            self.on_obsws_template_button)

    def upd_win(self):
        ''' update the settings window '''
        self.config.get()

        if self.config.local:
            self.qtui.serato_local_button.setChecked(True)
            self.qtui.serato_remote_button.setChecked(False)
        else:
            self.qtui.serato_local_button.setChecked(False)
            self.qtui.serato_remote_button.setChecked(True)
        self.qtui.serato_local_lineedit.setText(self.config.libpath)
        self.qtui.serato_remote_url_lineedit.setText(self.config.url)
        self.qtui.text_filename_lineedit.setText(self.config.file)
        self.qtui.text_template_lineedit.setText(self.config.txttemplate)
        self.qtui.http_enable_checkbox.setChecked(self.config.httpenabled)
        self.qtui.http_port_lineedit.setText(str(self.config.httpport))
        self.qtui.http_serverpath_lineedit.setText(self.config.httpdir)
        self.qtui.html_template_lineedit.setText(self.config.htmltemplate)
        self.qtui.serato_remote_poll_lineedit.setText(str(
            self.config.interval))
        self.qtui.read_delay_lineedit.setText(str(self.config.delay))
        self.qtui.notification_checkbox.setChecked(self.config.notif)

        self.upd_win_obsws()

    def upd_win_obsws(self):
        ''' update the obsws settings to match config '''
        self.qtui.obsws_enable_checkbox.setChecked(
            self.config.cparser.value('obsws/enabled', type=bool))
        if self.config.cparser.value('obsws/freetype2', type=bool):
            self.qtui.obsws_freetype2_button.setChecked(True)
            self.qtui.obsws_gdi_button.setChecked(False)
        else:
            self.qtui.obsws_freetype2_button.setChecked(False)
            self.qtui.obsws_gdi_button.setChecked(True)

        self.qtui.obsws_source_lineedit.setText(
            self.config.cparser.value('obsws/source'))
        self.qtui.obsws_host_lineedit.setText(
            self.config.cparser.value('obsws/host'))
        self.qtui.obsws_port_lineedit.setText(
            self.config.cparser.value('obsws/port'))
        self.qtui.obsws_secret_lineedit.setText(
            self.config.cparser.value('obsws/secret'))
        self.qtui.obsws_template_lineedit.setText(
            self.config.cparser.value('obsws/template'))

    def disable_web(self):
        ''' if the web server gets in trouble, this gets called '''
        self.qtui.error_label.setText(
            'HTTP Server settings are invalid. Bad port? Wrong directory?')
        self.qtui.http_enable_checkbox.setChecked(False)
        self.upd_win()
        self.upd_conf()

    def disable_obsws(self):
        ''' if the OBS WebSocket gets in trouble, this gets called '''
        self.qtui.error_label.setText(
            'OBS WebServer settings are invalid. Bad port? Wrong password?')
        #self.qtui.http_enable_checkbox.setChecked(False)
        self.upd_win()
        self.upd_conf()

    def upd_conf(self):
        ''' update the configuration '''

        #
        # These all need special/more handling at some point
        #
        httpenabled = self.qtui.http_enable_checkbox.isChecked()
        httpport = int(self.qtui.http_port_lineedit.text())
        httpdir = self.qtui.http_serverpath_lineedit.text()
        interval = float(self.qtui.serato_remote_poll_lineedit.text())
        delay = float(self.qtui.read_delay_lineedit.text())
        loglevel = self.qtui.logging_level_combobox.currentText()

        self.config.put(initialized=True,
                        local=self.qtui.serato_local_button.isChecked(),
                        libpath=self.qtui.serato_local_lineedit.text(),
                        url=self.qtui.serato_remote_url_lineedit.text(),
                        file=self.qtui.text_filename_lineedit.text(),
                        txttemplate=self.qtui.text_template_lineedit.text(),
                        httpport=httpport,
                        httpdir=httpdir,
                        httpenabled=httpenabled,
                        htmltemplate=self.qtui.html_template_lineedit.text(),
                        interval=interval,
                        delay=delay,
                        notif=self.qtui.notification_checkbox.isChecked(),
                        loglevel=loglevel)

        logging.getLogger().setLevel(loglevel)

        self.upd_conf_obsws()

        # Check to see if our web settings changed
        # from what we initially had.  if so
        # need to trigger the webthread to reset
        # itself.  Hitting stop makes it go through
        # the loop again
        if SettingsUI.httpport != httpport or \
           SettingsUI.httpenabled != httpenabled or \
           SettingsUI.httpdir != httpdir:
            self.tray.webthread.stop()
            SettingsUI.httpport = httpport
            SettingsUI.httpenabled = httpenabled
            SettingsUI.httpdir = httpdir

    def upd_conf_obsws(self):
        ''' update the obsws settings '''
        self.config.cparser.setValue(
            'obsws/freetype2', self.qtui.obsws_freetype2_button.isChecked())
        self.config.cparser.setValue('obsws/source',
                                     self.qtui.obsws_source_lineedit.text())
        self.config.cparser.setValue('obsws/host',
                                     self.qtui.obsws_host_lineedit.text())
        self.config.cparser.setValue('obsws/port',
                                     self.qtui.obsws_port_lineedit.text())
        self.config.cparser.setValue('obsws/secret',
                                     self.qtui.obsws_secret_lineedit.text())
        self.config.cparser.setValue('obsws/template',
                                     self.qtui.obsws_template_lineedit.text())
        self.config.cparser.setValue(
            'obsws/enabled', self.qtui.obsws_enable_checkbox.isChecked())

    @Slot()
    def on_text_saveas_button(self):
        ''' file button clicked action '''
        startfile = self.qtui.text_filename_lineedit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = '.'
        filename = QFileDialog.getSaveFileName(self, 'Open file', startdir,
                                               '*.txt')
        if filename:
            self.qtui.text_filename_lineedit.setText(filename[0])

    @Slot()
    def on_text_template_button(self):
        ''' file button clicked action '''
        startfile = self.qtui.text_template_lineedit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = os.path.join(self.config.BUNDLEDIR, "templates")
        filename = QFileDialog.getOpenFileName(self.qtui, 'Open file',
                                               startdir, '*.txt')
        if filename:
            self.qtui.text_template_lineedit.setText(filename[0])

    @Slot()
    def on_obsws_template_button(self):
        ''' file button clicked action '''
        startfile = self.qtui.obsws_template_lineedit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = os.path.join(self.config.BUNDLEDIR, "templates")
        filename = QFileDialog.getOpenFileName(self.qtui, 'Open file',
                                               startdir, '*.txt')
        if filename:
            self.qtui.obsws_template_lineedit.setText(filename[0])

    @Slot()
    def on_serato_lib_button(self):
        ''' lib button clicked action'''
        startdir = self.qtui.serato_local_lineedit.text()
        if not startdir:
            startdir = str(pathlib.Path.home())
        libdir = QFileDialog.getExistingDirectory(self.qtui,
                                                  'Select directory', startdir)
        if libdir:
            self.qtui.serato_local_lineedit.setText(libdir)

    @Slot()
    def on_httpdirbutton_clicked(self):
        ''' file button clicked action '''
        startdir = self.httpdirEdit.text()
        if not startdir:
            startdir = str(pathlib.Path.home())
        dirname = QFileDialog.getExistingDirectory(self.qtui,
                                                   'Select directory',
                                                   startdir)
        if dirname:
            self.httpdirEdit.setText(dirname)

    @Slot()
    def on_html_template_button(self):
        ''' file button clicked action '''
        startfile = self.qtui.html_template_lineedit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = os.path.join(self.config.BUNDLEDIR, "templates")
        filename = QFileDialog.getOpenFileName(self.qtui, 'Open file',
                                               startdir, '*.htm *.html')
        if filename:
            self.qtui.html_template_lineedit.setText(filename[0])

    @Slot()
    def on_cancel_button(self):
        ''' cancel button clicked action '''
        if self.tray:
            self.tray.action_config.setEnabled(True)
        self.upd_win()
        self.qtui.close()
        self.qtui.error_label.setText('')

        if not self.config.file:
            self.tray.cleanquit()

    @Slot()
    def on_reset_button(self):
        ''' cancel button clicked action '''
        self.config.reset()
        self.upd_win()

    @Slot()
    def on_save_button(self):
        ''' save button clicked action '''
        if self.qtui.serato_remote_button.isChecked() and (
                'https://serato.com/playlists'
                not in self.qtui.serato_remote_url_lineedit.text()
                and 'https://www.serato.com/playlists'
                not in self.qtui.serato_remote_url_lineedit.text()
                or len(self.qtui.serato_remote_url_lineedit.text()) < 30):
            self.qtui.error_label.setText(
                'Serato Live Playlist URL is invalid')
            return

        if self.qtui.serato_local_button.isChecked(
        ) and '_Serato_' not in self.qtui.serato_local_lineedit.text():
            self.qtui.error_label.setText(
                r'Serato Library Path is required.  Should point to "\_Serato\_" folder'
            )
            return

        if self.qtui.text_filename_lineedit.text() == "":
            self.qtui.error_label.setText('File to write is required')
            return

        self.config.unpause()
        self.upd_conf()
        self.close()
        self.qtui.error_label.setText('')
        if self.config.local:
            self.tray.action_oldestmode.setCheckable(True)
        else:
            self.tray.action_oldestmode.setCheckable(False)
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
