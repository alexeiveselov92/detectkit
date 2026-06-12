"""
Median Absolute Deviation (MAD) anomaly detector.

MAD is a robust statistical method for outlier detection that:
- Uses median (robust to outliers) instead of mean
- Measures deviation from median using MAD instead of std
- Less sensitive to extreme values than Z-Score

Formula:
- median_val = median(values)
- mad_val = median(|values - median_val|)
- sigma_est = 1.4826 × mad_val  (normal-consistency scaling, so that
  threshold is expressed in σ-equivalents like Z-Score)
- lower_bound = median_val - threshold × sigma_est
- upper_bound = median_val + threshold × sigma_est

Windowing, recency weighting (half_life), detrending and seasonality
grouping are shared with Z-Score and IQR — see
:class:`detectkit.detectors.statistical._windowed.WindowedStatDetector`.
"""

import numpy as np

from detectkit.detectors.statistical._windowed import WindowedStatDetector
from detectkit.utils.stats import weighted_mad, weighted_median


class MADDetector(WindowedStatDetector):
    """
    Median Absolute Deviation detector.

    Detects anomalies by comparing values against confidence intervals
    based on median and MAD (median absolute deviation).

    Detector-specific parameters:
        threshold (float): Number of σ-equivalents from median (default: 3.0).
            MAD is multiplied by the normal-consistency constant 1.4826, so
            threshold=3.0 genuinely corresponds to 3-sigma on Gaussian noise
            (raw 3×MAD would be only ≈2σ and fire on ~4% of normal points).
            - Higher = less sensitive, lower = more sensitive
        min_samples_per_group (int): default 10

    All other parameters (window_size, min_samples, seasonality_components,
    input_type, smoothing, window_weights/half_life, detrend) are shared —
    see WindowedStatDetector.

    Example:
        >>> detector = MADDetector(threshold=3.0, window_size=100)
        >>> results = detector.detect(data)
    """

    THRESHOLD_DEFAULT = 3.0
    MIN_SAMPLES_FLOOR = 1
    MIN_SAMPLES_PER_GROUP_DEFAULT = 10
    MIN_SAMPLES_PER_GROUP_FLOOR = 1
    STATS = (("median", "center"), ("mad", "spread"))

    # Normal-consistency constant: sigma ≈ 1.4826 × MAD for Gaussian data,
    # so threshold is comparable with Z-Score's σ units.
    MAD_SCALE = 1.4826

    def _compute_stats(self, values: np.ndarray, weights: np.ndarray) -> dict[str, float]:
        median = weighted_median(values, weights)
        return {"median": median, "mad": weighted_mad(values, weights, center=median)}

    def _build_interval(self, stats: dict[str, float], threshold: float) -> tuple[float, float]:
        if stats["mad"] == 0:
            # All values identical — any deviation is anomalous
            return stats["median"] - 1e-10, stats["median"] + 1e-10
        margin = threshold * self.MAD_SCALE * stats["mad"]
        return stats["median"] - margin, stats["median"] + margin

    def _severity(self, current: float, stats: dict[str, float], distance: float) -> float:
        # How many σ-equivalents beyond the bound
        sigma_est = self.MAD_SCALE * stats["mad"]
        return distance / sigma_est if sigma_est > 0 else float("inf")
