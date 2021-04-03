#!/usr/bin/env python3
''' user interface to configure '''

import logging
import os
import pathlib
import socket

# pylint: disable=no-name-in-module
from PySide2.QtCore import Qt

from PySide2.QtWidgets import \
                            QCheckBox, \
                            QComboBox, \
                            QFileDialog, \
                            QFrame, \
                            QHBoxLayout, \
                            QLabel, \
                            QLineEdit, \
                            QPushButton, \
                            QRadioButton, \
                            QScrollArea,\
                            QVBoxLayout, \
                            QWidget
from PySide2.QtGui import QIcon, QFont


# settings UI
class SettingsUI:  # pylint: disable=too-many-instance-attributes
    ''' create settings form window '''

    # Need to keep track of these values get changed by the
    # user.  These will get set in init.  If these values
    # change, then trigger the webthread to reset itself
    # to pick up the new values...
    httpdir = None
    httpenabled = None
    httpport = None

    # pylint: disable=too-many-statements, invalid-name
    def __init__(self, config, tray, version):

        self.config = config
        self.iconfile = config.iconfile
        self.tray = tray
        self.version = version
        self.scroll = QScrollArea()
        self.window = QWidget()
        self.separator1 = QFrame()
        self.separator2 = QFrame()
        self.separator3 = QFrame()
        if not config.iconfile:
            self.tray.cleanquit()
        self.scroll.setWindowIcon(QIcon(self.iconfile))
        self.layoutV = QVBoxLayout()
        self.layoutH0 = QHBoxLayout()
        self.layoutH0a = QHBoxLayout()
        self.layoutH1 = QHBoxLayout()
        self.layoutTxtTemplate = QHBoxLayout()
        self.layoutH4 = QHBoxLayout()
        self.layoutH5 = QHBoxLayout()
        self.layoutHttpEnableCheckbox = QHBoxLayout()
        self.layoutHttpPort = QHBoxLayout()
        self.layoutHttpHtmlTemplate = QHBoxLayout()
        self.layoutHttpServerPath = QHBoxLayout()
        self.layoutLogLevel = QHBoxLayout()

        SettingsUI.httpenabled = self.config.httpenabled
        SettingsUI.httpport = self.config.httpport
        SettingsUI.httpdir = self.config.httpdir

        self.fBold = QFont()
        self.fBold.setBold(True)
        self.scroll.setWindowTitle(f'Now Playing {self.version} - Settings')

        self.scroll.setWidgetResizable(True)
        self.scroll.setWindowFlag(Qt.CustomizeWindowHint, True)
        self.scroll.setWindowFlag(Qt.WindowCloseButtonHint, False)
        # self.scroll.setWindowFlag(Qt.WindowMinMaxButtonsHint, False)
        self.scroll.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.scroll.setWidget(self.window)
        self.scroll.setMinimumWidth(700)
        self.scroll.resize(700, 825)

        # error section
        self.errLabel = QLabel()
        self.errLabel.setStyleSheet('color: red')
        # remote
        self.localLabel = QLabel('Track Retrieval Mode')
        self.localLabel.setFont(self.fBold)
        self.layoutV.addWidget(self.localLabel)
        self.remoteDesc = QLabel(
            'Local mode (default) uses Serato\'s local history log for track data.\
\nRemote mode retrieves remote track data from Serato Live Playlists.')
        self.remoteDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.remoteDesc)
        # radios
        self.localRadio = QRadioButton('Local')
        self.localRadio.setChecked(True)
        self.localRadio.toggled.connect(
            lambda: self.on_radiobutton_select(self.localRadio))
        self.localRadio.setMaximumWidth(60)

        self.remoteRadio = QRadioButton('Remote')
        self.remoteRadio.toggled.connect(
            lambda: self.on_radiobutton_select(self.remoteRadio))
        self.layoutH0.addWidget(self.localRadio)
        self.layoutH0.addWidget(self.remoteRadio)
        self.layoutV.addLayout(self.layoutH0)

        # library path
        self.libLabel = QLabel('Serato Library Path')
        self.libLabel.setFont(self.fBold)
        self.libDesc = QLabel(
            'Location of Serato library folder.\ni.e., \\THE_PATH_TO\\_Serato_'
        )
        self.libDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.libLabel)
        self.layoutV.addWidget(self.libDesc)
        self.libButton = QPushButton('Browse for folder')
        self.layoutH0a.addWidget(self.libButton)
        self.libButton.clicked.connect(self.on_libbutton_clicked)
        self.libEdit = QLineEdit()
        self.layoutH0a.addWidget(self.libEdit)
        self.layoutV.addLayout(self.layoutH0a)
        # url
        self.urlLabel = QLabel('URL')
        self.urlLabel.setFont(self.fBold)
        self.urlDesc = QLabel(
            'Web address of your Serato Playlist.\ne.g., https://serato.com/playlists/USERNAME/live'
        )
        self.urlDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.urlLabel)
        self.urlEdit = QLineEdit()
        self.layoutV.addWidget(self.urlDesc)
        self.layoutV.addWidget(self.urlEdit)
        self.urlLabel.setHidden(True)
        self.urlEdit.setHidden(True)
        self.urlDesc.setHidden(True)
        # separator line
        self.separator1.setFrameShape(QFrame.HLine)
        # self.separator.setFrameShadow(QFrame.Sunken)
        self.layoutV.addWidget(self.separator1)

        # interval
        self.intervalLabel = QLabel('Polling Interval')
        self.intervalLabel.setFont(self.fBold)
        self.intervalDesc = QLabel('Amount of time, in seconds, \
that must elapse before checking for new track info. (Default = 10.0)')
        self.intervalDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.intervalLabel)
        self.layoutV.addWidget(self.intervalDesc)
        self.intervalEdit = QLineEdit()
        self.intervalEdit.setMaximumSize(40, 35)
        self.layoutV.addWidget(self.intervalEdit)
        self.intervalLabel.setHidden(True)
        self.intervalDesc.setHidden(True)
        self.intervalEdit.setHidden(True)

        # notify
        self.notifLabel = QLabel('Notification Indicator')
        self.notifLabel.setFont(self.fBold)
        self.layoutV.addWidget(self.notifLabel)
        self.notifCbox = QCheckBox()
        self.notifCbox.setMaximumWidth(25)
        self.layoutH5.addWidget(self.notifCbox)
        self.notifDesc = QLabel('Show OS system notification \
when new song is retrieved.')
        self.notifDesc.setStyleSheet('color: grey')
        self.layoutH5.addWidget(self.notifDesc)
        self.layoutV.addLayout(self.layoutH5)

        # separator line
        self.separator2.setFrameShape(QFrame.HLine)
        # self.separator.setFrameShadow(QFrame.Sunken)
        self.layoutV.addWidget(self.separator2)

        # file
        self.fileLabel = QLabel('File')
        self.fileLabel.setFont(self.fBold)
        self.fileDesc = QLabel(
            'The file to which current track info is written. (Must be plain text: .txt)'
        )
        self.fileDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.fileLabel)
        self.layoutV.addWidget(self.fileDesc)
        self.fileButton = QPushButton('Save as ...')
        self.layoutH1.addWidget(self.fileButton)
        self.fileButton.clicked.connect(self.on_filebutton_clicked)
        self.fileEdit = QLineEdit()
        self.layoutH1.addWidget(self.fileEdit)
        self.layoutV.addLayout(self.layoutH1)

        self.txttemplateLabel = QLabel('TXT Template')
        self.txttemplateLabel.setFont(self.fBold)
        self.txttemplateDesc = QLabel('Template file for text output')
        self.txttemplateDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.txttemplateLabel)
        self.layoutV.addWidget(self.txttemplateDesc)
        self.txttemplateButton = QPushButton('Browse for file')
        self.layoutTxtTemplate.addWidget(self.txttemplateButton)
        self.txttemplateButton.clicked.connect(
            self.on_txttemplatebutton_clicked)
        self.txttemplateEdit = QLineEdit()
        self.layoutTxtTemplate.addWidget(self.txttemplateEdit)
        self.layoutV.addLayout(self.layoutTxtTemplate)

        # delay
        self.delayLabel = QLabel('Write Delay')
        self.delayLabel.setFont(self.fBold)
        self.delayDesc = QLabel('Amount of time, in seconds, \
to delay writing the new track info once it\'s retrieved. (Default = 0)')
        self.delayDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.delayLabel)
        self.layoutV.addWidget(self.delayDesc)
        self.delayEdit = QLineEdit()
        self.delayEdit.setMaximumWidth(40)
        self.layoutV.addWidget(self.delayEdit)

        # separator line
        self.separator3.setFrameShape(QFrame.HLine)
        # self.separator.setFrameShadow(QFrame.Sunken)
        self.layoutV.addWidget(self.separator3)

        # HTTP Server Support
        self.httpenabledLabel = QLabel('HTTP Server Support')
        self.httpenabledLabel.setFont(self.fBold)
        self.layoutV.addWidget(self.httpenabledLabel)
        self.httpenabledCbox = QCheckBox()
        self.httpenabledCbox.setMaximumWidth(25)
        self.layoutHttpEnableCheckbox.addWidget(self.httpenabledCbox)
        self.httpenabledDesc = QLabel('Enable HTTP Server')
        self.httpenabledDesc.setStyleSheet('color: grey')
        self.layoutHttpEnableCheckbox.addWidget(self.httpenabledDesc)
        self.layoutV.addLayout(self.layoutHttpEnableCheckbox)

        try:
            hostname = socket.gethostname()
            hostip = socket.gethostbyname(hostname)
        except:  # pylint: disable = bare-except
            hostname = 'Unknown Hostname'
            hostip = 'Unknown IP'

        self.connectionLabel = QLabel('Networking Info')
        self.connectionLabel.setFont(self.fBold)
        self.connectionDesc = QLabel(
            f'Hostname: {hostname} / IP Address:{hostip}')
        self.connectionDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.connectionLabel)
        self.layoutV.addWidget(self.connectionDesc)

        self.httpportLabel = QLabel('Port')
        self.httpportLabel.setFont(self.fBold)
        self.httpportDesc = QLabel('TCP Port to run the server on')
        self.httpportDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.httpportLabel)
        self.layoutV.addWidget(self.httpportDesc)
        self.httpportEdit = QLineEdit()
        self.httpportEdit.setMaximumWidth(60)
        self.layoutV.addWidget(self.httpportEdit)

        self.htmltemplateLabel = QLabel('HTML Template')
        self.htmltemplateLabel.setFont(self.fBold)
        self.htmltemplateDesc = QLabel('Template file to format')
        self.htmltemplateDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.htmltemplateLabel)
        self.layoutV.addWidget(self.htmltemplateDesc)
        self.htmltemplateButton = QPushButton('Browse for file')
        self.layoutHttpHtmlTemplate.addWidget(self.htmltemplateButton)
        self.htmltemplateButton.clicked.connect(
            self.on_htmltemplatebutton_clicked)
        self.htmltemplateEdit = QLineEdit()
        self.layoutHttpHtmlTemplate.addWidget(self.htmltemplateEdit)
        self.layoutV.addLayout(self.layoutHttpHtmlTemplate)

        self.httpdirLabel = QLabel('Server Path')
        self.httpdirLabel.setFont(self.fBold)
        self.httpdirDesc = QLabel('Location to write data')
        self.httpdirDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.httpdirLabel)
        self.layoutV.addWidget(self.httpdirDesc)
        self.httpdirButton = QPushButton('Save to folder...')
        self.layoutHttpServerPath.addWidget(self.httpdirButton)
        self.httpdirButton.clicked.connect(self.on_httpdirbutton_clicked)
        self.httpdirEdit = QLineEdit()
        self.layoutHttpServerPath.addWidget(self.httpdirEdit)
        self.layoutV.addLayout(self.layoutHttpServerPath)

        if self.config.loglevel == 'INFO':
            setlogindex = 0
        else:
            setlogindex = 1

        self.loglevelLabel = QLabel('Logging Level')
        self.loglevelLabel.setFont(self.fBold)
        self.loglevelDesc = QLabel('Verbosity of the log')
        self.loglevelDesc.setStyleSheet('color: grey')
        self.layoutV.addWidget(self.loglevelLabel)
        self.layoutV.addWidget(self.loglevelDesc)
        self.loglevelComboBox = QComboBox()
        self.loglevelComboBox.addItem('INFO')
        self.loglevelComboBox.addItem('DEBUG')
        self.loglevelComboBox.setCurrentIndex(setlogindex)
        self.loglevelComboBox.setMaximumWidth(100)
        self.layoutLogLevel.addWidget(self.loglevelComboBox)
        self.layoutLogLevel.setAlignment(Qt.AlignLeft)
        self.layoutV.addLayout(self.layoutLogLevel)

        # separator line
        self.separatorRCS = QFrame()
        self.separatorRCS.setFrameShape(QFrame.HLine)
        # self.separator.setFrameShadow(QFrame.Sunken)
        self.layoutV.addWidget(self.separatorRCS)

        # error area
        self.layoutV.addWidget(self.errLabel)
        # reset btn
        self.resetButton = QPushButton('Reset')
        self.resetButton.setMaximumSize(80, 35)
        self.layoutH4.addWidget(self.resetButton)
        self.resetButton.clicked.connect(self.on_resetbutton_clicked)
        # cancel btn
        self.cancelButton = QPushButton('Cancel')
        self.cancelButton.setMaximumSize(80, 35)
        self.layoutH4.addWidget(self.cancelButton)
        self.cancelButton.clicked.connect(self.on_cancelbutton_clicked)
        # save btn
        self.saveButton = QPushButton('Save')
        self.saveButton.setMaximumSize(80, 35)
        self.layoutH4.addWidget(self.saveButton)
        self.saveButton.clicked.connect(self.on_savebutton_clicked)
        self.layoutV.addLayout(self.layoutH4)

        self.window.setLayout(self.layoutV)

    def upd_win(self):
        ''' update the settings window '''
        self.config.get()

        if self.config.local:
            self.localRadio.setChecked(True)
            self.remoteRadio.setChecked(False)
        else:
            self.localRadio.setChecked(False)
            self.remoteRadio.setChecked(True)
        self.libEdit.setText(self.config.libpath)
        self.urlEdit.setText(self.config.url)
        self.fileEdit.setText(self.config.file)
        self.txttemplateEdit.setText(self.config.txttemplate)
        self.httpenabledCbox.setChecked(self.config.httpenabled)
        self.httpportEdit.setText(str(self.config.httpport))
        self.httpdirEdit.setText(self.config.httpdir)
        self.htmltemplateEdit.setText(self.config.htmltemplate)
        self.intervalEdit.setText(str(self.config.interval))
        self.delayEdit.setText(str(self.config.delay))
        self.notifCbox.setChecked(self.config.notif)

    def disable_web(self):
        ''' if the web server gets in trouble, this gets called '''
        self.errLabel.setText(
            'HTTP Server settings are invalid. Bad port? Wrong directory?')
        self.httpenabledCbox.setChecked(False)
        self.upd_win()
        self.upd_conf()

    # pylint: disable=too-many-locals
    def upd_conf(self):
        ''' update the configuration '''
        local = str(self.localRadio.isChecked())
        libpath = self.libEdit.text()
        url = self.urlEdit.text()
        file = self.fileEdit.text()
        txttemplate = self.txttemplateEdit.text()
        httpenabled = self.httpenabledCbox.isChecked()
        httpport = int(self.httpportEdit.text())
        httpdir = self.httpdirEdit.text()
        htmltemplate = self.htmltemplateEdit.text()
        interval = self.intervalEdit.text()
        delay = self.delayEdit.text()
        notif = self.notifCbox.isChecked()
        loglevel = self.loglevelComboBox.currentText()

        self.config.put(initialized=True,
                        local=local,
                        libpath=libpath,
                        url=url,
                        file=file,
                        txttemplate=txttemplate,
                        httpport=httpport,
                        httpdir=httpdir,
                        httpenabled=httpenabled,
                        htmltemplate=htmltemplate,
                        interval=interval,
                        delay=delay,
                        notif=notif,
                        loglevel=loglevel)

        logging.getLogger().setLevel(loglevel)

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

    def on_radiobutton_select(self, b):
        ''' radio button action '''
        if b.text() == 'Local':
            self.urlLabel.setHidden(True)
            self.urlEdit.setHidden(True)
            self.urlDesc.setHidden(True)
            self.intervalLabel.setHidden(True)
            self.intervalDesc.setHidden(True)
            self.intervalEdit.setHidden(True)
            self.libLabel.setHidden(False)
            self.libEdit.setHidden(False)
            self.libDesc.setHidden(False)
            self.libButton.setHidden(False)
        else:
            self.urlLabel.setHidden(False)
            self.urlEdit.setHidden(False)
            self.urlDesc.setHidden(False)
            self.intervalLabel.setHidden(False)
            self.intervalDesc.setHidden(False)
            self.intervalEdit.setHidden(False)
            self.libLabel.setHidden(True)
            self.libEdit.setHidden(True)
            self.libDesc.setHidden(True)
            self.libButton.setHidden(True)

        self.window.hide()
        self.errLabel.setText('')
        self.window.show()

    def on_filebutton_clicked(self):
        ''' file button clicked action '''
        startfile = self.fileEdit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = '.'
        filename = QFileDialog.getSaveFileName(self.window, 'Open file',
                                               startdir, '*.txt')
        if filename:
            self.fileEdit.setText(filename[0])

    def on_txttemplatebutton_clicked(self):
        ''' file button clicked action '''
        startfile = self.txttemplateEdit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = os.path.join(self.config.bundledir, "templates")
        filename = QFileDialog.getOpenFileName(self.window, 'Open file',
                                               startdir, '*.txt')
        if filename:
            self.txttemplateEdit.setText(filename[0])

    def on_libbutton_clicked(self):
        ''' lib button clicked action'''
        startdir = self.libEdit.text()
        if not startdir:
            startdir = str(pathlib.Path.home())
        libdir = QFileDialog.getExistingDirectory(self.window,
                                                  'Select directory', startdir)
        if libdir:
            self.libEdit.setText(libdir)

    def on_httpdirbutton_clicked(self):
        ''' file button clicked action '''
        startdir = self.httpdirEdit.text()
        if not startdir:
            startdir = str(pathlib.Path.home())
        dirname = QFileDialog.getExistingDirectory(self.window,
                                                   'Select directory',
                                                   startdir)
        if dirname:
            self.httpdirEdit.setText(dirname)

    def on_htmltemplatebutton_clicked(self):
        ''' file button clicked action '''
        startfile = self.htmltemplateEdit.text()
        if startfile:
            startdir = os.path.dirname(startfile)
        else:
            startdir = os.path.join(self.config.bundledir, "templates")
        filename = QFileDialog.getOpenFileName(self.window, 'Open file',
                                               startdir, '*.htm *.html')
        if filename:
            self.htmltemplateEdit.setText(filename[0])

    def on_cancelbutton_clicked(self):
        ''' cancel button clicked action '''
        if self.tray:
            self.tray.action_config.setEnabled(True)
        self.upd_win()
        self.close()
        self.errLabel.setText('')

        if not self.config.file:
            self.tray.cleanquit()

    def on_resetbutton_clicked(self):
        ''' cancel button clicked action '''
        self.config.reset()
        self.upd_win()

    def on_savebutton_clicked(self):
        ''' save button clicked action '''
        if self.remoteRadio.isChecked() and (
                'https://serato.com/playlists' not in self.urlEdit.text() and
                'https://www.serato.com/playlists' not in self.urlEdit.text()
                or len(self.urlEdit.text()) < 30):
            self.errLabel.setText('* URL is invalid')
            self.window.hide()
            self.window.show()
            return

        if self.localRadio.isChecked() and '_Serato_' not in self.libEdit.text(
        ):
            self.errLabel.setText(
                '* Serato Library Path is required.  Should point to "_Serato_" folder'
            )
            self.window.hide()
            self.window.show()
            return

        if self.fileEdit.text() == "":
            self.errLabel.setText('* File is required')
            self.window.hide()
            self.window.show()
            return

        self.config.paused = False
        self.upd_conf()
        self.close()
        self.errLabel.setText('')
        if self.config.local:
            self.tray.action_oldestmode.setCheckable(True)
        else:
            self.config.mixmode = 'newest'
            self.tray.action_oldestmode.setCheckable(False)
        self.tray.action_pause.setText('Pause')
        self.tray.action_pause.setEnabled(True)

    def show(self):
        ''' show the system tram '''
        if self.tray:
            self.tray.action_config.setEnabled(False)
        self.upd_win()
        self.scroll.show()
        self.scroll.setFocus()

    def close(self):
        ''' close the system tray '''
        self.tray.action_config.setEnabled(True)
        self.scroll.hide()

    def exit(self):
        ''' exit the tray '''
        self.scroll.close()
