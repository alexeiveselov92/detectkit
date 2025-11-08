"""
Interquartile Range (IQR) anomaly detector.

IQR is a robust statistical method for outlier detection that:
- Uses quartiles (Q1, Q3) instead of mean
- Measures spread using IQR = Q3 - Q1
- Less sensitive to outliers than Z-Score
- Similar robustness to MAD
- Supports seasonality grouping for adaptive thresholds

Formula:
- Q1 = 25th percentile
- Q3 = 75th percentile
- IQR = Q3 - Q1
- lower_bound = Q1 - threshold × IQR
- upper_bound = Q3 + threshold × IQR

With seasonality:
- Computes global statistics (entire window)
- Computes group statistics (seasonality subset)
- Applies multipliers: adjusted_stat = global_stat × group_multiplier

Default threshold = 1.5 (standard Tukey's fences)
"""

import json
from typing import Any, Dict, List, Optional, Union

import numpy as np

from detectkit.detectors.base import BaseDetector, DetectionResult


class IQRDetector(BaseDetector):
    """
    Interquartile Range (IQR) detector for anomaly detection with seasonality support.

    Detects anomalies using Tukey's fences method based on quartiles.
    This is a robust method that works well with skewed distributions.

    Parameters:
        threshold (float): IQR multiplier for bounds (default: 1.5)
            - 1.5 is standard Tukey's fences (identifies outliers)
            - 3.0 identifies extreme outliers
            - Higher = less sensitive (fewer anomalies)
            - Lower = more sensitive (more anomalies)

        window_size (int): Historical window size in points (default: 100)
            - Uses last N points to compute statistics
            - Larger = more stable but less responsive
            - Smaller = more responsive but less stable

        min_samples (int): Minimum samples required for detection (default: 30)
            - Skip detection if window has fewer valid points
            - Ensures statistical reliability

        seasonality_components (list, optional): List of seasonality groupings
            - Single component: ["hour_of_day"]
            - Multiple separate: ["hour_of_day", "day_of_week"]
            - Combined group: [["hour_of_day", "day_of_week"]]
            - Enables adaptive confidence intervals per seasonality pattern

        min_samples_per_group (int): Minimum samples per seasonality group (default: 4)
            - Groups with fewer samples use global statistics
            - Needs at least 4 for quartile calculation

    Example:
        >>> # Without seasonality
        >>> detector = IQRDetector(threshold=1.5, window_size=100)
        >>> results = detector.detect(data)

        >>> # With seasonality
        >>> detector = IQRDetector(
        ...     threshold=1.5,
        ...     window_size=2016,
        ...     seasonality_components=["hour_of_day", "day_of_week"]
        ... )
        >>> results = detector.detect(data)
    """

    def __init__(
        self,
        threshold: float = 1.5,
        window_size: int = 100,
        min_samples: int = 30,
        seasonality_components: Optional[List[Union[str, List[str]]]] = None,
        min_samples_per_group: int = 4,
        input_type: str = "values",
        smoothing: Optional[str] = None,
        smoothing_alpha: float = 0.3,
        smoothing_window: int = 10,
        window_weights: Optional[str] = None,
        weight_decay: float = 0.95,
    ):
        """
        Initialize IQR detector with parameters.

        Args:
            threshold: IQR multiplier for bounds
            window_size: Historical window size in points
            min_samples: Minimum total samples required
            seasonality_components: Optional list of seasonality groups
            min_samples_per_group: Minimum samples per seasonality group
            input_type: Input transformation type (values, changes, absolute_changes, log_changes)
            smoothing: Smoothing method (None, ema, sma)
            smoothing_alpha: EMA smoothing factor (0 < alpha <= 1)
            smoothing_window: SMA window size
            window_weights: Weighting method (None, exponential, linear)
            weight_decay: Decay factor for exponential weights (0 < decay < 1)
        """
        super().__init__(
            threshold=threshold,
            window_size=window_size,
            min_samples=min_samples,
            seasonality_components=seasonality_components,
            min_samples_per_group=min_samples_per_group,
            input_type=input_type,
            smoothing=smoothing,
            smoothing_alpha=smoothing_alpha,
            smoothing_window=smoothing_window,
            window_weights=window_weights,
            weight_decay=weight_decay,
        )

    def _validate_params(self):
        """Validate detector parameters."""
        threshold = self.params.get("threshold")
        if threshold is None or threshold <= 0:
            raise ValueError("threshold must be positive")

        window_size = self.params.get("window_size")
        if window_size is None or window_size < 1:
            raise ValueError("window_size must be at least 1")

        min_samples = self.params.get("min_samples")
        if min_samples is None or min_samples < 4:
            raise ValueError("min_samples must be at least 4 (for quartiles)")

        if min_samples > window_size:
            raise ValueError("min_samples cannot exceed window_size")

        min_samples_per_group = self.params.get("min_samples_per_group", 4)
        if min_samples_per_group < 4:
            raise ValueError(
                "min_samples_per_group must be at least 4 (for quartiles)"
            )

    def _parse_seasonality_data(
        self, seasonality_data: np.ndarray, seasonality_columns: List[str]
    ) -> Dict[str, np.ndarray]:
        """
        Parse seasonality JSON strings into structured data.

        Args:
            seasonality_data: Array of JSON strings
            seasonality_columns: List of column names

        Returns:
            Dict with column names as keys, numpy arrays as values
        """
        if len(seasonality_data) == 0:
            return {}

        parsed_data = {col: [] for col in seasonality_columns}

        for json_str in seasonality_data:
            if json_str is None or json_str == "{}":
                for col in seasonality_columns:
                    parsed_data[col].append(None)
            else:
                try:
                    data_dict = json.loads(json_str)
                    for col in seasonality_columns:
                        parsed_data[col].append(data_dict.get(col))
                except (json.JSONDecodeError, TypeError):
                    for col in seasonality_columns:
                        parsed_data[col].append(None)

        return {col: np.array(vals) for col, vals in parsed_data.items()}

    def _create_seasonality_mask(
        self,
        seasonality_dict: Dict[str, np.ndarray],
        window_start: int,
        current_idx: int,
        group_columns: List[str],
    ) -> np.ndarray:
        """
        Create boolean mask for seasonality group.

        Args:
            seasonality_dict: Parsed seasonality data
            window_start: Start index of window
            current_idx: Current point index
            group_columns: List of columns to group by

        Returns:
            Boolean mask for window indices matching current point's seasonality
        """
        if not group_columns or not seasonality_dict:
            window_size = current_idx - window_start
            return np.ones(window_size, dtype=bool)

        current_values = {}
        for col in group_columns:
            if col in seasonality_dict:
                current_values[col] = seasonality_dict[col][current_idx]
            else:
                return np.ones(current_idx - window_start, dtype=bool)

        mask = np.ones(current_idx - window_start, dtype=bool)

        for col in group_columns:
            current_val = current_values[col]
            window_vals = seasonality_dict[col][window_start:current_idx]
            mask &= (window_vals == current_val)

        return mask

    def detect(self, data: Dict[str, np.ndarray]) -> list[DetectionResult]:
        """
        Perform IQR-based anomaly detection with optional seasonality support.

        For each point, uses historical window to compute:
        1. Global Q1, Q3, IQR (entire window)
        2. If seasonality configured: group Q1, Q3, IQR (seasonality subset)
        3. Apply multipliers: adjusted = global × (group / global)
        4. Build confidence interval: [Q1 - threshold×IQR, Q3 + threshold×IQR]
        5. Detect anomaly if value outside interval

        Args:
            data: Dictionary with keys:
                - timestamp: np.array of datetime64[ms]
                - value: np.array of float64 (may contain NaN)
                - seasonality_data: np.array of JSON strings (optional)
                - seasonality_columns: list of column names (optional)

        Returns:
            List of DetectionResult for each point

        Notes:
            - NaN values are skipped (marked as non-anomalous)
            - First min_samples-1 points are skipped (insufficient history)
            - Uses linear interpolation for percentile calculation
            - Seasonality grouping creates adaptive confidence intervals
        """
        timestamps = data["timestamp"]
        values = data["value"]  # ORIGINAL values (always kept)
        threshold = self.params["threshold"]
        window_size = self.params["window_size"]
        min_samples = self.params["min_samples"]

        # Seasonality parameters
        seasonality_components = self.params.get("seasonality_components")
        min_samples_per_group = self.params.get("min_samples_per_group", 4)

        # STEP 0: Preprocessing (smoothing + input_type transformation)
        smoothed_values = self._apply_smoothing(values)
        processed_values = self._preprocess_input(smoothed_values)

        # Parse seasonality data if available
        seasonality_dict = {}
        seasonality_columns = data.get("seasonality_columns", [])
        seasonality_data = data.get("seasonality_data", np.array([]))

        if (
            seasonality_components
            and len(seasonality_columns) > 0
            and len(seasonality_data) > 0
        ):
            seasonality_dict = self._parse_seasonality_data(
                seasonality_data, seasonality_columns
            )

        results = []
        n_points = len(timestamps)

        for i in range(n_points):
            current_val = values[i]  # ORIGINAL value
            current_processed = processed_values[i]  # PROCESSED value
            current_ts = timestamps[i]

            # Skip NaN values (in processed)
            if np.isnan(current_processed):
                results.append(
                    DetectionResult(
                        timestamp=current_ts,
                        value=current_val,
                        processed_value=current_processed,
                        is_anomaly=False,
                        detection_metadata={"reason": "missing_data"},
                    )
                )
                continue

            # Get historical window (not including current point)
            window_start = max(0, i - window_size)
            window_processed = processed_values[window_start:i]

            # Filter out NaN values from window
            valid_mask = ~np.isnan(window_processed)
            window_valid = window_processed[valid_mask]

            # Check if we have enough samples
            if len(window_valid) < min_samples:
                results.append(
                    DetectionResult(
                        timestamp=current_ts,
                        value=current_val,
                        processed_value=current_processed,
                        is_anomaly=False,
                        detection_metadata={
                            "reason": "insufficient_data",
                            "window_size": int(len(window_valid)),
                            "min_samples": min_samples,
                        },
                    )
                )
                continue

            # Compute weights for window (if specified)
            weights = self._compute_weights(len(window_valid))

            # STEP 1: Compute GLOBAL statistics (entire window)
            # Use weighted statistics if weights are not uniform
            from detectkit.utils import weighted_percentile

            global_q1 = weighted_percentile(window_valid, weights, 25)
            global_q3 = weighted_percentile(window_valid, weights, 75)
            global_iqr = global_q3 - global_q1

            # Initialize adjusted statistics
            adjusted_q1 = global_q1
            adjusted_q3 = global_q3
            adjusted_iqr = global_iqr

            # STEP 2: Apply seasonality adjustments
            multipliers_applied = []

            if seasonality_components and seasonality_dict:
                for group in seasonality_components:
                    # Convert single string to list
                    group_cols = [group] if isinstance(group, str) else group

                    # Create mask for this seasonality group
                    season_mask = self._create_seasonality_mask(
                        seasonality_dict, window_start, i, group_cols
                    )

                    # Apply mask to window (only valid values + seasonality match)
                    # Both valid_mask and season_mask are same size as window_processed
                    combined_mask = valid_mask & season_mask

                    group_values = window_processed[combined_mask]

                    # Check if enough samples in group
                    if len(group_values) < min_samples_per_group:
                        # Insufficient data - skip this group (multiplier = 1.0)
                        multipliers_applied.append({
                            "group": group_cols,
                            "q1_multiplier": 1.0,
                            "q3_multiplier": 1.0,
                            "iqr_multiplier": 1.0,
                            "reason": "insufficient_group_data",
                            "group_size": int(len(group_values)),
                        })
                        continue

                    # Compute group statistics with weights
                    group_weights = self._compute_weights(len(group_values))
                    group_q1 = weighted_percentile(group_values, group_weights, 25)
                    group_q3 = weighted_percentile(group_values, group_weights, 75)
                    group_iqr = group_q3 - group_q1

                    # Calculate multipliers (avoid division by zero)
                    if global_q1 != 0:
                        q1_multiplier = group_q1 / global_q1
                    else:
                        q1_multiplier = 1.0

                    if global_q3 != 0:
                        q3_multiplier = group_q3 / global_q3
                    else:
                        q3_multiplier = 1.0

                    if global_iqr > 0:
                        iqr_multiplier = group_iqr / global_iqr
                    else:
                        iqr_multiplier = 1.0

                    # Apply multipliers
                    adjusted_q1 *= q1_multiplier
                    adjusted_q3 *= q3_multiplier
                    adjusted_iqr *= iqr_multiplier

                    multipliers_applied.append({
                        "group": group_cols,
                        "q1_multiplier": float(q1_multiplier),
                        "q3_multiplier": float(q3_multiplier),
                        "iqr_multiplier": float(iqr_multiplier),
                        "group_size": int(len(group_values)),
                    })

            # STEP 3: Build confidence interval with adjusted statistics
            if adjusted_iqr == 0:
                # No spread - use small epsilon
                confidence_lower = adjusted_q1 - 1e-10
                confidence_upper = adjusted_q3 + 1e-10
            else:
                confidence_lower = adjusted_q1 - threshold * adjusted_iqr
                confidence_upper = adjusted_q3 + threshold * adjusted_iqr

            # STEP 4: Check if current PROCESSED value is anomalous
            is_anomaly = (current_processed < confidence_lower) or (
                current_processed > confidence_upper
            )

            # STEP 5: Compute metadata
            metadata = {
                "global_q1": float(global_q1),
                "global_q3": float(global_q3),
                "global_iqr": float(global_iqr),
                "adjusted_q1": float(adjusted_q1),
                "adjusted_q3": float(adjusted_q3),
                "adjusted_iqr": float(adjusted_iqr),
                "window_size": int(len(window_valid)),
            }

            # Add preprocessing info if used
            if self.params.get("smoothing") or self.params.get("input_type") != "values":
                metadata["preprocessing"] = {
                    "input_type": self.params.get("input_type", "values"),
                    "smoothing": self.params.get("smoothing"),
                }
                if self.params.get("smoothing"):
                    metadata["preprocessing"]["smoothed_value"] = float(smoothed_values[i])

            if seasonality_components and multipliers_applied:
                metadata["seasonality_groups"] = multipliers_applied

            if is_anomaly:
                if current_processed < confidence_lower:
                    direction = "below"
                    distance = confidence_lower - current_processed
                else:
                    direction = "above"
                    distance = current_processed - confidence_upper

                # Severity: how many adjusted IQR units away
                if adjusted_iqr > 0:
                    severity = distance / adjusted_iqr
                else:
                    severity = float("inf")

                metadata.update(
                    {
                        "direction": direction,
                        "severity": float(severity),
                        "distance": float(distance),
                    }
                )

            results.append(
                DetectionResult(
                    timestamp=current_ts,
                    value=current_val,  # ORIGINAL value
                    processed_value=current_processed,  # PROCESSED value
                    is_anomaly=is_anomaly,
                    confidence_lower=float(confidence_lower),
                    confidence_upper=float(confidence_upper),
                    detection_metadata=metadata,
                )
            )

        return results

    def _get_non_default_params(self) -> Dict[str, Any]:
        """
        Get parameters that differ from defaults.

        Excludes execution parameters (seasonality_components, min_samples_per_group)
        from detector ID hash.
        """
        defaults = {
            "threshold": 1.5,
            "window_size": 100,
            "min_samples": 30,
            "min_samples_per_group": 4,
            "input_type": "values",
            "smoothing": None,
            "smoothing_alpha": 0.3,
            "smoothing_window": 10,
            "window_weights": None,
            "weight_decay": 0.95,
        }
        # Execution parameters that don't affect detector ID
        execution_params = {
            "seasonality_components",
            "min_samples_per_group",
            "smoothing_alpha",  # Only affects smoothing, not algorithm
            "smoothing_window",  # Only affects smoothing, not algorithm
            "weight_decay",  # Only affects weighting, not algorithm
        }

        return {
            k: v for k, v in self.params.items()
            if v != defaults.get(k) and k not in execution_params
        }
