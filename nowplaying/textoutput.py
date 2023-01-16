#!/usr/bin/env python3
''' write to a text file '''

import logging


def deltxttrack(config=None):
    ''' delete text track file '''

    if not config:
        logging.debug('No config?')
        return

    if not config.file:
        return

    if config.cparser.value('textoutput/clearonstartup', type=bool):
        writetxttrack(config, clear=True)


def writetxttrack(config=None,
                  filename=None,
                  templatehandler=None,
                  metadata=None,
                  clear=False):
    ''' write new track info '''

    if not filename:
        filename = config.file

    if not filename and not config:
        logging.debug('no filename and no config?!?')
        return

    if config and config.cparser.value('textoutput/fileappend', type=bool):
        mode = 'a'
    else:
        mode = 'w'

    if clear:
        mode = 'w'

    logging.debug('writetxttrack called for %s', filename)
    if templatehandler:
        txttemplate = templatehandler.generate(metadata)
    elif clear:
        txttemplate = ''
    else:
        txttemplate = '{{ artist }} - {{ title }}'

    logging.debug('writetxttrack: starting write')
    # need to -specifically- open as utf-8 otherwise
    # pyinstaller built app crashes
    with open(filename, mode, encoding='utf-8') as textfh:
        textfh.write(txttemplate)
    logging.debug('writetxttrack: finished write')
