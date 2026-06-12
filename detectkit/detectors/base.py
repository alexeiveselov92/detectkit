"""
Base detector interface for anomaly detection.

All detectors must inherit from BaseDetector and implement:
- _validate_params() - parameter validation
- detect() - main detection method
- _get_non_default_params() - for hash generation
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np

from detectkit.utils.json_utils import json_dumps_sorted


@dataclass
class DetectionResult:
    """
    Result of anomaly detection for a single data point.

    Attributes:
        timestamp: Data point timestamp
        value: Actual metric value (ALWAYS original value)
        is_anomaly: Whether point is anomalous
        processed_value: Value analyzed by detector (may be smoothed/transformed).
            Defaults to value when detector applies no preprocessing.
        confidence_lower: Lower bound of confidence interval (for processed_value)
        confidence_upper: Upper bound of confidence interval (for processed_value)
        detection_metadata: Additional metadata (severity, direction, etc.)
    """

    timestamp: np.datetime64
    value: float
    is_anomaly: bool
    processed_value: float | None = None
    confidence_lower: float | None = None
    confidence_upper: float | None = None
    detection_metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.processed_value is None:
            self.processed_value = self.value

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "timestamp": self.timestamp,
            "value": self.value,
            "processed_value": self.processed_value,
            "is_anomaly": self.is_anomaly,
            "confidence_lower": self.confidence_lower,
            "confidence_upper": self.confidence_upper,
            "detection_metadata": json_dumps_sorted(self.detection_metadata or {}),
        }


class BaseDetector(ABC):
    """
    Abstract base class for anomaly detectors.

    All detectors must:
    1. Validate parameters in _validate_params()
    2. Implement detect() to return DetectionResult for each point
    3. Implement _get_non_default_params() for hash generation

    The detector_id (hash) is used for:
    - Storing detections in _dtk_detections table
    - Task locking in _dtk_tasks table

    Example:
        >>> class MyDetector(BaseDetector):
        ...     def __init__(self, threshold: float = 3.0):
        ...         super().__init__(threshold=threshold)
        ...
        ...     def _validate_params(self):
        ...         if self.params["threshold"] <= 0:
        ...             raise ValueError("threshold must be positive")
        ...
        ...     def detect(self, data):
        ...         # Detection logic here
        ...         pass
        ...
        ...     def _get_non_default_params(self):
        ...         defaults = {"threshold": 3.0}
        ...         return {k: v for k, v in self.params.items() if v != defaults.get(k)}
    """

    # Bump when the detection algorithm changes for the SAME parameters
    # (e.g. a statistics convention change): the version feeds the detector
    # ID, so existing detections recompute instead of silently mixing two
    # regimes under one ID.
    ALGORITHM_VERSION: int = 1

    def __init__(self, **params):
        """
        Initialize detector with parameters.

        Args:
            **params: Detector-specific parameters
        """
        self.params = params
        self._validate_params()

    @abstractmethod
    def _validate_params(self):
        """
        Validate detector parameters.

        Should raise ValueError if parameters are invalid.

        Example:
            >>> def _validate_params(self):
            ...     if self.params.get("threshold", 0) <= 0:
            ...         raise ValueError("threshold must be positive")
        """
        pass

    @abstractmethod
    def detect(self, data: dict[str, np.ndarray]) -> list[DetectionResult]:
        """
        Perform anomaly detection on metric data.

        Args:
            data: Dictionary from MetricLoader.load() with keys:
                - timestamp: np.array of datetime64[ms]
                - value: np.array of float64 (may contain NaN for missing data)
                - seasonality_data: np.array of JSON strings
                - seasonality_columns: list of column names

        Returns:
            List of DetectionResult for each data point

        Notes:
            - Handle NaN values appropriately (missing data)
            - Use seasonality_data if detector supports it
            - confidence_lower/upper are optional (only if detector provides them)
            - detection_metadata can include: severity, direction, missing_ratio, etc.

        Example:
            >>> results = detector.detect(data)
            >>> for result in results:
            ...     if result.is_anomaly:
            ...         print(f"Anomaly at {result.timestamp}: {result.value}")
        """
        pass

    def get_detector_id(self) -> str:
        """
        Generate unique detector ID (hash).

        Hash is based on:
        - Detector class name
        - Non-default parameters (sorted)

        This ensures:
        - Same detector with same params = same ID
        - Different params = different ID (allows parallel runs)

        Returns:
            16-character hex string (first 16 chars of SHA256)

        Example:
            >>> detector1 = MADDetector(threshold=3.0)
            >>> detector2 = MADDetector(threshold=3.0)
            >>> detector1.get_detector_id() == detector2.get_detector_id()
            True
            >>> detector3 = MADDetector(threshold=2.5)
            >>> detector1.get_detector_id() != detector3.get_detector_id()
            True
        """
        non_default_params = self._get_non_default_params()
        sorted_params = sorted(non_default_params.items())
        version_tag = f"@v{self.ALGORITHM_VERSION}" if self.ALGORITHM_VERSION != 1 else ""
        hash_string = self.__class__.__name__ + version_tag + str(sorted_params)
        return hashlib.sha256(hash_string.encode()).hexdigest()[:16]

    def get_detector_params(self) -> str:
        """
        Get detector parameters as JSON string.

        Returns JSON with sorted keys for consistency.
        Used for storing in _dtk_detections.detector_params.

        Returns:
            JSON string with sorted parameters

        Example:
            >>> detector = MADDetector(threshold=3.0, min_samples=30)
            >>> detector.get_detector_params()
            '{"min_samples": 30, "threshold": 3.0}'
        """
        non_default_params = self._get_non_default_params()
        return json_dumps_sorted(non_default_params)

    @abstractmethod
    def _get_non_default_params(self) -> dict[str, Any]:
        """
        Get parameters that differ from defaults.

        Used for hash generation and parameter storage.
        Only non-default parameters are included to ensure
        consistent hashing across different instantiations.

        Returns:
            Dictionary of non-default parameters

        Example:
            >>> def _get_non_default_params(self):
            ...     defaults = {"threshold": 3.0, "min_samples": 30}
            ...     return {
            ...         k: v for k, v in self.params.items()
            ...         if v != defaults.get(k)
            ...     }
        """
        pass

    def __repr__(self) -> str:
        """String representation of detector."""
        params_str = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.__class__.__name__}({params_str})"

    def get_context_size(self) -> int:
        """
        Get number of historical points needed for detection.

        Used by task_manager to determine how many points to load
        when resuming from last_processed_timestamp (idempotency).

        Returns:
            Number of historical points needed (0 = no context needed)

        Example:
            - Manual Bounds without input_type: 0 (each point is independent)
            - Manual Bounds with input_type=changes: 1 (need previous point)
            - MAD with window_size=100: 100 (need 100 points for statistics)
            - MAD with window_size=100 and input_type=changes: 100 (already covered)
        """
        context = 0

        # If detector uses a window (MAD, Z-Score, IQR)
        window_size = self.params.get("window_size")
        if window_size is not None:
            context = window_size

        # If input_type requires previous points
        input_type = self.params.get("input_type", "values")
        if input_type in ["changes", "absolute_changes", "log_changes"]:
            # Need at least 1 previous point for computing changes
            context = max(context, 1)

        return context

    def _preprocess_input(self, values: np.ndarray) -> np.ndarray:
        """
        Preprocess input values based on input_type parameter.

        Args:
            values: Original metric values

        Returns:
            Processed values (may be changes, absolute changes, etc.)

        Supported input_type values:
            - "values": No transformation (default)
            - "changes": Relative change (v[t] - v[t-1]) / v[t-1]
            - "absolute_changes": Absolute change v[t] - v[t-1]
            - "log_changes": Log change log(v[t]) - log(v[t-1])

        Note:
            First value has no previous point, so it's set to NaN for changes.
        """
        input_type = self.params.get("input_type", "values")

        if input_type == "values":
            return values

        elif input_type == "changes":
            # Relative change
            with np.errstate(divide="ignore", invalid="ignore"):
                changes = np.diff(values) / values[:-1]
            # First point has no previous value
            return np.concatenate([[np.nan], changes])

        elif input_type == "absolute_changes":
            # Absolute change
            changes = np.diff(values)
            return np.concatenate([[np.nan], changes])

        elif input_type == "log_changes":
            # Logarithmic change (good for exponential growth)
            with np.errstate(divide="ignore", invalid="ignore"):
                log_changes = np.diff(np.log(values + 1))  # +1 to handle zeros
            return np.concatenate([[np.nan], log_changes])

        else:
            raise ValueError(
                f"Unknown input_type: {input_type}. "
                f"Supported values: values, changes, absolute_changes, log_changes"
            )

    def _apply_smoothing(self, values: np.ndarray) -> np.ndarray:
        """
        Apply smoothing to values to reduce noise.

        Args:
            values: Input values

        Returns:
            Smoothed values (same length as input)

        Supported smoothing methods:
            - None: No smoothing (default)
            - "ema": Exponential Moving Average
            - "sma": Simple Moving Average
        """
        smoothing = self.params.get("smoothing")

        if smoothing is None:
            return values

        elif smoothing == "ema":
            alpha = self.params.get("smoothing_alpha", 0.3)
            return self._compute_ema(values, alpha)

        elif smoothing == "sma":
            window = self.params.get("smoothing_window", 10)
            return self._compute_sma(values, window)

        else:
            raise ValueError(
                f"Unknown smoothing method: {smoothing}. " f"Supported methods: ema, sma"
            )

    def _compute_ema(self, values: np.ndarray, alpha: float) -> np.ndarray:
        """
        Compute Exponential Moving Average.

        Args:
            values: Input values
            alpha: Smoothing factor (0 < alpha <= 1)
                  - Higher alpha = more weight to recent values
                  - Lower alpha = smoother (more historical weight)

        Returns:
            Smoothed values

        Formula:
            ema[first_valid] = values[first_valid]
            ema[t] = alpha * values[t] + (1 - alpha) * ema[t-1]

        Leading NaN values stay NaN (the EMA starts at the first valid
        point); later NaN values carry the previous EMA forward.
        """
        if not (0 < alpha <= 1):
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")

        values = np.asarray(values, dtype=float)
        ema = np.full_like(values, np.nan, dtype=float)
        if values.size == 0:
            return ema

        valid_indices = np.flatnonzero(~np.isnan(values))
        if valid_indices.size == 0:
            return ema

        first = valid_indices[0]
        ema[first] = values[first]
        for i in range(first + 1, len(values)):
            if np.isnan(values[i]):
                ema[i] = ema[i - 1]  # Carry forward if missing
            else:
                ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1]

        return ema

    def _compute_sma(self, values: np.ndarray, window: int) -> np.ndarray:
        """Compute a NaN-aware Simple Moving Average in O(n).

        Replaces the previous double-loop with a cumulative-sum trick:
        we accumulate (sum, count) over the valid mask and read the
        window contribution as a difference of two cumulative entries.
        Output matches the original semantics: the first ``window-1``
        points average over what's available, all-NaN windows yield NaN.
        """
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")

        values = np.asarray(values, dtype=float)
        n = values.size
        if n == 0:
            return values.copy()

        valid_mask = ~np.isnan(values)
        safe_values = np.where(valid_mask, values, 0.0)

        # Pad with a leading zero so the difference at index ``i`` covers
        # the inclusive range ``[i-window+1 .. i]`` without a branch.
        cum_vals = np.concatenate(([0.0], np.cumsum(safe_values)))
        cum_count = np.concatenate(([0], np.cumsum(valid_mask.astype(np.int64))))

        idx = np.arange(n)
        starts = np.maximum(0, idx - window + 1)
        ends = idx + 1  # exclusive

        window_sums = cum_vals[ends] - cum_vals[starts]
        window_counts = cum_count[ends] - cum_count[starts]

        with np.errstate(invalid="ignore", divide="ignore"):
            sma = np.where(window_counts > 0, window_sums / window_counts, np.nan)
        return sma
