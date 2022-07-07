#!/usr/bin/env python3
''' deal with IP address malarky '''

# pylint: disable=c-extension-no-member

import datetime
import socket
import logging

try:
    import netifaces
    IFACES = True
except ImportError:
    IFACES = False

HOSTFQDN = None
HOSTNAME = None
HOSTIP = None
TIMESTAMP = None
TIMEDELTA = datetime.timedelta(minutes=10)


def trysocket():
    ''' try using socket.*; this works most of the time '''
    global HOSTFQDN, HOSTNAME, HOSTIP  #pylint: disable=global-statement
    try:
        HOSTNAME = socket.gethostname()
    except Exception as error:  # pylint: disable = broad-except
        logging.error('Getting hostname via socket failed: %s',
                      error)
    try:
        HOSTFQDN = socket.getfqdn()
    except Exception as error:  # pylint: disable = broad-except
        logging.error('Getting hostfqdn via socket failed: %s',
                      error)

    if HOSTFQDN:
        try:
            HOSTIP = socket.gethostbyname(HOSTFQDN)
        except Exception as error:  # pylint: disable = broad-except
            logging.error('Getting IP information via socket failed: %s',
                          error)

def trynetifaces():
    ''' try using socket.*; this works most of the time '''
    global HOSTIP  #pylint: disable=global-statement

    try:
        gws = netifaces.gateways()
        defnic = gws['default'][netifaces.AF_INET][1]
        defnicipinfo = netifaces.ifaddresses(defnic).setdefault(
            netifaces.AF_INET, [{
                'addr': None
            }])
        HOSTIP = defnicipinfo[0]['addr']
    except Exception as error:  # pylint: disable = broad-except
        logging.error('Getting IP information via netifaces failed: %s', error)


def fallback():
    ''' worst case? put in 127.0.0.1 '''
    global HOSTIP, HOSTNAME, HOSTFQDN  #pylint: disable=global-statement

    if not HOSTIP:
        HOSTIP = '127.0.0.1'

    if not HOSTNAME:
        HOSTNAME = 'localhost'

    if not HOSTFQDN:
        HOSTFQDN = 'localhost'


def gethostmeta():
    ''' resolve hostname/ip of this machine '''
    global TIMESTAMP  #pylint: disable=global-statement

    if not TIMESTAMP or (datetime.datetime.now() - TIMESTAMP >
                         TIMEDELTA) or not HOSTNAME:
        trysocket()
        if not HOSTIP and IFACES:
            trynetifaces()

        if not HOSTIP:
            fallback()
        TIMESTAMP = datetime.datetime.now()
    return {'hostname': HOSTNAME, 'hostfqdn': HOSTFQDN, 'hostip': HOSTIP}
