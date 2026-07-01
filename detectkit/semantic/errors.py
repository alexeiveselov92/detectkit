"""Typed errors for the OSI (Open Semantic Interchange) interop layer.

Kept separate so the converter surfaces failures with clear, actionable messages
(and the CLI can map them to a friendly exit) instead of leaking pydantic /
sqlglot internals.
"""

from __future__ import annotations


class OsiError(Exception):
    """Base class for every OSI interop failure."""


class OsiParseError(OsiError):
    """The OSI model file is missing, malformed, or has no usable model/metric."""


class OsiUnsupportedMetric(OsiError):
    """The OSI metric cannot be SAFELY compiled to a one-value-per-bucket series.

    Raised — rather than emitting a plausible-but-wrong query — for the metric
    shapes that don't map cleanly to detectkit's contract (window functions,
    non-aggregate expressions, cross-dataset joins, an unsupported aggregate, or
    a grain a Cube target can't express). The message names the reason and points
    at the ``query_file`` escape hatch.
    """


class OsiDependencyMissing(OsiError):
    """The optional ``[osi]`` extra (sqlglot) is not installed."""
