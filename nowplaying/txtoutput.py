#!/usr/bin/env python3
''' write to a text file '''

import logging


def writetxttrack(config=None,
                  filename=None,
                  templatehandler=None,
                  metadata=None,
                  clear=False):
    ''' write new track info '''

    if not filename:
        filename = config.file

    if not filename and not config:
        raise ValueError

    if config and config.cparser.get('textoutput/fileappend', type=bool):
        mode = 'a'
    else:
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
