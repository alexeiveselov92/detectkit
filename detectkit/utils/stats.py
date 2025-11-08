"""
Statistical utility functions for detectors.

Provides weighted statistics functions for use in detectors.
"""

from typing import Optional

import numpy as np


def weighted_percentile(
    data: np.ndarray,
    weights: np.ndarray,
    percentile: float
) -> float:
    """
    Compute weighted percentile.

    Args:
        data: Array of values
        weights: Array of weights (must sum to 1.0)
        percentile: Percentile to compute (0-100)

    Returns:
        Weighted percentile value

    Example:
        >>> data = np.array([1, 2, 3, 4, 5])
        >>> weights = np.array([0.1, 0.2, 0.4, 0.2, 0.1])
        >>> weighted_percentile(data, weights, 50)  # Weighted median
        3.0

    Note:
        Uses linear interpolation between cumulative weights.
    """
    if len(data) != len(weights):
        raise ValueError(f"data and weights must have same length: {len(data)} vs {len(weights)}")

    if not np.isclose(weights.sum(), 1.0):
        raise ValueError(f"weights must sum to 1.0, got {weights.sum()}")

    if not (0 <= percentile <= 100):
        raise ValueError(f"percentile must be in [0, 100], got {percentile}")

    # Sort data and weights together
    sorted_indices = np.argsort(data)
    sorted_data = data[sorted_indices]
    sorted_weights = weights[sorted_indices]

    # Cumulative sum of weights
    cumsum = np.cumsum(sorted_weights)

    # Find index where cumsum >= percentile/100
    target = percentile / 100.0
    idx = np.searchsorted(cumsum, target)

    # Handle edge cases
    if idx >= len(sorted_data):
        return sorted_data[-1]

    if idx == 0:
        return sorted_data[0]

    # Linear interpolation between surrounding values
    # (more accurate than just returning sorted_data[idx])
    lower_weight = cumsum[idx - 1] if idx > 0 else 0.0
    upper_weight = cumsum[idx]

    if np.isclose(lower_weight, upper_weight):
        # Avoid division by zero
        return sorted_data[idx]

    # Interpolate
    fraction = (target - lower_weight) / (upper_weight - lower_weight)
    return sorted_data[idx - 1] + fraction * (sorted_data[idx] - sorted_data[idx - 1])


def weighted_median(data: np.ndarray, weights: np.ndarray) -> float:
    """
    Compute weighted median (50th percentile).

    Args:
        data: Array of values
        weights: Array of weights (must sum to 1.0)

    Returns:
        Weighted median value

    Example:
        >>> data = np.array([1, 2, 3, 4, 5])
        >>> weights = np.array([0.1, 0.2, 0.4, 0.2, 0.1])
        >>> weighted_median(data, weights)
        3.0
    """
    return weighted_percentile(data, weights, 50.0)


def weighted_mad(
    data: np.ndarray,
    weights: np.ndarray,
    center: Optional[float] = None
) -> float:
    """
    Compute weighted Median Absolute Deviation.

    Args:
        data: Array of values
        weights: Array of weights (must sum to 1.0)
        center: Center value (if None, uses weighted median)

    Returns:
        Weighted MAD value

    Example:
        >>> data = np.array([1, 2, 3, 4, 5])
        >>> weights = np.array([0.1, 0.2, 0.4, 0.2, 0.1])
        >>> weighted_mad(data, weights)
        1.0
    """
    if center is None:
        center = weighted_median(data, weights)

    deviations = np.abs(data - center)
    return weighted_median(deviations, weights)


def weighted_mean(data: np.ndarray, weights: np.ndarray) -> float:
    """
    Compute weighted mean.

    Args:
        data: Array of values
        weights: Array of weights (must sum to 1.0)

    Returns:
        Weighted mean value

    Example:
        >>> data = np.array([1, 2, 3, 4, 5])
        >>> weights = np.array([0.1, 0.2, 0.4, 0.2, 0.1])
        >>> weighted_mean(data, weights)
        3.0
    """
    if len(data) != len(weights):
        raise ValueError(f"data and weights must have same length: {len(data)} vs {len(weights)}")

    if not np.isclose(weights.sum(), 1.0):
        raise ValueError(f"weights must sum to 1.0, got {weights.sum()}")

    return np.sum(data * weights)


def weighted_std(
    data: np.ndarray,
    weights: np.ndarray,
    center: Optional[float] = None,
    ddof: int = 0
) -> float:
    """
    Compute weighted standard deviation.

    Args:
        data: Array of values
        weights: Array of weights (must sum to 1.0)
        center: Center value (if None, uses weighted mean)
        ddof: Delta degrees of freedom (0 = population, 1 = sample)

    Returns:
        Weighted standard deviation

    Example:
        >>> data = np.array([1, 2, 3, 4, 5])
        >>> weights = np.array([0.1, 0.2, 0.4, 0.2, 0.1])
        >>> weighted_std(data, weights)
        1.095445...
    """
    if len(data) != len(weights):
        raise ValueError(f"data and weights must have same length: {len(data)} vs {len(weights)}")

    if not np.isclose(weights.sum(), 1.0):
        raise ValueError(f"weights must sum to 1.0, got {weights.sum()}")

    if center is None:
        center = weighted_mean(data, weights)

    # Weighted variance
    variance = np.sum(weights * (data - center) ** 2)

    # Apply Bessel's correction if ddof=1
    if ddof == 1:
        # For weighted data: variance / (1 - sum(weights^2))
        sum_weights_sq = np.sum(weights ** 2)
        variance = variance / (1 - sum_weights_sq)

    return np.sqrt(variance)
