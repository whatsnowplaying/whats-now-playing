#!/usr/bin/env python3
''' bootstrap the app '''

import logging
import os
import shutil

import nowplaying.version


def setuplogging(logpath=None):
    ''' configure logging '''
    besuretorotate = False

    if os.path.exists(logpath):
        besuretorotate = True

    logfhandler = logging.handlers.RotatingFileHandler(filename=logpath,
                                                       backupCount=10,
                                                       encoding='utf-8')
    if besuretorotate:
        logfhandler.doRollover()

    # this loglevel should eventually be tied into config
    # but for now, hard-set at info
    logging.basicConfig(
        format='%(asctime)s %(threadName)s %(module)s:%(funcName)s:%(lineno)d '
        + '%(levelname)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z',
        handlers=[logfhandler],
        level=logging.DEBUG)
    logging.info('starting up v%s',
                 nowplaying.version.get_versions()['version'])


def setuptemplates(bundledir=None, templatedir=None):
    ''' put the templates into place '''

    # first, define a method for copytree to use to
    # ignore files that already exist

    def bootstrap_template_ignore(srcdir, srclist):  # pylint: disable=unused-argument
        ''' do not copy template files that already exist '''
        ignore = []
        for src in srclist:
            check = os.path.join(templatedir, src)
            if os.path.exists(check):
                ignore.append(src)
            else:
                logging.debug('Adding %s to templates dir', src)

        return ignore

    # and now the main work...

    bundletemplatedir = os.path.join(bundledir, 'templates')

    if os.path.exists(bundletemplatedir):
        shutil.copytree(bundletemplatedir,
                        templatedir,
                        ignore=bootstrap_template_ignore,
                        dirs_exist_ok=True)
    else:
        logging.error('Cannot locate templates dir during bootstrap!')
