#!/usr/bin/env python3
"""Port availability checks."""

import logging
import socket

# Enough to clear a run of neighbours on the same base port without wandering
# far from the number the user was told to enter in their DJ software.
_SEARCH_RANGE = 20


def port_available(port: int, host: str = "") -> bool:
    """Whether a TCP listener can bind this port right now.

    An empty host binds every interface, which is what the Icecast listener and
    the web server both do, so a port free only on loopback is still reported
    busy. Advisory either way: the answer can be stale by the time a caller
    acts on it.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
            return True
    except OSError:
        return False


def first_free_port(start: int, host: str = "", limit: int = _SEARCH_RANGE) -> int | None:
    """Return the first bindable port at or above start, or None.

    Counts up rather than picking at random: whoever set this has to type the
    number into another application, so staying near the one they expected is
    worth more than spreading the choice out.
    """
    for port in range(start, start + limit):
        if port_available(port, host):
            return port
    logging.warning("no free port in %s-%s", start, start + limit - 1)
    return None
