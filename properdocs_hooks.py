"""mkdocs build hooks for What's Now Playing documentation."""

import shutil


def on_pre_build(config):  # pylint: disable=unused-argument
    """Copy repo-root CHANGELOG.md into docs/ before each build."""
    shutil.copy("CHANGELOG.md", "docs/changelog.md")
