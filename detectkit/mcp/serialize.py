"""Numpy-free, JSON-safe serialization helpers shared by every MCP tool.

Contract (see the module docstring in :mod:`detectkit.mcp.tools`): every
timestamp crossing the tool boundary is an ISO-8601 UTC string
(``2026-07-01T00:00:00Z``), and every numeric value is a plain ``float``/``int``
or ``None`` — never a numpy scalar, never NaN (NaN becomes ``None``, mirroring
the reporting/UI payload convention).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from detectkit.mcp.errors import McpProjectError
from detectkit.reporting.builder import _ms, _num_or_none
from detectkit.utils.datetime_utils import to_naive_utc

# Re-export so callers only need `detectkit.mcp.serialize`.
num_or_none = _num_or_none

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"
_ISO_FMT_MS = "%Y-%m-%dT%H:%M:%S.%f"


def ms_to_iso(ms: int | None) -> str | None:
    """An integer ms-epoch to an ISO-8601 UTC string (``None`` passes through)."""
    if ms is None:
        return None
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    if dt.microsecond:
        return dt.strftime(_ISO_FMT_MS)[:-3] + "Z"
    return dt.strftime(_ISO_FMT)


def to_iso(value: Any) -> str | None:
    """A datetime / ``np.datetime64`` (or ``None``) to an ISO-8601 UTC string."""
    if value is None:
        return None
    return ms_to_iso(_ms(value))


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (``Z`` or an explicit offset) to naive UTC.

    Accepts the ``Z`` suffix (not handled by ``datetime.fromisoformat`` before
    Python 3.11) by rewriting it to ``+00:00`` first; a bare date
    (``2026-07-01``) is also accepted (midnight UTC).
    """
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise McpProjectError(
            f"Invalid ISO-8601 timestamp: {value!r} (expected e.g. "
            "'2026-07-01T00:00:00Z' or '2026-07-01')"
        ) from exc
    result = to_naive_utc(parsed)
    assert result is not None  # parsed is never None here
    return result


def clamp_limit(limit: int, *, default: int, hard_cap: int) -> int:
    """A requested ``limit`` clamped to ``[1, hard_cap]`` (non-positive -> default)."""
    if limit <= 0:
        limit = default
    return min(limit, hard_cap)


def jsonify(value: Any) -> Any:
    """Recursively coerce numpy scalars/NaN in an already-built dict/list to plain JSON types.

    A last-line defensive pass — every tool builds its own JSON-safe shape
    explicitly — used by tests and any value pulled through unchanged from a
    stored JSON blob (e.g. a detector-params dict) that might still carry a
    numpy scalar.
    """
    if isinstance(value, dict):
        return {k: jsonify(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonify(v) for v in value]
    if isinstance(value, np.generic):
        return num_or_none(value)
    if isinstance(value, float):
        return num_or_none(value)
    return value
