"""
Interquartile Range (IQR) anomaly detector.

IQR is a robust statistical method for outlier detection that:
- Uses quartiles (Q1, Q3) instead of mean
- Measures spread using IQR = Q3 - Q1
- Robustness similar to MAD; works well with skewed distributions

Formula (Tukey's fences):
- Q1 = 25th percentile, Q3 = 75th percentile
- IQR = Q3 - Q1
- lower_bound = Q1 - threshold × IQR
- upper_bound = Q3 + threshold × IQR

Default threshold = 1.5 (standard Tukey's fences).

Windowing, recency weighting (half_life), detrending and seasonality
grouping are shared with MAD and Z-Score — see
:class:`detectkit.detectors.statistical._windowed.WindowedStatDetector`.
"""

import numpy as np

from detectkit.detectors.statistical._windowed import WindowedStatDetector
from detectkit.utils.stats import weighted_percentile


class IQRDetector(WindowedStatDetector):
    """
    Interquartile Range (IQR) detector using Tukey's fences.

    Detector-specific parameters:
        threshold (float): IQR multiplier for bounds (default: 1.5)
            - 1.5 is standard Tukey's fences, 3.0 = extreme outliers only
        min_samples (int): default 30, must be at least 4 (quartiles)
        min_samples_per_group (int): default 4, must be at least 4

    All other parameters (window_size, seasonality_components, input_type,
    smoothing, window_weights/half_life, detrend) are shared — see
    WindowedStatDetector.

    Example:
        >>> detector = IQRDetector(threshold=1.5, window_size=100)
        >>> results = detector.detect(data)
    """

    THRESHOLD_DEFAULT = 1.5
    MIN_SAMPLES_FLOOR = 4
    MIN_SAMPLES_PER_GROUP_DEFAULT = 4
    MIN_SAMPLES_PER_GROUP_FLOOR = 4
    STATS = (("q1", "center"), ("q3", "center"), ("iqr", "spread"))

    def _compute_stats(self, values: np.ndarray, weights: np.ndarray) -> dict[str, float]:
        q1 = weighted_percentile(values, weights, 25)
        q3 = weighted_percentile(values, weights, 75)
        return {"q1": q1, "q3": q3, "iqr": q3 - q1}

    def _build_interval(self, stats: dict[str, float], threshold: float) -> tuple[float, float]:
        if stats["iqr"] == 0:
            # No spread — any deviation outside [q1, q3] is anomalous
            return stats["q1"] - 1e-10, stats["q3"] + 1e-10
        return (
            stats["q1"] - threshold * stats["iqr"],
            stats["q3"] + threshold * stats["iqr"],
        )

    def _severity(self, current: float, stats: dict[str, float], distance: float) -> float:
        # How many adjusted IQR units beyond the fence
        return distance / stats["iqr"] if stats["iqr"] > 0 else float("inf")
