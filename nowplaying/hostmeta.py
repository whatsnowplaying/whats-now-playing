#!/usr/bin/env python3
"""deal with IP address malarky"""

# pylint: disable=c-extension-no-member

import datetime
import socket
import logging

try:
    import netifaces  # pylint: disable=import-error

    IFACES = True
except ImportError:
    IFACES = False

HOSTFQDN = None
HOSTNAME = None
HOSTIP = None
TIMESTAMP = None
TIMEDELTA = datetime.timedelta(minutes=10)


def trysocket():
    """try using socket.*; this works most of the time"""
    global HOSTFQDN, HOSTNAME, HOSTIP  # pylint: disable=global-statement
    socket.setdefaulttimeout(5)
    try:
        HOSTNAME = socket.gethostname()
    except Exception as error:  # pylint: disable = broad-except
        logging.error("Getting hostname via socket failed: %s", error)
    try:
        HOSTFQDN = socket.getfqdn()
        # Check if getfqdn returned a bogus reverse DNS result
        if HOSTFQDN and ("in-addr.arpa" in HOSTFQDN or "ip6.arpa" in HOSTFQDN):
            logging.debug(
                "getfqdn returned reverse DNS result, using hostname instead: %s", HOSTFQDN
            )
            HOSTFQDN = HOSTNAME  # Use the hostname instead
    except Exception as error:  # pylint: disable = broad-except
        logging.error("Getting hostfqdn via socket failed: %s", error)

    if HOSTFQDN:
        try:
            resolved_ip = socket.gethostbyname(HOSTFQDN)
            # Don't use localhost/loopback IPs - let netifaces find the real network IP
            if resolved_ip and not resolved_ip.startswith(("127.", "::1")):
                HOSTIP = resolved_ip
            else:
                logging.debug(
                    "Socket resolved to localhost (%s), skipping to try netifaces", resolved_ip
                )
        except Exception as error:  # pylint: disable = broad-except
            logging.error("Getting IP information via socket failed: %s", error)


def trynetifaces():
    """try using socket.*; this works most of the time"""
    global HOSTIP  # pylint: disable=global-statement
    socket.setdefaulttimeout(5)
    try:
        gws = netifaces.gateways()  # pylint: disable=no-member
        defnic = gws["default"][netifaces.AF_INET][1]  # pylint: disable=no-member
        defnicipinfo = netifaces.ifaddresses(defnic).setdefault(netifaces.AF_INET, [{"addr": None}])  # pylint: disable=no-member
        HOSTIP = defnicipinfo[0]["addr"]
    except Exception as error:  # pylint: disable = broad-except
        logging.error("Getting IP information via netifaces failed: %s", error)


def fallback():
    """worst case? put in 127.0.0.1"""
    global HOSTIP, HOSTNAME, HOSTFQDN  # pylint: disable=global-statement

    if not HOSTIP:
        HOSTIP = "127.0.0.1"

    if not HOSTNAME:
        HOSTNAME = "localhost"

    if not HOSTFQDN:
        HOSTFQDN = "localhost"


def gethostmeta() -> dict[str, str | None]:
    """resolve hostname/ip of this machine"""
    global TIMESTAMP  # pylint: disable=global-statement

    logging.debug("Attempting to get DNS information")

    if not TIMESTAMP or (datetime.datetime.now() - TIMESTAMP > TIMEDELTA) or not HOSTNAME:
        trysocket()
        # sourcery skip: hoist-repeated-if-condition
        if not HOSTIP and IFACES:
            trynetifaces()

        if not HOSTIP:
            fallback()
        TIMESTAMP = datetime.datetime.now()
    return {"hostname": HOSTNAME, "hostfqdn": HOSTFQDN, "hostip": HOSTIP}
