"""
Median Absolute Deviation (MAD) anomaly detector.

MAD is a robust statistical method for outlier detection that:
- Uses median (robust to outliers) instead of mean
- Measures deviation from median using MAD instead of std
- Less sensitive to extreme values than Z-Score

Formula:
- median_val = median(values)
- mad_val = median(|values - median_val|)
- lower_bound = median_val - threshold × mad_val
- upper_bound = median_val + threshold × mad_val

Seasonality support:
- Groups data by seasonality components
- Computes global statistics (entire window)
- Computes component statistics (per group)
- Applies multipliers to adjust confidence intervals
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import json

import numpy as np

from detectkit.detectors.base import BaseDetector, DetectionResult


class MADDetector(BaseDetector):
    """
    Median Absolute Deviation detector for anomaly detection.

    Detects anomalies by comparing values against confidence intervals
    based on median and MAD (median absolute deviation).

    Parameters:
        threshold (float): Number of MAD units from median (default: 3.0)
            - 3.0 is standard (similar to 3-sigma in Z-Score)
            - Higher = less sensitive (fewer anomalies)
            - Lower = more sensitive (more anomalies)

        window_size (int): Historical window size in points (default: 100)
            - Uses last N points to compute statistics
            - Larger = more stable but less responsive
            - Smaller = more responsive but less stable

        min_samples (int): Minimum samples required for detection (default: 30)
            - Skip detection if window has fewer valid points
            - Ensures statistical reliability

    Example:
        >>> detector = MADDetector(threshold=3.0, window_size=100)
        >>> results = detector.detect(data)
        >>> for r in results:
        ...     if r.is_anomaly:
        ...         print(f"Anomaly: {r.value} outside [{r.confidence_lower}, {r.confidence_upper}]")
    """

    def __init__(
        self,
        threshold: float = 3.0,
        window_size: int = 100,
        min_samples: int = 30,
        seasonality_components: Optional[List[Union[str, List[str]]]] = None,
        min_samples_per_group: int = 10,
    ):
        """
        Initialize MAD detector with parameters.

        Args:
            threshold: Number of MAD units from median
            window_size: Historical window size in points
            min_samples: Minimum total samples required
            seasonality_components: Optional list of seasonality groups
                Examples:
                - ["day_of_week"] - single component
                - [["day_of_week", "hour"]] - combined group
                - ["day", ["hour", "minute"]] - separate + combined
            min_samples_per_group: Minimum samples per seasonality group
        """
        super().__init__(
            threshold=threshold,
            window_size=window_size,
            min_samples=min_samples,
            seasonality_components=seasonality_components,
            min_samples_per_group=min_samples_per_group,
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
        if min_samples is None or min_samples < 1:
            raise ValueError("min_samples must be at least 1")

        if min_samples > window_size:
            raise ValueError("min_samples cannot exceed window_size")

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

        Example:
            Input: ['{"day": 1, "hour": 10}', '{"day": 1, "hour": 11}']
            Output: {"day": array([1, 1]), "hour": array([10, 11])}
        """
        if len(seasonality_data) == 0:
            return {}

        # Parse all JSON strings
        parsed_data = {col: [] for col in seasonality_columns}

        for json_str in seasonality_data:
            if json_str is None or json_str == "{}":
                # Empty seasonality - add None for all columns
                for col in seasonality_columns:
                    parsed_data[col].append(None)
            else:
                try:
                    data_dict = json.loads(json_str)
                    for col in seasonality_columns:
                        parsed_data[col].append(data_dict.get(col))
                except (json.JSONDecodeError, TypeError):
                    # Invalid JSON - add None
                    for col in seasonality_columns:
                        parsed_data[col].append(None)

        # Convert to numpy arrays
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
            group_columns: List of columns to group by (e.g., ["day", "hour"])

        Returns:
            Boolean mask for window indices matching current point's seasonality

        Example:
            Current point: day=1, hour=10
            Group columns: ["day", "hour"]
            Returns: mask where (day==1) AND (hour==10)
        """
        if not group_columns or not seasonality_dict:
            # No grouping - return all True
            window_size = current_idx - window_start
            return np.ones(window_size, dtype=bool)

        # Get current point's seasonality values
        current_values = {}
        for col in group_columns:
            if col in seasonality_dict:
                current_values[col] = seasonality_dict[col][current_idx]
            else:
                # Column not found - no filtering
                return np.ones(current_idx - window_start, dtype=bool)

        # Create combined mask (AND of all columns)
        mask = np.ones(current_idx - window_start, dtype=bool)

        for col in group_columns:
            current_val = current_values[col]
            window_vals = seasonality_dict[col][window_start:current_idx]
            mask &= (window_vals == current_val)

        return mask

    def detect(self, data: Dict[str, np.ndarray]) -> list[DetectionResult]:
        """
        Perform MAD-based anomaly detection with seasonality support.

        Algorithm (TECHNICAL_SPEC.md section 8):
        1. Parse seasonality data
        2. For each point:
           - Compute global statistics (entire window)
           - For each seasonality group:
             * Create mask matching current point's seasonality
             * Compute group statistics
             * Calculate multipliers
           - Apply all multipliers to adjust intervals
           - Detect anomalies

        Args:
            data: Dictionary with keys:
                - timestamp: np.array of datetime64[ms]
                - value: np.array of float64 (may contain NaN)
                - seasonality_data: np.array of JSON strings
                - seasonality_columns: list of column names

        Returns:
            List of DetectionResult for each point
        """
        timestamps = data["timestamp"]
        values = data["value"]
        seasonality_data = data.get("seasonality_data", np.array([]))
        seasonality_columns = data.get("seasonality_columns", [])

        threshold = self.params["threshold"]
        window_size = self.params["window_size"]
        min_samples = self.params["min_samples"]
        seasonality_components = self.params.get("seasonality_components")
        min_samples_per_group = self.params.get("min_samples_per_group", 10)

        # Parse seasonality data once
        seasonality_dict = {}
        if len(seasonality_data) > 0 and seasonality_columns:
            seasonality_dict = self._parse_seasonality_data(
                seasonality_data, seasonality_columns
            )

        results = []
        n_points = len(timestamps)

        for i in range(n_points):
            current_val = values[i]
            current_ts = timestamps[i]

            # Skip NaN values
            if np.isnan(current_val):
                results.append(
                    DetectionResult(
                        timestamp=current_ts,
                        value=current_val,
                        is_anomaly=False,
                        detection_metadata={"reason": "missing_data"},
                    )
                )
                continue

            # Get historical window (not including current point)
            window_start = max(0, i - window_size)
            window_values = values[window_start:i]

            # Filter out NaN values from window
            valid_mask = ~np.isnan(window_values)
            window_valid = window_values[valid_mask]

            # Check if we have enough samples
            if len(window_valid) < min_samples:
                results.append(
                    DetectionResult(
                        timestamp=current_ts,
                        value=current_val,
                        is_anomaly=False,
                        detection_metadata={
                            "reason": "insufficient_data",
                            "window_size": int(len(window_valid)),
                            "min_samples": min_samples,
                        },
                    )
                )
                continue

            # STEP 1: Compute GLOBAL statistics (entire window)
            global_median = np.median(window_valid)
            global_abs_deviations = np.abs(window_valid - global_median)
            global_mad = np.median(global_abs_deviations)

            # Initialize adjusted statistics with global values
            adjusted_median = global_median
            adjusted_mad = global_mad

            # STEP 2: Apply seasonality adjustments
            multipliers_applied = []

            if seasonality_components and seasonality_dict:
                # Process each seasonality group
                for group in seasonality_components:
                    # Normalize to list (handle both str and List[str])
                    group_cols = [group] if isinstance(group, str) else group

                    # Create mask for this group
                    season_mask = self._create_seasonality_mask(
                        seasonality_dict, window_start, i, group_cols
                    )

                    # Apply mask to window (only valid values + seasonality match)
                    combined_mask = valid_mask.copy()
                    combined_mask[valid_mask] &= season_mask

                    group_values = window_values[combined_mask]

                    # Check if enough samples in group
                    if len(group_values) < min_samples_per_group:
                        # Insufficient data - skip this group (multiplier = 1.0)
                        multipliers_applied.append({
                            "group": group_cols,
                            "median_multiplier": 1.0,
                            "mad_multiplier": 1.0,
                            "reason": "insufficient_group_data",
                            "group_size": int(len(group_values)),
                        })
                        continue

                    # Compute group statistics
                    group_median = np.median(group_values)
                    group_abs_dev = np.abs(group_values - group_median)
                    group_mad = np.median(group_abs_dev)

                    # Calculate multipliers
                    if global_median != 0:
                        median_multiplier = group_median / global_median
                    else:
                        median_multiplier = 1.0

                    if global_mad != 0:
                        mad_multiplier = group_mad / global_mad
                    else:
                        mad_multiplier = 1.0

                    # Apply multipliers
                    adjusted_median *= median_multiplier
                    adjusted_mad *= mad_multiplier

                    multipliers_applied.append({
                        "group": group_cols,
                        "median_multiplier": float(median_multiplier),
                        "mad_multiplier": float(mad_multiplier),
                        "group_size": int(len(group_values)),
                    })

            # STEP 3: Build confidence interval
            if adjusted_mad == 0:
                # All values identical - any deviation is anomalous
                confidence_lower = adjusted_median - 1e-10
                confidence_upper = adjusted_median + 1e-10
            else:
                confidence_lower = adjusted_median - threshold * adjusted_mad
                confidence_upper = adjusted_median + threshold * adjusted_mad

            # STEP 4: Check if current value is anomalous
            is_anomaly = (current_val < confidence_lower) or (current_val > confidence_upper)

            # Build metadata
            metadata = {
                "global_median": float(global_median),
                "global_mad": float(global_mad),
                "adjusted_median": float(adjusted_median),
                "adjusted_mad": float(adjusted_mad),
                "window_size": int(len(window_valid)),
            }

            if seasonality_components and multipliers_applied:
                metadata["seasonality_groups"] = multipliers_applied

            if is_anomaly:
                if current_val < confidence_lower:
                    direction = "below"
                    distance = confidence_lower - current_val
                else:
                    direction = "above"
                    distance = current_val - confidence_upper

                # Severity: how many adjusted MAD units away
                severity = distance / adjusted_mad if adjusted_mad > 0 else float("inf")

                metadata.update({
                    "direction": direction,
                    "severity": float(severity),
                    "distance": float(distance),
                })

            results.append(
                DetectionResult(
                    timestamp=current_ts,
                    value=current_val,
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
            "threshold": 3.0,
            "window_size": 100,
            "min_samples": 30,
            "min_samples_per_group": 10,
        }
        # Execution parameters that don't affect detector ID
        execution_params = {"seasonality_components", "min_samples_per_group"}

        return {
            k: v for k, v in self.params.items()
            if v != defaults.get(k) and k not in execution_params
        }
