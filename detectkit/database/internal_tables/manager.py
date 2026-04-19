"""Composite :class:`InternalTablesManager` assembled from per-table mixins."""

from __future__ import annotations

from detectkit.database.internal_tables._alert_states import _AlertStatesMixin
from detectkit.database.internal_tables._datapoints import _DatapointsMixin
from detectkit.database.internal_tables._detections import _DetectionsMixin
from detectkit.database.internal_tables._metrics import _MetricsMixin
from detectkit.database.internal_tables._schema import _SchemaMixin
from detectkit.database.internal_tables._tasks import _TasksMixin


class InternalTablesManager(
    _SchemaMixin,
    _DatapointsMixin,
    _DetectionsMixin,
    _TasksMixin,
    _MetricsMixin,
    _AlertStatesMixin,
):
    """High-level façade over a :class:`BaseDatabaseManager` for ``_dtk_*`` tables.

    The class itself adds no behaviour; each mixin owns the methods for
    one logical table. Splitting them keeps every file under ~250 lines
    and makes it obvious where to look when tracking down a bug.
    """
