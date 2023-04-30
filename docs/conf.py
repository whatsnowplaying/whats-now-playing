# pylint: disable=all

# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys

#sys.path.insert(0, os.path.abspath('..'))

import nowplaying.version  # pylint: disable=import-error, no-name-in-module

# -- Project information -----------------------------------------------------

project = 'What\'s Now Playing'
copyright = '2021-2023, Allen Wittenauer'
author = 'Allen Wittenauer'

# The full version, including alpha/beta/rc tags
release = f'{nowplaying.version.__CURRENT_TAG__} [+ {nowplaying.version.__VERSION_DISTANCE__} changes]'
# last released version
lasttag = nowplaying.version.__CURRENT_TAG__

# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.githubpages',
    'sphinx.ext.extlinks',
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'furo'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

#make some variables available to RST
#variables_to_export = [
#    "release",
#    "lasttag",
#]

#frozen_locals = dict(locals())
#rst_prolog = '\n'.join(map(lambda x: f".. |{x}| replace:: {frozen_locals[x]}", variables_to_export))
#del frozen_locals

releaselink = 'https://github.com/whatsnowplaying/whats-now-playing/releases'
basedownload = f'{releaselink}/download'

extlinks = {
    'lasttagdownloadlink':
    (f'{basedownload}/{lasttag}/NowPlaying-{lasttag}-%s.zip', '%s')
}
