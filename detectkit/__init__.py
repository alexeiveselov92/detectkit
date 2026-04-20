"""
detectk - Anomaly Detection for Time-Series Metrics

A Python library for data analysts and engineers to monitor metrics with automatic anomaly detection.
"""

import logging as _logging

from detectkit.core.interval import Interval
from detectkit.core.models import ColumnDefinition, TableModel

__version__ = "0.5.0"

# Library best practice: attach a NullHandler so records aren't dropped with
# a "No handlers could be found" warning when the embedding app hasn't
# configured its root logger.
_logging.getLogger(__name__).addHandler(_logging.NullHandler())

__all__ = [
    "Interval",
    "ColumnDefinition",
    "TableModel",
    "__version__",
]
