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
from typing import Any, Dict, Optional

import numpy as np

try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    import json
    HAS_ORJSON = False


def json_dumps_sorted(obj):
    """JSON dumps with sorted keys - handles both orjson and standard json."""
    if HAS_ORJSON:
        return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS).decode('utf-8')
    else:
        return json.dumps(obj, sort_keys=True)


@dataclass
class DetectionResult:
    """
    Result of anomaly detection for a single data point.

    Attributes:
        timestamp: Data point timestamp
        value: Actual metric value (ALWAYS original value)
        processed_value: Value analyzed by detector (may be smoothed/transformed)
        is_anomaly: Whether point is anomalous
        confidence_lower: Lower bound of confidence interval (for processed_value)
        confidence_upper: Upper bound of confidence interval (for processed_value)
        detection_metadata: Additional metadata (severity, direction, etc.)
    """

    timestamp: np.datetime64
    value: float
    processed_value: float
    is_anomaly: bool
    confidence_lower: Optional[float] = None
    confidence_upper: Optional[float] = None
    detection_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
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
    def detect(self, data: Dict[str, np.ndarray]) -> list[DetectionResult]:
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
        hash_string = self.__class__.__name__ + str(sorted_params)
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
    def _get_non_default_params(self) -> Dict[str, Any]:
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
            with np.errstate(divide='ignore', invalid='ignore'):
                changes = np.diff(values) / values[:-1]
            # First point has no previous value
            return np.concatenate([[np.nan], changes])

        elif input_type == "absolute_changes":
            # Absolute change
            changes = np.diff(values)
            return np.concatenate([[np.nan], changes])

        elif input_type == "log_changes":
            # Logarithmic change (good for exponential growth)
            with np.errstate(divide='ignore', invalid='ignore'):
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
                f"Unknown smoothing method: {smoothing}. "
                f"Supported methods: ema, sma"
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
            ema[0] = values[0]
            ema[t] = alpha * values[t] + (1 - alpha) * ema[t-1]
        """
        if not (0 < alpha <= 1):
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")

        ema = np.zeros_like(values, dtype=float)
        ema[0] = values[0]

        for i in range(1, len(values)):
            if np.isnan(values[i]):
                ema[i] = ema[i-1]  # Carry forward if missing
            else:
                ema[i] = alpha * values[i] + (1 - alpha) * ema[i-1]

        return ema

    def _compute_sma(self, values: np.ndarray, window: int) -> np.ndarray:
        """
        Compute Simple Moving Average.

        Args:
            values: Input values
            window: Window size for averaging

        Returns:
            Smoothed values

        Note:
            For first (window-1) points, uses available data.
        """
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")

        sma = np.zeros_like(values, dtype=float)

        for i in range(len(values)):
            start = max(0, i - window + 1)
            window_values = values[start:i+1]
            # Filter out NaN values
            valid_values = window_values[~np.isnan(window_values)]
            if len(valid_values) > 0:
                sma[i] = np.mean(valid_values)
            else:
                sma[i] = np.nan

        return sma

    def _compute_weights(self, window_size: int) -> np.ndarray:
        """
        Compute weights for points in window.

        Args:
            window_size: Size of the window

        Returns:
            Array of weights (normalized to sum to 1)

        Supported window_weights methods:
            - None: Uniform weights (all points equal)
            - "exponential": Exponential decay (recent points have more weight)
            - "linear": Linear increase (recent points have more weight)
        """
        window_weights = self.params.get("window_weights")

        if window_weights is None:
            # Uniform weights
            return np.ones(window_size) / window_size

        elif window_weights == "exponential":
            weight_decay = self.params.get("weight_decay", 0.95)
            if not (0 < weight_decay < 1):
                raise ValueError(f"weight_decay must be in (0, 1), got {weight_decay}")

            # Older points get less weight: decay^k for k in [window_size, 1]
            weights = np.array([weight_decay ** k for k in range(window_size, 0, -1)])
            return weights / weights.sum()

        elif window_weights == "linear":
            # Linear increase: 1, 2, 3, ..., window_size
            weights = np.arange(1, window_size + 1, dtype=float)
            return weights / weights.sum()

        else:
            raise ValueError(
                f"Unknown window_weights method: {window_weights}. "
                f"Supported methods: exponential, linear"
            )
