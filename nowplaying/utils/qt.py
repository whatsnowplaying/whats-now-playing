#!/usr/bin/env python3
"""Qt UI helpers."""

from PySide6.QtWidgets import QWidget


def focus_window(widget: QWidget | None) -> None:
    """Show widget, raise it to the front, and grab keyboard focus.

    `QWidget.show()` alone makes a widget visible but does not bring it
    to the foreground or take keyboard focus when the user is interacting
    with another application.  The full incantation is:

    * `show()` — make the widget visible
    * `raise_()` — move it to the top of the stacking order
    * `activateWindow()` — request that this window become the active
      window (so the OS directs keyboard input to it)
    * `setFocus()` — make this widget the keyboard-focus target within
      the now-active window so input has somewhere concrete to land

    `activateWindow()` alone activates the window but does not give any
    specific child widget input focus; `setFocus()` closes that gap.

    Passing `None` is a no-op.  Callers can drop their defensive `if
    widget:` guards and pass the optional reference directly.

    Note: on macOS the OS prevents apps from stealing focus from another
    app entirely; in that case a higher-level activation (via PyObjC) is
    needed in addition to this helper.
    """
    if widget is None:
        return
    widget.show()
    widget.raise_()
    widget.activateWindow()
    widget.setFocus()
