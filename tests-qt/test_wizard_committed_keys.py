#!/usr/bin/env python3
"""collected() is a page's whole answer, and Cancel restores exactly those keys.

Verification commits a page's fields before checking them, because the plugin
constructed to do the checking reads its settings from config. Cancel then puts
back whatever that changed.

Base commit() writes collected() and nothing else, so the two cannot drift --
but a page can still override commit() and reintroduce a bare setValue, which
would leave that key unrestorable. Nothing raises when it happens, so it is
asserted here instead.
"""

import pytest


def _wizard_pages(config):
    """Every input plugin that offers a wizard page, as (short_name, page)."""
    found = []
    for key, module in sorted(config.plugins.get("inputs", {}).items()):
        plugin = module.Plugin(config=config)
        if plugin.wizardpage is None:
            continue
        found.append((key.replace("nowplaying.inputs.", ""), plugin.wizardpage))
    return found


def test_some_pages_were_collected(bootstrap, qtbot):  # pylint: disable=unused-argument
    """Guard the guard: an empty collection would make every test below vacuous.

    Takes qtbot despite not driving any widget: constructing plugins before a
    QApplication exists and then meeting one later aborts the interpreter.
    """
    assert len(_wizard_pages(bootstrap)) > 1


class _RecordingCparser:
    """Passes everything through, noting which keys were written."""

    def __init__(self, real):
        self._real = real
        self.written: list[str] = []

    def setValue(self, key, value):  # pylint: disable=invalid-name
        """Record the key, then write it for real."""
        self.written.append(key)
        self._real.setValue(key, value)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _RecordingConfig:  # pylint: disable=too-few-public-methods
    """A ConfigFile stand-in whose cparser records writes."""

    def __init__(self, real):
        self._real = real
        self.cparser = _RecordingCparser(real.cparser)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_commit_writes_nothing_undeclared(bootstrap, qtbot):  # pylint: disable=unused-argument
    """Every key commit() writes must appear in collected().

    Watches the setValue calls rather than diffing config before and after. A
    diff is vacuous here: the page loads its widgets from config, so committing
    them writes the same values back and nothing appears to change -- the test
    then passes even for a page that bypassed collected() entirely.
    """
    config = bootstrap
    undeclared: dict[str, set[str]] = {}

    for short_name, page_class in _wizard_pages(config):
        page = page_class(config=config)
        recording = _RecordingConfig(config)
        page.config = recording
        try:
            page.commit()
        finally:
            page.config = config

        if extra := set(recording.cparser.written) - set(page.collected()):
            undeclared[short_name] = extra

    assert not undeclared, f"commit() wrote keys missing from collected(): {undeclared}"


def test_restore_puts_back_a_changed_value(bootstrap, qtbot):  # pylint: disable=unused-argument
    """A page that commits a new value must restore the old one on cancel."""
    config = bootstrap
    config.cparser.setValue("traktor/collections", "/original/collection.nml")

    module = config.plugins["inputs"]["nowplaying.inputs.traktor"]
    page = module.Plugin(config=config).wizardpage(config=config)
    page._path_edit.setText("/edited/by/user.nml")  # pylint: disable=protected-access

    page._snapshot_and_commit(config)  # pylint: disable=protected-access
    assert config.cparser.value("traktor/collections") == "/edited/by/user.nml"

    page.restore_committed(config)
    assert config.cparser.value("traktor/collections") == "/original/collection.nml"


def test_restore_returns_the_key_to_its_prior_state(bootstrap, qtbot):  # pylint: disable=unused-argument
    """Restore must leave presence *and* value as they were.

    Deliberately not asserting that a removed key comes back absent: remove()
    does not necessarily make a key absent, because defaults() may also have
    written it, and that value survives. Whether "absent" is even reachable
    depends on whether the software is installed on the machine running the
    test, so the invariant worth asserting is that nothing observable changed.
    """
    config = bootstrap
    config.cparser.remove("traktor/collections")
    was_present = config.cparser.contains("traktor/collections")
    was_value = config.cparser.value("traktor/collections") if was_present else None

    module = config.plugins["inputs"]["nowplaying.inputs.traktor"]
    page = module.Plugin(config=config).wizardpage(config=config)
    page._path_edit.setText("/typed/in.nml")  # pylint: disable=protected-access

    page._snapshot_and_commit(config)  # pylint: disable=protected-access
    assert config.cparser.value("traktor/collections") == "/typed/in.nml"

    page.restore_committed(config)
    assert config.cparser.contains("traktor/collections") is was_present
    assert (config.cparser.value("traktor/collections") if was_present else None) == was_value


def test_untouched_page_leaves_nothing_to_restore(bootstrap, qtbot):  # pylint: disable=unused-argument
    """A page whose widgets still hold what config had records no change.

    This is what keeps the crash window small: nothing is remembered, because
    committing the loaded values changed nothing.
    """
    config = bootstrap
    config.cparser.setValue("traktor/collections", "/unchanged.nml")

    module = config.plugins["inputs"]["nowplaying.inputs.traktor"]
    page = module.Plugin(config=config).wizardpage(config=config)

    page._snapshot_and_commit(config)  # pylint: disable=protected-access
    assert not page._prior_values  # pylint: disable=protected-access
    assert config.cparser.value("traktor/collections") == "/unchanged.nml"


def test_repeated_visits_keep_the_original(bootstrap, qtbot):  # pylint: disable=unused-argument
    """Visiting a page twice must not snapshot the value the first visit wrote."""
    config = bootstrap
    config.cparser.setValue("traktor/collections", "/original.nml")

    module = config.plugins["inputs"]["nowplaying.inputs.traktor"]
    page = module.Plugin(config=config).wizardpage(config=config)

    page._path_edit.setText("/first-edit.nml")  # pylint: disable=protected-access
    page._snapshot_and_commit(config)  # pylint: disable=protected-access
    page._path_edit.setText("/second-edit.nml")  # pylint: disable=protected-access
    page._snapshot_and_commit(config)  # pylint: disable=protected-access

    page.restore_committed(config)
    assert config.cparser.value("traktor/collections") == "/original.nml"


@pytest.mark.parametrize("page_short_name", ["traktor", "virtualdj", "m3u", "icecast"])
def test_declared_keys_are_namespaced_to_the_plugin(bootstrap, page_short_name, qtbot):  # pylint: disable=unused-argument
    """Collected keys should look like config keys, so typos are obvious."""
    module = bootstrap.plugins["inputs"][f"nowplaying.inputs.{page_short_name}"]
    page = module.Plugin(config=bootstrap).wizardpage(config=bootstrap)
    assert page.collected()
    for key in page.collected():
        assert "/" in key, f"{key} is not a group/key pair"
