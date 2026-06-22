"""Distribution features for the detector-selection decision tree.

All pure numpy (no scipy): the detector-suitability spec in
:mod:`detectkit.autotune.detector_select` reads these to vote for a detector
type per seasonality group.
"""

from __future__ import annotations

import math

import numpy as np


def compute_distribution_features(values: np.ndarray) -> dict[str, float]:
    """Summarize a sample's shape.

    Returns:
        Dict with:
        - ``n``: valid sample count
        - ``skewness``: Fisher-Pearson moment skewness
        - ``excess_kurtosis``: kurtosis - 3
        - ``outlier_fraction``: fraction beyond Tukey fences
        - ``heavy_tail_ratio``: (1.4826*MAD)/std; <1 = heavy-tailed, ~1 = Gaussian
        - ``zero_inflation``: fraction of (near-)zero values
        - ``normality``: Jarque-Bera-shaped proxy in (0, 1], higher = more normal
    """
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    n = int(v.size)
    if n < 2:
        return {
            "n": float(n),
            "skewness": 0.0,
            "excess_kurtosis": 0.0,
            "outlier_fraction": 0.0,
            "heavy_tail_ratio": 1.0,
            "zero_inflation": 0.0,
            "normality": 0.5,
        }

    mean = float(np.mean(v))
    m2 = float(np.mean((v - mean) ** 2))
    std = math.sqrt(m2)

    if m2 == 0.0:
        skewness = 0.0
        excess_kurtosis = 0.0
    else:
        m3 = float(np.mean((v - mean) ** 3))
        m4 = float(np.mean((v - mean) ** 4))
        skewness = m3 / (m2**1.5)
        excess_kurtosis = m4 / (m2**2) - 3.0

    q1, q3 = (float(x) for x in np.percentile(v, [25, 75]))
    iqr = q3 - q1
    if iqr > 0:
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        outlier_fraction = float(np.mean((v < low) | (v > high)))
    else:
        outlier_fraction = 0.0

    median = float(np.median(v))
    mad = float(np.median(np.abs(v - median)))
    heavy_tail_ratio = (1.4826 * mad) / std if std > 0 else 1.0

    zero_inflation = float(np.mean(np.abs(v) < 1e-12))

    jarque_bera_shape = (skewness**2) / 6.0 + (excess_kurtosis**2) / 24.0
    normality = math.exp(-jarque_bera_shape)

    return {
        "n": float(n),
        "skewness": skewness,
        "excess_kurtosis": excess_kurtosis,
        "outlier_fraction": outlier_fraction,
        "heavy_tail_ratio": heavy_tail_ratio,
        "zero_inflation": zero_inflation,
        "normality": normality,
    }
