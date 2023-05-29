#!/usr/bin/env python3
''' routine to import plugins '''

import importlib
import pkgutil
import types
import typing as t

import nowplaying  # pylint: disable=unused-import, cyclic-import


def import_plugins(namespace: types.ModuleType) -> dict[str, types.ModuleType]:
    ''' import plugins and return an object
        with all of them '''

    def iter_ns(ns_pkg):
        ''' iterate over a package and return children.
            used to monkey patch in plugins
        '''
        prefix = f'{ns_pkg.__name__}.'
        for pkg in pkgutil.iter_modules(ns_pkg.__path__, prefix):
            if 'test' not in pkg[1]:
                yield pkg[1]

        # special handling when the package is bundled with PyInstaller
        # See https://github.com/pyinstaller/pyinstaller/issues/1905#issuecomment-445787510
        toc: t.Set[str] = set()
        for importer in pkgutil.iter_importers(
                ns_pkg.__name__.partition(".")[0]):  # pragma: no cover
            if hasattr(importer, 'toc'):
                toc |= importer.toc  # pyright: ignore [reportGeneralTypeIssues]
        for name in toc:  # pragma: no cover
            if name.startswith(prefix):
                yield name

    return {name: importlib.import_module(name) for name in iter_ns(namespace)}
