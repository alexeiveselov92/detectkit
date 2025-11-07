"""
Manual Bounds anomaly detector.

Simple detector that uses user-specified thresholds for anomaly detection.
Useful when domain knowledge exists about acceptable ranges.

Examples:
- CPU usage should be <= 90%
- Response time should be <= 1000ms
- Queue size should be >= 0 and <= 10000
"""

from typing import Any, Dict, Optional

import numpy as np

from detectkit.detectors.base import BaseDetector, DetectionResult


class ManualBoundsDetector(BaseDetector):
    """
    Manual threshold detector for anomaly detection.

    Detects anomalies by comparing values against user-specified bounds.
    Does not use historical data - purely threshold-based.

    Parameters:
        lower_bound (float | None): Minimum acceptable value (default: None = no lower limit)
            - Values below this are anomalous
            - None means no lower bound

        upper_bound (float | None): Maximum acceptable value (default: None = no upper limit)
            - Values above this are anomalous
            - None means no upper bound

    At least one bound must be specified.

    Example:
        >>> # Detect values above 100
        >>> detector = ManualBoundsDetector(upper_bound=100.0)
        >>> results = detector.detect(data)

        >>> # Detect values outside [10, 90]
        >>> detector = ManualBoundsDetector(lower_bound=10.0, upper_bound=90.0)
        >>> results = detector.detect(data)
    """

    def __init__(
        self,
        lower_bound: Optional[float] = None,
        upper_bound: Optional[float] = None,
    ):
        """Initialize Manual Bounds detector with thresholds."""
        super().__init__(
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )

    def _validate_params(self):
        """Validate detector parameters."""
        lower_bound = self.params.get("lower_bound")
        upper_bound = self.params.get("upper_bound")

        # At least one bound must be specified
        if lower_bound is None and upper_bound is None:
            raise ValueError("At least one of lower_bound or upper_bound must be specified")

        # If both specified, lower must be less than upper
        if lower_bound is not None and upper_bound is not None:
            if lower_bound >= upper_bound:
                raise ValueError("lower_bound must be less than upper_bound")

    def detect(self, data: Dict[str, np.ndarray]) -> list[DetectionResult]:
        """
        Perform threshold-based anomaly detection.

        Simply checks if each value is outside the specified bounds.
        Does not use historical window - purely threshold-based.

        Args:
            data: Dictionary with keys:
                - timestamp: np.array of datetime64[ms]
                - value: np.array of float64 (may contain NaN)
                - seasonality_data: np.array of JSON strings (not used)
                - seasonality_columns: list of column names (not used)

        Returns:
            List of DetectionResult for each point

        Notes:
            - NaN values are skipped (marked as non-anomalous)
            - No historical window needed
            - No minimum samples requirement
        """
        timestamps = data["timestamp"]
        values = data["value"]
        lower_bound = self.params.get("lower_bound")
        upper_bound = self.params.get("upper_bound")

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

            # Check bounds
            is_anomaly = False
            direction = None
            distance = 0.0

            if lower_bound is not None and current_val < lower_bound:
                is_anomaly = True
                direction = "below"
                distance = lower_bound - current_val

            if upper_bound is not None and current_val > upper_bound:
                is_anomaly = True
                direction = "above"
                distance = current_val - upper_bound

            # Prepare metadata
            metadata = {}
            if is_anomaly:
                metadata["direction"] = direction
                metadata["distance"] = float(distance)

                # Severity: relative distance from bound
                if direction == "below":
                    # How far below as percentage of range
                    if upper_bound is not None:
                        bound_range = upper_bound - lower_bound
                        severity = distance / bound_range if bound_range > 0 else float("inf")
                    else:
                        # No upper bound, just use absolute distance
                        severity = distance
                else:  # above
                    if lower_bound is not None:
                        bound_range = upper_bound - lower_bound
                        severity = distance / bound_range if bound_range > 0 else float("inf")
                    else:
                        severity = distance

                metadata["severity"] = float(severity)

            results.append(
                DetectionResult(
                    timestamp=current_ts,
                    value=current_val,
                    is_anomaly=is_anomaly,
                    confidence_lower=lower_bound,
                    confidence_upper=upper_bound,
                    detection_metadata=metadata,
                )
            )

        return results

    def _get_non_default_params(self) -> Dict[str, Any]:
        """Get parameters that differ from defaults."""
        # No defaults - all params are non-default
        return {
            k: v for k, v in self.params.items()
            if v is not None
        }
