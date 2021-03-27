#!/usr/bin/env python3
'''
   setup nowplaying w/versioneer
'''
from setuptools import setup
import versioneer

setup(name='NowPlaying',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      include_package_data=True)
