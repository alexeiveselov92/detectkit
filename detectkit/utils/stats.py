"""
Statistical utility functions for detectors.

Provides weighted statistics used by windowed detectors (MAD, Z-Score, IQR).

Conventions:
    - Weights only need to be positive; every function normalizes internally.
    - ``weighted_percentile`` uses the midpoint (Hazen) convention, so with
      uniform weights ``weighted_median`` reproduces ``np.median`` exactly
      for both odd and even sample sizes.
    - Callers are responsible for filtering NaN values out of ``data``.
"""

import numpy as np


def _normalize_weights(data: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Validate and normalize *weights* to sum to 1.0."""
    if len(data) != len(weights):
        raise ValueError(f"data and weights must have same length: {len(data)} vs {len(weights)}")
    if len(weights) == 0:
        raise ValueError("data and weights must be non-empty")

    total = weights.sum()
    if not np.isfinite(total) or total <= 0:
        raise ValueError(f"weights must be positive and finite, got sum={total}")
    return weights / total


def effective_sample_size(weights: np.ndarray) -> float:
    """
    Kish effective sample size: (sum w)^2 / sum(w^2).

    Measures how many "real" observations the weighted sample is worth.
    Uniform weights over n points give exactly n; strongly decayed weights
    give much less. Useful for judging statistical reliability when
    recency weighting is enabled.
    """
    weights = np.asarray(weights, dtype=float)
    total = weights.sum()
    if total <= 0:
        return 0.0
    return float(total**2 / np.sum(weights**2))


def weighted_percentile(data: np.ndarray, weights: np.ndarray, percentile: float) -> float:
    """
    Compute weighted percentile using the midpoint (Hazen) convention.

    Each sorted point i is placed at cumulative position
    ``(cumsum(w)[i] - w[i]/2) / sum(w)`` and the requested percentile is
    linearly interpolated between neighboring positions. With uniform
    weights the median matches ``np.median`` exactly.

    Args:
        data: Array of values (must not contain NaN)
        weights: Array of positive weights (normalized internally)
        percentile: Percentile to compute (0-100)

    Returns:
        Weighted percentile value
    """
    if not (0 <= percentile <= 100):
        raise ValueError(f"percentile must be in [0, 100], got {percentile}")

    data = np.asarray(data, dtype=float)
    weights = np.asarray(weights, dtype=float)
    _normalize_weights(data, weights)  # validation only

    order = np.argsort(data, kind="stable")
    sorted_data = data[order]
    sorted_weights = weights[order]

    # Divide by the total once at the end (instead of normalizing first)
    # so uniform integer weights produce exact positions.
    total = sorted_weights.sum()
    positions = (np.cumsum(sorted_weights) - 0.5 * sorted_weights) / total
    target = percentile / 100.0

    # np.interp clamps outside [positions[0], positions[-1]] to the
    # first/last value, which is the desired edge behavior.
    return float(np.interp(target, positions, sorted_data))


def weighted_median(data: np.ndarray, weights: np.ndarray) -> float:
    """Compute weighted median (50th percentile, midpoint convention)."""
    return weighted_percentile(data, weights, 50.0)


def weighted_mad(data: np.ndarray, weights: np.ndarray, center: float | None = None) -> float:
    """
    Compute weighted Median Absolute Deviation.

    Args:
        data: Array of values (must not contain NaN)
        weights: Array of positive weights (normalized internally)
        center: Center value (if None, uses weighted median)

    Returns:
        Weighted MAD value
    """
    if center is None:
        center = weighted_median(data, weights)

    deviations = np.abs(np.asarray(data, dtype=float) - center)
    return weighted_median(deviations, weights)


def weighted_mean(data: np.ndarray, weights: np.ndarray) -> float:
    """Compute weighted mean."""
    data = np.asarray(data, dtype=float)
    weights = _normalize_weights(data, weights)
    return float(np.sum(data * weights))


def weighted_std(
    data: np.ndarray, weights: np.ndarray, center: float | None = None, ddof: int = 0
) -> float:
    """
    Compute weighted standard deviation.

    Args:
        data: Array of values (must not contain NaN)
        weights: Array of positive weights (normalized internally)
        center: Center value (if None, uses weighted mean)
        ddof: Delta degrees of freedom (0 = population, 1 = sample).
            With ddof=1 the reliability correction ``1 / (1 - sum(w^2))``
            is applied; when the effective sample size is too small for
            the correction (<= 1), falls back to the population estimate.

    Returns:
        Weighted standard deviation
    """
    data = np.asarray(data, dtype=float)
    weights = _normalize_weights(data, weights)

    if center is None:
        center = float(np.sum(data * weights))

    variance = float(np.sum(weights * (data - center) ** 2))

    if ddof == 1:
        correction = 1.0 - float(np.sum(weights**2))
        if correction > 1e-12:
            variance = variance / correction
        # else: effective n <= 1, keep the population estimate

    return float(np.sqrt(variance))
