"""Shared helpers for parsing seasonality data and building masks.

Used by statistical detectors (MAD, Z-Score, IQR) that compute group-aware
statistics. Keeping the logic in one place avoids the historical drift
where the same parsing code lived in three nearly identical copies.
"""

from __future__ import annotations

import numpy as np

from detectkit.utils.json_utils import json_loads


def parse_seasonality_data(
    seasonality_data: np.ndarray,
    seasonality_columns: list[str],
) -> dict[str, np.ndarray]:
    """Parse an array of JSON strings into per-column numpy arrays.

    Args:
        seasonality_data: 1-D object array of JSON-encoded dicts
            (or ``"{}"``/``None`` for points without seasonality features).
        seasonality_columns: Column names to project from each dict.

    Returns:
        Dict mapping column name to a numpy array of values aligned with
        the input. Missing keys, malformed JSON and empty payloads all
        resolve to ``None`` for the corresponding row.

    Example:
        >>> parse_seasonality_data(
        ...     np.array(['{"day": 1, "hour": 10}', '{"day": 1, "hour": 11}']),
        ...     ["day", "hour"],
        ... )
        {'day': array([1, 1]), 'hour': array([10, 11])}
    """
    if len(seasonality_data) == 0:
        return {}

    parsed: dict[str, list] = {col: [] for col in seasonality_columns}
    for payload in seasonality_data:
        if payload is None or payload == "{}":
            for col in seasonality_columns:
                parsed[col].append(None)
            continue
        try:
            data_dict = json_loads(payload)
        except (ValueError, TypeError):
            for col in seasonality_columns:
                parsed[col].append(None)
            continue
        for col in seasonality_columns:
            parsed[col].append(data_dict.get(col))

    return {col: np.array(vals) for col, vals in parsed.items()}


def create_seasonality_mask(
    seasonality_dict: dict[str, np.ndarray],
    window_start: int,
    current_idx: int,
    group_columns: list[str],
) -> np.ndarray:
    """Boolean mask selecting window indices that match the current point.

    Args:
        seasonality_dict: Output of :func:`parse_seasonality_data`.
        window_start: Inclusive start of the window inside the parsed arrays.
        current_idx: Index of the point being evaluated.
        group_columns: Columns whose values must match the current point
            (e.g. ``["day_of_week", "hour"]``).

    Returns:
        Boolean array of length ``current_idx - window_start``. When no
        grouping is requested or the requested columns are missing, the
        mask is all ``True``.
    """
    window_size = current_idx - window_start
    if not group_columns or not seasonality_dict:
        return np.ones(window_size, dtype=bool)

    current_values: dict[str, object] = {}
    for col in group_columns:
        if col not in seasonality_dict:
            return np.ones(window_size, dtype=bool)
        current_values[col] = seasonality_dict[col][current_idx]

    mask = np.ones(window_size, dtype=bool)
    for col in group_columns:
        window_vals = seasonality_dict[col][window_start:current_idx]
        mask &= window_vals == current_values[col]
    return mask
