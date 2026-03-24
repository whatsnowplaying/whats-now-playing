#!/usr/bin/env python3
"""setup nltk"""

import nltk
import truststore

truststore.inject_into_ssl()

nltk.download("punkt")
nltk.download("punkt_tab")
