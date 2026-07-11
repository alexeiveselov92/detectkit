"""OSI (Open Semantic Interchange) interop for detectkit.

An **isolated, additive** layer: nothing in the load/detect/alert pipeline imports
it, so it can never affect a running project. It powers the ``dtk osi`` command
group only (import an OSI metric into a native detectkit metric; export detectkit
metrics into an OSI fragment). sqlglot is an optional dependency (the ``[osi]``
extra), imported lazily inside :mod:`detectkit.semantic.query_gen`.

See ``.claude/rules/architecture.md`` ("Manual semantic interop") and
``project_osi_detectkit_integration`` for the design.
"""

from __future__ import annotations

from detectkit.semantic.errors import (
    OsiDependencyMissing,
    OsiError,
    OsiParseError,
    OsiUnsupportedMetric,
)
from detectkit.semantic.exporter import export_metric_to_osi, export_models
from detectkit.semantic.importer import ImportResult, import_osi_metric
from detectkit.semantic.osi_model import (
    DETECTKIT_VENDOR,
    OsiSemanticModel,
    load_osi_models,
    parse_osi_models,
)

__all__ = [
    "DETECTKIT_VENDOR",
    "ImportResult",
    "OsiDependencyMissing",
    "OsiError",
    "OsiParseError",
    "OsiSemanticModel",
    "OsiUnsupportedMetric",
    "export_metric_to_osi",
    "export_models",
    "import_osi_metric",
    "load_osi_models",
    "parse_osi_models",
]
