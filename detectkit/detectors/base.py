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
        value: Actual metric value
        is_anomaly: Whether point is anomalous
        confidence_lower: Lower bound of confidence interval (if available)
        confidence_upper: Upper bound of confidence interval (if available)
        detection_metadata: Additional metadata (severity, direction, etc.)
    """

    timestamp: np.datetime64
    value: float
    is_anomaly: bool
    confidence_lower: Optional[float] = None
    confidence_upper: Optional[float] = None
    detection_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "timestamp": self.timestamp,
            "value": self.value,
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
