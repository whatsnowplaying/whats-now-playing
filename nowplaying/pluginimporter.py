#!/usr/bin/env python3
"""routine to import plugins"""

import importlib
import logging
import pkgutil
import types


def _candidate_names(ns_pkg: types.ModuleType):
    """Yield the dotted module names in a package, from disk and from a frozen TOC."""
    prefix = f"{ns_pkg.__name__}."
    for _, name, _ in pkgutil.iter_modules(ns_pkg.__path__, prefix):
        yield name

    # special handling when the package is bundled with PyInstaller
    # See https://github.com/pyinstaller/pyinstaller/issues/1905#issuecomment-445787510
    #
    # Currently unreachable: pyinstaller 6.22.1 renamed FrozenImporter to
    # PyiFrozenFinder and exposes no toc attribute, and iter_modules() above
    # finds bundled plugin modules by itself (verified against a real onedir
    # bundle on macOS). Kept because that was checked on one platform and one
    # pyinstaller, and losing every plugin in a shipped build is not a cheap
    # mistake.
    toc: set[str] = set()
    for importer in pkgutil.iter_importers(ns_pkg.__name__.partition(".")[0]):  # pragma: no cover
        if hasattr(importer, "toc"):
            toc |= importer.toc  # pyright: ignore [reportAttributeAccessIssue]
    for name in toc:  # pragma: no cover
        if name.startswith(prefix):
            yield name


def import_plugins(namespace: types.ModuleType) -> dict[str, types.ModuleType]:
    """Import the plugin modules in a package, keyed by dotted module name.

    Only modules that actually provide a Plugin class are returned. Every caller
    goes straight to module.Plugin(...), so a module without one is not a plugin
    -- and it used to be imported and handed over regardless, so the
    AttributeError surfaced while ConfigFile was building its plugin objects,
    nowhere near the module at fault.
    """
    found: dict[str, types.ModuleType] = {}
    for name in dict.fromkeys(_candidate_names(namespace)):
        basename = name.rpartition(".")[2]
        # A leading underscore is the convention for "helper, not a plugin".
        # Both checks are on the base name so a package name cannot disqualify
        # everything inside it.
        #
        # Test modules are matched exactly rather than by substring: "test" in
        # basename would also drop a real plugin named contest.py or latest.py,
        # and silently, since a plugin missing from the registry cannot be
        # selected or configured. This only saves a log line anyway -- the
        # Plugin-class check below already skips a stray test module.
        if (
            basename.startswith("_")
            or basename == "test"
            or basename.startswith("test_")
            or basename.endswith("_test")
        ):
            continue
        try:
            module = importlib.import_module(name)
        except Exception:  # pylint: disable=broad-exception-caught
            # One unimportable plugin should cost its own feature, not startup.
            logging.exception("cannot import plugin %s; skipping", name)
            continue
        if not hasattr(module, "Plugin"):
            # Not silent: this is either a helper that should be named _foo.py or
            # a plugin whose class is misnamed, and the second is worth noticing.
            logging.warning("%s has no Plugin class; not loading it as a plugin", name)
            continue
        found[name] = module
    return found
