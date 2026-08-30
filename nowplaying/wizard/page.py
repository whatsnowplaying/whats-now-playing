#!/usr/bin/env python3
"""Base class and widget helpers for plugin-provided wizard pages.

This is the plugin-facing contract: twelve input plugins subclass WizardPage
and use PathEdit and port_edit, so treat its surface as published.
"""

import functools
import logging
import pathlib
from typing import TYPE_CHECKING

from PySide6.QtGui import QIntValidator  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
    QWizardPage,
)

import nowplaying.uihelp
from nowplaying.wizard.verify import (
    POLL_TIMEOUT,
    START_TIMEOUT,
    VerifyResult,
    VerifyStatus,
    VerifyWorker,
)

if TYPE_CHECKING:
    import types

    import nowplaying.config


class WizardPage(QWizardPage):  # pylint: disable=too-few-public-methods
    """Base class for plugin-provided first-run wizard pages.

    Plugin files define a subclass, then assign:
        self.wizardpage = _TheirPageClass
    in Plugin.__init__().  The install wizard instantiates it as:
        plugin.wizardpage(config=...)
    """

    class PathEdit(QWidget):
        """QLineEdit + Browse button for file or directory pickers.

        Pass file_filter (e.g. '*.nml') for a file picker; omit it (or pass '')
        for a directory picker.  Pass startdir for a smarter initial browse
        location when the field is empty.
        """

        def __init__(  # pylint: disable=too-many-arguments
            self,
            title: str,
            placeholder: str = "",
            file_filter: str = "",
            startdir: "pathlib.Path | str | None" = None,
            allow_bundles: bool = False,
            parent: "QWidget | None" = None,
        ) -> None:
            super().__init__(parent)
            self._title = title
            self._file_filter = file_filter
            self._startdir = str(startdir) if startdir is not None else None
            self._allow_bundles = allow_bundles

            self._edit = QLineEdit()
            self._edit.setPlaceholderText(placeholder)

            browse_btn = QPushButton("Browse…")
            browse_btn.clicked.connect(self._browse)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self._edit)
            layout.addWidget(browse_btn)

        def text(self) -> str:
            """Return the current path text."""
            return self._edit.text()

        def setText(self, text: str) -> None:  # pylint: disable=invalid-name
            """Set the path text."""
            self._edit.setText(text)

        def _browse(self) -> None:
            start = self._edit.text() or self._startdir or str(pathlib.Path.home())
            parent = self.window() or self
            if self._file_filter:
                result = nowplaying.uihelp.UIHelp.open_file_dialog(
                    parent, self._title, start, self._file_filter
                )
            else:
                result = nowplaying.uihelp.UIHelp.open_dir_dialog(
                    parent, self._title, start, allow_bundles=self._allow_bundles
                )
            if result:
                self._edit.setText(result)

    @staticmethod
    def port_edit(placeholder: str = "", width: int = 120) -> QLineEdit:
        """Return a QLineEdit pre-validated for TCP port numbers (1–65535)."""
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setMaximumWidth(width)
        edit.setValidator(QIntValidator(1, 65535))
        return edit

    # Set by the host wizard when it registers the page, for flows that need to
    # leave the declared page order -- the multi-PC DJ role skips the output
    # pages. Pushed in rather than read off the wizard so this stays independent
    # of whichever flow is hosting it.
    next_page_override: int | None = None

    def nextId(self) -> int:  # pylint: disable=invalid-name
        """Route to the page the host asked for, or the declared next one."""
        if self.next_page_override is not None:
            return self.next_page_override
        return super().nextId()

    # Set by every subclass's __init__. Declared here so commit() can reach it
    # without the base having an __init__ of its own.
    config: "nowplaying.config.ConfigFile | None" = None

    def collected(self) -> dict[str, object]:  # pylint: disable=no-self-use
        """This page's answers, keyed by the config key each one belongs to.

        The single source of truth for a page: commit() writes these and Cancel
        restores exactly these, so the two cannot drift apart.
        """
        return {}

    def commit(self) -> None:
        """Write collected() to QSettings. Called when the wizard is accepted."""
        if self.config is None:
            return
        for key, value in self.collected().items():
            self.config.cparser.setValue(key, value)

    # Live verification. Driven from the wizard's currentIdChanged, not from
    # initializePage/cleanupPage, so a subclass overriding those without calling
    # super() cannot silently disable it.

    # Set by the setup wizard when it builds the page.
    verification_module: "types.ModuleType | None" = None

    # Shown alongside WAITING, for sources that need the user to act in another
    # application first: "No track yet." alone is a dead end.
    verification_prompt: str | None = None

    # Class-level, since every plugin page writes its own __init__ and anything
    # the base needs has to exist without one.
    _verify_worker: "VerifyWorker | None" = None
    _verify_label: QLabel | None = None
    _verify_button: QPushButton | None = None
    _verify_config = None

    # Prior values of keys commit() changed. None means the key was absent, so
    # restoring is a remove() rather than a write of "".
    _prior_values: "dict[str, object | None] | None" = None

    # Leaving a page only has to stop polling; blocking the UI thread for the
    # full start() timeout to watch it happen makes Next look broken. Shutdown
    # waits properly, since that is when the port has to be free.
    _PAGE_CHANGE_STOP_MS = 2000

    def start_verification(self, config) -> None:
        """Begin polling this page's source; no-op when there is nothing to poll.

        Commits first. The plugin reads its settings from config, so without this
        it would be checked against whatever was there before the user typed
        anything -- on a fresh install, nothing at all.
        """
        if self.verification_module is None or self._verify_worker is not None:
            return

        self._verify_config = config
        self._snapshot_and_commit(config)
        worker = VerifyWorker(self.verification_module, config, parent=self)
        worker.observed.connect(self.on_verify_result)
        # Its own connection rather than a line inside on_verify_result, which
        # is documented as overridable: a subclass presenting results its own
        # way must not be able to leave the button dead.
        worker.observed.connect(self._on_verify_observed)
        # _drive() returns outright when the plugin will not construct or start()
        # fails, and without this the slot stays taken, so a corrected key or
        # path could never be retried.
        # The worker is bound into the connection rather than recovered with
        # sender(), which is an implicit lookup across a queued cross-thread
        # connection to a plain bound method.
        worker.finished.connect(functools.partial(self._on_worker_finished, worker))
        self._verify_worker = worker
        worker.start()

    def _on_verify_observed(self, _result: VerifyResult) -> None:
        """Re-arm Check Again as soon as the worker reports anything.

        A successful start() polls until the page is left, so finished never
        fires and re-enabling there alone would make Check Again single-use --
        exactly the case where retrying matters, a source pointed somewhere
        valid but wrong that reports WAITING forever.
        """
        if self._verify_button is not None:
            self._verify_button.setEnabled(True)

    def _on_worker_finished(self, worker: "VerifyWorker") -> None:
        """Free the slot, unless a newer worker has already taken it."""
        if worker is self._verify_worker:
            self._verify_worker = None
        if self._verify_button is not None:
            self._verify_button.setEnabled(True)

    def retry_verification(self) -> None:
        """Re-read the page's fields and check again."""
        if self._verify_config is None:
            return
        self.stop_verification()
        if self._verify_worker is not None:
            # stop_verification() keeps the worker when its wait expires, and a
            # poll can sit in wait_for for POLL_TIMEOUT, well past the 2s this
            # allows. start_verification() would then return early and leave the
            # stale result on screen, so say so rather than look ignored.
            self.on_verify_result(
                VerifyResult(
                    VerifyStatus.WAITING,
                    "Still finishing the previous check. Try again in a moment.",
                )
            )
            return
        if self._verify_button is not None:
            self._verify_button.setEnabled(False)
        self.start_verification(self._verify_config)

    def _snapshot_and_commit(self, config) -> None:
        """Write the page's values, remembering only the ones that actually change.

        Recording just the changes keeps Cancel honest and means an untouched
        page leaves nothing to undo: its widgets hold what config already had,
        so committing them changes nothing.
        """
        keys = frozenset(self.collected())
        before = {
            key: (config.cparser.value(key) if config.cparser.contains(key) else None)
            for key in keys
        }
        self.commit()
        prior = self._prior_values if self._prior_values is not None else {}
        for key, old in before.items():
            new = config.cparser.value(key) if config.cparser.contains(key) else None
            # First snapshot wins: repeated visits must not overwrite the
            # original with a value this page wrote earlier.
            if new != old and key not in prior:
                prior[key] = old
        self._prior_values = prior

    def restore_committed(self, config) -> None:
        """Undo what _snapshot_and_commit() changed. Called when the wizard is cancelled."""
        if not self._prior_values:
            return
        for key, old in self._prior_values.items():
            if old is None:
                config.cparser.remove(key)
            else:
                config.cparser.setValue(key, old)
        self._prior_values = None

    def stop_verification(self, shutting_down: bool = False) -> None:
        """Wind the poller down. Must run on Back, Cancel, close and Finish alike:
        a source left started would still hold its port when the real
        subprocesses launch moments later."""
        worker = self._verify_worker
        if worker is None:
            return
        worker.request_stop()
        # Worst-case teardown is an in-flight getplayingtrack() the stop event
        # cannot interrupt, then stop() itself, so budget both. Falling short
        # here on Finish lets the source keep its port into start_all_processes().
        shutdown_ms = int((POLL_TIMEOUT + START_TIMEOUT) * 1000)
        wait_ms = shutdown_ms if shutting_down else self._PAGE_CHANGE_STOP_MS
        if worker.wait(wait_ms):
            self._verify_worker = None
            return
        # Keep the reference: start() sits inside an asyncio.wait_for the stop
        # event cannot interrupt, so a slow plugin outlives the short wait. The
        # page still owns the thread, and shutdown gets a second, longer go.
        logging.error("verify: worker for %s did not stop", type(self).__name__)

    _GLYPHS = {
        VerifyStatus.OK: "✓",
        VerifyStatus.WAITING: "…",
        VerifyStatus.FAILED: "⚠",
        VerifyStatus.TIMEOUT: "⚠",
    }

    def _verification_label(self) -> QLabel | None:
        """The status line, appended to the page's own layout on first use.

        Deliberately not the subtitle: that is where the page explains what to
        do, and overwriting it trades an instruction for a status.
        """
        if self._verify_label is not None:
            return self._verify_label
        layout = self.layout()
        if layout is None:
            return None
        label = QLabel()
        label.setWordWrap(True)
        label.setFrameShape(QFrame.Shape.StyledPanel)
        label.setFrameShadow(QFrame.Shadow.Sunken)
        label.setMargin(8)

        # Correcting a path or key has to be retryable without leaving the page:
        # polling stops for good once start() fails, and navigating away and back
        # is not an obvious thing for a user to try.
        button = QPushButton("Check Again")
        button.clicked.connect(self.retry_verification)
        self._verify_button = button

        # Wrapped in a widget so it fits any layout: QLayout has addWidget but
        # not addLayout.
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(label, 1)
        row_layout.addWidget(button, 0)

        # QFormLayout wants rows, not widgets; addRow() spans both columns.
        if isinstance(layout, QFormLayout):
            layout.addRow(row)
        else:
            layout.addWidget(row)
        self._verify_label = label
        return label

    def on_verify_result(self, result: VerifyResult) -> None:
        """Show the latest observation. Override for richer presentation."""
        label = self._verification_label()
        if label is None:
            return
        text = f"{self._GLYPHS.get(result.status, '')}  {result.message}".strip()
        prompt = result.prompt
        if prompt is None and result.status is VerifyStatus.WAITING:
            prompt = self.verification_prompt
        if prompt:
            text = f"{text}\n{prompt}"
        label.setText(text)
        weight = "bold" if result.status is VerifyStatus.OK else "normal"
        label.setStyleSheet(f"QLabel {{ font-weight: {weight}; }}")
