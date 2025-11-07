"""
Z-Score anomaly detector.

Z-Score is a classical statistical method for outlier detection that:
- Uses mean as measure of center
- Uses standard deviation as measure of spread
- Assumes approximately normal distribution

Formula:
- mean_val = mean(values)
- std_val = std(values)
- z_score = (value - mean_val) / std_val
- lower_bound = mean_val - threshold × std_val
- upper_bound = mean_val + threshold × std_val

Note: Z-Score is more sensitive to outliers than MAD because
both mean and std are affected by extreme values.
"""

from typing import Any, Dict

import numpy as np

from detectkit.detectors.base import BaseDetector, DetectionResult


class ZScoreDetector(BaseDetector):
    """
    Z-Score detector for anomaly detection.

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

    Example:
        >>> detector = ZScoreDetector(threshold=3.0, window_size=100)
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
    ):
        """Initialize Z-Score detector with parameters."""
        super().__init__(
            threshold=threshold,
            window_size=window_size,
            min_samples=min_samples,
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

    def detect(self, data: Dict[str, np.ndarray]) -> list[DetectionResult]:
        """
        Perform Z-Score based anomaly detection.

        For each point, uses historical window to compute:
        1. mean_val = mean of window
        2. std_val = standard deviation of window
        3. confidence_interval = [mean - threshold×std, mean + threshold×std]
        4. is_anomaly = value outside confidence interval

        Args:
            data: Dictionary with keys:
                - timestamp: np.array of datetime64[ms]
                - value: np.array of float64 (may contain NaN)
                - seasonality_data: np.array of JSON strings (not used yet)
                - seasonality_columns: list of column names (not used yet)

        Returns:
            List of DetectionResult for each point

        Notes:
            - NaN values are skipped (marked as non-anomalous)
            - First min_samples-1 points are skipped (insufficient history)
            - Uses Bessel's correction (ddof=1) for std calculation
            - Seasonality support will be added in future versions
        """
        timestamps = data["timestamp"]
        values = data["value"]
        threshold = self.params["threshold"]
        window_size = self.params["window_size"]
        min_samples = self.params["min_samples"]

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

            # Compute Z-Score statistics
            mean_val = np.mean(window_valid)
            std_val = np.std(window_valid, ddof=1)  # Bessel's correction

            # Handle edge case: std = 0 (all values identical)
            if std_val == 0:
                # Use small epsilon to avoid division by zero
                # If all values are identical, any deviation is anomalous
                confidence_lower = mean_val - 1e-10
                confidence_upper = mean_val + 1e-10
            else:
                confidence_lower = mean_val - threshold * std_val
                confidence_upper = mean_val + threshold * std_val

            # Check if current value is anomalous
            is_anomaly = (current_val < confidence_lower) or (current_val > confidence_upper)

            # Determine direction and severity
            metadata = {
                "mean": float(mean_val),
                "std": float(std_val),
                "window_size": int(len(window_valid)),
            }

            if is_anomaly:
                if current_val < confidence_lower:
                    direction = "below"
                    distance = confidence_lower - current_val
                else:
                    direction = "above"
                    distance = current_val - confidence_upper

                # Severity: how many standard deviations away (Z-score)
                z_score = abs((current_val - mean_val) / std_val) if std_val > 0 else float("inf")

                metadata.update({
                    "direction": direction,
                    "severity": float(z_score),
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
        """Get parameters that differ from defaults."""
        defaults = {
            "threshold": 3.0,
            "window_size": 100,
            "min_samples": 30,
        }
        return {
            k: v for k, v in self.params.items()
            if v != defaults.get(k)
        }
