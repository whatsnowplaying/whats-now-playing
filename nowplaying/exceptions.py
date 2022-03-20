#!/usr/bin/env python3
''' Internal exceptions '''


class PluginVerifyError(Exception):
    ''' Exception raised when a plugin's verify_settingsui
      needs to fail '''
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)
