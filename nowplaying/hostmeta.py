#!/usr/bin/env python3
''' deal with IP address malarky '''

# pylint: disable=c-extension-no-member

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


def trysocket():
    ''' try using socket.*; this works most of the time '''
    global HOSTFQDN, HOSTNAME, HOSTIP  #pylint: disable=global-statement
    try:
        HOSTNAME = socket.gethostname()
        HOSTFQDN = socket.getfqdn()
        HOSTIP = socket.gethostbyname(HOSTFQDN)
    except Exception as error:  # pylint: disable = broad-except
        logging.error('Getting host or IP information via socket failed: %s',
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


def gethostmeta():
    ''' resolve hostname/ip of this machine '''

    trysocket()
    if not HOSTIP and IFACES:
        trynetifaces()

    return {'hostname': HOSTNAME, 'hostfqdn': HOSTFQDN, 'hostip': HOSTIP}
