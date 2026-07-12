"""Typed errors for the loading layer.

Kept separate (mirroring ``semantic/errors.py``) so a source-database failure
in hybrid mode can be told apart from a state-database failure at a glance —
in logs, in the project-level error alert, and by any caller inspecting
``type(exc)``.
"""

from __future__ import annotations


class SourceDatabaseError(Exception):
    """A metric's SOURCE-profile database failed (hybrid mode).

    Wraps the original exception with the source profile's name. Raised only
    around the two places that actually talk to a source-profile connection:
    ``MetricLoader.load``'s query execution, and building a pooled
    source-profile manager in ``TaskManager``. Every other failure (saving to
    _dtk_* state, detect, alert, or a non-hybrid metric's query — which runs
    through the same connection as state) stays a plain, unwrapped exception,
    since there is nothing to disambiguate in that case.
    """

    def __init__(self, profile_name: str, original: BaseException) -> None:
        self.profile_name = profile_name
        self.original = original
        super().__init__(
            f"source database (profile '{profile_name}'): " f"{type(original).__name__}: {original}"
        )
