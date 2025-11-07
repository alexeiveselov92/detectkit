"""
Interquartile Range (IQR) anomaly detector.

IQR is a robust statistical method for outlier detection that:
- Uses quartiles (Q1, Q3) instead of mean
- Measures spread using IQR = Q3 - Q1
- Less sensitive to outliers than Z-Score
- Similar robustness to MAD

Formula:
- Q1 = 25th percentile
- Q3 = 75th percentile
- IQR = Q3 - Q1
- lower_bound = Q1 - threshold × IQR
- upper_bound = Q3 + threshold × IQR

Default threshold = 1.5 (standard Tukey's fences)
"""

from typing import Any, Dict

import numpy as np

from detectkit.detectors.base import BaseDetector, DetectionResult


class IQRDetector(BaseDetector):
    """
    Interquartile Range (IQR) detector for anomaly detection.

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

    Example:
        >>> detector = IQRDetector(threshold=1.5, window_size=100)
        >>> results = detector.detect(data)
        >>> for r in results:
        ...     if r.is_anomaly:
        ...         print(f"Anomaly: {r.value} outside [{r.confidence_lower}, {r.confidence_upper}]")
    """

    def __init__(
        self,
        threshold: float = 1.5,
        window_size: int = 100,
        min_samples: int = 30,
    ):
        """Initialize IQR detector with parameters."""
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
        if min_samples is None or min_samples < 4:
            raise ValueError("min_samples must be at least 4 (for quartiles)")

        if min_samples > window_size:
            raise ValueError("min_samples cannot exceed window_size")

    def detect(self, data: Dict[str, np.ndarray]) -> list[DetectionResult]:
        """
        Perform IQR-based anomaly detection.

        For each point, uses historical window to compute:
        1. Q1 = 25th percentile of window
        2. Q3 = 75th percentile of window
        3. IQR = Q3 - Q1
        4. lower_bound = Q1 - threshold × IQR
        5. upper_bound = Q3 + threshold × IQR
        6. is_anomaly = value outside [lower_bound, upper_bound]

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
            - Uses linear interpolation for percentile calculation
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

            # Compute IQR statistics
            q1 = np.percentile(window_valid, 25)
            q3 = np.percentile(window_valid, 75)
            iqr = q3 - q1

            # Handle edge case: IQR = 0 (all values in same range)
            if iqr == 0:
                # Use Q1/Q3 with small epsilon
                # If no spread, any value outside Q1-Q3 is anomalous
                confidence_lower = q1 - 1e-10
                confidence_upper = q3 + 1e-10
            else:
                confidence_lower = q1 - threshold * iqr
                confidence_upper = q3 + threshold * iqr

            # Check if current value is anomalous
            is_anomaly = (current_val < confidence_lower) or (current_val > confidence_upper)

            # Determine direction and severity
            metadata = {
                "q1": float(q1),
                "q3": float(q3),
                "iqr": float(iqr),
                "window_size": int(len(window_valid)),
            }

            if is_anomaly:
                if current_val < confidence_lower:
                    direction = "below"
                    distance = confidence_lower - current_val
                else:
                    direction = "above"
                    distance = current_val - confidence_upper

                # Severity: how many IQR units away
                severity = distance / iqr if iqr > 0 else float("inf")

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
        """Get parameters that differ from defaults."""
        defaults = {
            "threshold": 1.5,
            "window_size": 100,
            "min_samples": 30,
        }
        return {
            k: v for k, v in self.params.items()
            if v != defaults.get(k)
        }
