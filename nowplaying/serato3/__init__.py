#!/usr/bin/env python3
"""
Serato Module

This module provides comprehensive support for reading Serato DJ files including:
- Database files (_database_V2)
- Crate files (.crate)
- Smart crate files (.scrate)
- Session files (.session)
- History files (.HistoryLog)

The module is structured with separate components for different file types
to maintain clean separation of concerns and improve maintainability.
"""

from .base import SeratoBaseReader, SeratoRuleMatchingMixin
from .crate import SeratoCrateReader
from .database import SeratoDatabaseV2Reader
from .handler import SeratoHandler
from .plugin import Plugin
from .session import SeratoSessionReader
from .smart_crate import SeratoSmartCrateReader

__all__ = [
    "SeratoBaseReader",
    "SeratoRuleMatchingMixin",
    "SeratoDatabaseV2Reader",
    "SeratoCrateReader",
    "SeratoSmartCrateReader",
    "SeratoSessionReader",
    "SeratoHandler",
    "Plugin",
]
