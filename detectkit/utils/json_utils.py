"""JSON helpers shared across detectors, loaders, and orchestration.

Uses :mod:`orjson` when installed (faster and produces stable byte output)
and falls back to the stdlib :mod:`json` otherwise. All public helpers
return ``str`` so callers don't have to care about the backend.
"""

from __future__ import annotations

import json
from typing import Any

try:  # pragma: no cover - exercised by import path
    import orjson  # type: ignore[import-untyped]

    _HAS_ORJSON = True
except ImportError:  # pragma: no cover
    _HAS_ORJSON = False


def json_dumps_sorted(obj: Any) -> str:
    """Serialize *obj* to JSON with deterministically sorted keys."""
    if _HAS_ORJSON:
        return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS).decode("utf-8")
    return json.dumps(obj, sort_keys=True)


def json_loads(value: str | bytes) -> Any:
    """Parse a JSON document, preferring orjson for speed."""
    if _HAS_ORJSON:
        return orjson.loads(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)
