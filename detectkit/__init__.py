"""
detectk - Anomaly Detection for Time-Series Metrics

A Python library for data analysts and engineers to monitor metrics with automatic anomaly detection.
"""

__version__ = "0.1.0"

from detectkit.core.interval import Interval
from detectkit.core.models import ColumnDefinition, TableModel

__all__ = [
    "Interval",
    "ColumnDefinition",
    "TableModel",
    "__version__",
]
