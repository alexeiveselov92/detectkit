"""Public surface for the metric processing pipeline.

External code imports :class:`TaskManager`, :class:`PipelineStep` and
:class:`TaskStatus` from this package; everything else is internal.

``MetricLoader`` is re-exported here only because tests historically
patch ``detectkit.orchestration.task_manager.MetricLoader``. New code
should import :class:`MetricLoader` from
:mod:`detectkit.loaders.metric_loader` directly.
"""

from detectkit.loaders.metric_loader import MetricLoader  # noqa: F401  (test patch target)
from detectkit.orchestration.task_manager._types import (
    PipelineStep,
    TaskStatus,
    make_alert_config_id,
)
from detectkit.orchestration.task_manager.manager import TaskManager

# Legacy private alias kept so existing imports don't break.
_make_alert_config_id = make_alert_config_id

__all__ = [
    "TaskManager",
    "PipelineStep",
    "TaskStatus",
    "make_alert_config_id",
]
