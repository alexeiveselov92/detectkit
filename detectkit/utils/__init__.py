"""Utility functions for detectk."""

from detectkit.utils.stats import (
    weighted_mad,
    weighted_median,
    weighted_percentile,
)

__all__ = [
    "weighted_percentile",
    "weighted_median",
    "weighted_mad",
]
