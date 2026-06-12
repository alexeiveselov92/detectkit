"""
Z-Score anomaly detector.

Z-Score is a classical statistical method for outlier detection that:
- Uses mean as measure of center
- Uses standard deviation as measure of spread
- Assumes approximately normal distribution

Formula:
- mean_val = mean(values)
- std_val = std(values)  (Bessel-corrected, ddof=1)
- lower_bound = mean_val - threshold × std_val
- upper_bound = mean_val + threshold × std_val

Note: Z-Score is more sensitive to outliers than MAD because both mean
and std are affected by extreme values.

Windowing, recency weighting (half_life), detrending and seasonality
grouping are shared with MAD and IQR — see
:class:`detectkit.detectors.statistical._windowed.WindowedStatDetector`.
"""

import numpy as np

from detectkit.detectors.statistical._windowed import WindowedStatDetector
from detectkit.utils.stats import weighted_mean, weighted_std


class ZScoreDetector(WindowedStatDetector):
    """
    Z-Score detector.

    Detects anomalies by comparing values against confidence intervals
    based on mean and standard deviation.

    Detector-specific parameters:
        threshold (float): Number of standard deviations from mean
            (default: 3.0 — 99.7% of normal data within ±3σ)
        min_samples (int): default 30, must be at least 2
        min_samples_per_group (int): default 3

    All other parameters (window_size, seasonality_components, input_type,
    smoothing, window_weights/half_life, detrend) are shared — see
    WindowedStatDetector.

    Example:
        >>> detector = ZScoreDetector(threshold=3.0, window_size=100)
        >>> results = detector.detect(data)
    """

    THRESHOLD_DEFAULT = 3.0
    MIN_SAMPLES_FLOOR = 2
    MIN_SAMPLES_PER_GROUP_DEFAULT = 3
    MIN_SAMPLES_PER_GROUP_FLOOR = 1
    STATS = (("mean", "center"), ("std", "spread"))

    def _compute_stats(self, values: np.ndarray, weights: np.ndarray) -> dict[str, float]:
        mean = weighted_mean(values, weights)
        return {"mean": mean, "std": weighted_std(values, weights, center=mean, ddof=1)}

    def _build_interval(self, stats: dict[str, float], threshold: float) -> tuple[float, float]:
        if stats["std"] == 0:
            # All values identical — any deviation is anomalous
            return stats["mean"] - 1e-10, stats["mean"] + 1e-10
        return (
            stats["mean"] - threshold * stats["std"],
            stats["mean"] + threshold * stats["std"],
        )

    def _severity(self, current: float, stats: dict[str, float], distance: float) -> float:
        # Distance beyond the bound in σ units — the same "0 at the bound"
        # convention as MAD/IQR, so the alert layer can compare severities
        # across detectors when picking the alert payload.
        return distance / stats["std"] if stats["std"] > 0 else float("inf")
