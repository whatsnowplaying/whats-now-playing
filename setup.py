#!/usr/bin/env python3
'''
    Titles for streaming for Serato
'''
from setuptools import setup
import versioneer

setup(name='NowPlaying',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      include_package_data=True)
