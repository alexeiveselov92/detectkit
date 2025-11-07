"""
Z-Score anomaly detector.

Z-Score is a classical statistical method for outlier detection that:
- Uses mean as measure of center
- Uses standard deviation as measure of spread
- Assumes approximately normal distribution
- Supports seasonality grouping for adaptive thresholds

Formula:
- mean_val = mean(values)
- std_val = std(values)
- z_score = (value - mean_val) / std_val
- lower_bound = mean_val - threshold × std_val
- upper_bound = mean_val + threshold × std_val

With seasonality:
- Computes global statistics (entire window)
- Computes group statistics (seasonality subset)
- Applies multipliers: adjusted_stat = global_stat × group_multiplier

Note: Z-Score is more sensitive to outliers than MAD because
both mean and std are affected by extreme values.
"""

import json
from typing import Any, Dict, List, Optional, Union

import numpy as np

from detectkit.detectors.base import BaseDetector, DetectionResult


class ZScoreDetector(BaseDetector):
    """
    Z-Score detector for anomaly detection with seasonality support.

    Detects anomalies by comparing values against confidence intervals
    based on mean and standard deviation (Z-Score method).

    Parameters:
        threshold (float): Number of standard deviations from mean (default: 3.0)
            - 3.0 is standard (99.7% of normal data within ±3σ)
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

        min_samples_per_group (int): Minimum samples per seasonality group (default: 3)
            - Groups with fewer samples use global statistics

    Example:
        >>> # Without seasonality
        >>> detector = ZScoreDetector(threshold=3.0, window_size=100)
        >>> results = detector.detect(data)

        >>> # With seasonality
        >>> detector = ZScoreDetector(
        ...     threshold=3.0,
        ...     window_size=2016,
        ...     seasonality_components=["hour_of_day", "day_of_week"]
        ... )
        >>> results = detector.detect(data)
    """

    def __init__(
        self,
        threshold: float = 3.0,
        window_size: int = 100,
        min_samples: int = 30,
        seasonality_components: Optional[List[Union[str, List[str]]]] = None,
        min_samples_per_group: int = 3,
    ):
        """Initialize Z-Score detector with parameters."""
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
        if min_samples is None or min_samples < 2:
            raise ValueError("min_samples must be at least 2")

        if min_samples > window_size:
            raise ValueError("min_samples cannot exceed window_size")

        min_samples_per_group = self.params.get("min_samples_per_group", 3)
        if min_samples_per_group < 1:
            raise ValueError("min_samples_per_group must be at least 1")

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
        Perform Z-Score based anomaly detection with optional seasonality support.

        For each point, uses historical window to compute:
        1. Global mean and std (entire window)
        2. If seasonality configured: group mean and std (seasonality subset)
        3. Apply multipliers: adjusted = global × (group / global)
        4. Build confidence interval: [mean - threshold×std, mean + threshold×std]
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
            - Uses Bessel's correction (ddof=1) for std calculation
            - Seasonality grouping creates adaptive confidence intervals
        """
        timestamps = data["timestamp"]
        values = data["value"]
        threshold = self.params["threshold"]
        window_size = self.params["window_size"]
        min_samples = self.params["min_samples"]

        # Seasonality parameters
        seasonality_components = self.params.get("seasonality_components")
        min_samples_per_group = self.params.get("min_samples_per_group", 3)

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
            window_valid = window_values[~np.isnan(window_values)]

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
            global_mean = np.mean(window_valid)
            global_std = np.std(window_valid, ddof=1)

            # Initialize adjusted statistics
            adjusted_mean = global_mean
            adjusted_std = global_std

            # STEP 2: Apply seasonality adjustments
            if seasonality_components and seasonality_dict:
                for group in seasonality_components:
                    # Convert single string to list
                    group_cols = [group] if isinstance(group, str) else group

                    # Create mask for this seasonality group
                    season_mask = self._create_seasonality_mask(
                        seasonality_dict, window_start, i, group_cols
                    )

                    # Filter window by seasonality mask
                    season_indices = np.where(season_mask)[0]
                    if len(season_indices) < min_samples_per_group:
                        # Not enough samples in this group - skip adjustment
                        continue

                    # Get values for this seasonality group
                    group_window = window_values[season_indices]
                    group_valid = group_window[~np.isnan(group_window)]

                    if len(group_valid) < min_samples_per_group:
                        continue

                    # Compute group statistics
                    group_mean = np.mean(group_valid)
                    group_std = np.std(group_valid, ddof=1)

                    # Calculate multipliers (avoid division by zero)
                    if global_mean != 0:
                        mean_multiplier = group_mean / global_mean
                    else:
                        mean_multiplier = 1.0

                    if global_std > 0:
                        std_multiplier = group_std / global_std
                    else:
                        std_multiplier = 1.0

                    # Apply multipliers
                    adjusted_mean *= mean_multiplier
                    adjusted_std *= std_multiplier

            # STEP 3: Build confidence interval with adjusted statistics
            if adjusted_std == 0:
                # All values identical - use small epsilon
                confidence_lower = adjusted_mean - 1e-10
                confidence_upper = adjusted_mean + 1e-10
            else:
                confidence_lower = adjusted_mean - threshold * adjusted_std
                confidence_upper = adjusted_mean + threshold * adjusted_std

            # STEP 4: Check if current value is anomalous
            is_anomaly = (current_val < confidence_lower) or (
                current_val > confidence_upper
            )

            # STEP 5: Compute metadata
            metadata = {
                "global_mean": float(global_mean),
                "global_std": float(global_std),
                "adjusted_mean": float(adjusted_mean),
                "adjusted_std": float(adjusted_std),
                "window_size": int(len(window_valid)),
            }

            if is_anomaly:
                if current_val < confidence_lower:
                    direction = "below"
                    distance = confidence_lower - current_val
                else:
                    direction = "above"
                    distance = current_val - confidence_upper

                # Severity: how many adjusted std away
                if adjusted_std > 0:
                    z_score = abs((current_val - adjusted_mean) / adjusted_std)
                else:
                    z_score = float("inf")

                metadata.update(
                    {
                        "direction": direction,
                        "severity": float(z_score),
                        "distance": float(distance),
                    }
                )

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
        """Get parameters that differ from defaults."""
        defaults = {
            "threshold": 3.0,
            "window_size": 100,
            "min_samples": 30,
            "min_samples_per_group": 3,
        }
        return {
            k: v
            for k, v in self.params.items()
            if k not in {"seasonality_components"}
            and v != defaults.get(k)
        }
