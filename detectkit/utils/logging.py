"""Logging helpers for the detectkit library.

Libraries should not configure root handlers, levels, or formatting on the
user's behalf. We only expose :func:`get_logger` so internal modules can emit
structured records, and attach a :class:`logging.NullHandler` in the top-level
package (see ``detectkit/__init__.py``) to silence "No handlers could be
found" warnings when the embedding application has not configured logging.
"""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Return the logger for *name*, typically ``__name__`` of the caller."""
    return logging.getLogger(name)


__all__ = ["get_logger"]
