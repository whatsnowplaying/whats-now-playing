#!/usr/bin/env python3
''' setup nltk '''

import ssl
import nltk

try:
    _create_unverified_https_context = ssl._create_unverified_context  # pylint: disable=protected-access
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context  # pylint: disable=protected-access

nltk.download('punkt')
