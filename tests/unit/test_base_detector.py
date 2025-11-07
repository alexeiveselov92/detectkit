"""Tests for BaseDetector and DetectionResult."""

from datetime import datetime
from typing import Any, Dict

import numpy as np
import pytest

from detectkit.detectors.base import BaseDetector, DetectionResult


# Mock detector for testing
class MockDetector(BaseDetector):
    """Simple mock detector for testing."""

    def __init__(self, threshold: float = 3.0, min_samples: int = 30):
        super().__init__(threshold=threshold, min_samples=min_samples)

    def _validate_params(self):
        """Validate parameters."""
        if self.params.get("threshold", 0) <= 0:
            raise ValueError("threshold must be positive")
        if self.params.get("min_samples", 0) < 1:
            raise ValueError("min_samples must be at least 1")

    def detect(self, data: Dict[str, np.ndarray]) -> list[DetectionResult]:
        """Mock detection - marks values > threshold as anomalies."""
        results = []
        timestamps = data["timestamp"]
        values = data["value"]

        threshold = self.params["threshold"]

        for ts, val in zip(timestamps, values):
            is_anomaly = not np.isnan(val) and val > threshold
            results.append(
                DetectionResult(
                    timestamp=ts,
                    value=val,
                    is_anomaly=is_anomaly,
                    confidence_lower=0.0 if not np.isnan(val) else None,
                    confidence_upper=threshold if not np.isnan(val) else None,
                    detection_metadata={"mock": True},
                )
            )

        return results

    def _get_non_default_params(self) -> Dict[str, Any]:
        """Return non-default parameters."""
        defaults = {"threshold": 3.0, "min_samples": 30}
        return {k: v for k, v in self.params.items() if v != defaults.get(k)}


class TestDetectionResult:
    """Test DetectionResult dataclass."""

    def test_init(self):
        """Test DetectionResult initialization."""
        ts = np.datetime64("2024-01-01T00:00:00", "ms")
        result = DetectionResult(
            timestamp=ts,
            value=10.5,
            is_anomaly=True,
            confidence_lower=5.0,
            confidence_upper=15.0,
            detection_metadata={"severity": "high"},
        )

        assert result.timestamp == ts
        assert result.value == 10.5
        assert result.is_anomaly is True
        assert result.confidence_lower == 5.0
        assert result.confidence_upper == 15.0
        assert result.detection_metadata == {"severity": "high"}

    def test_init_minimal(self):
        """Test DetectionResult with minimal fields."""
        ts = np.datetime64("2024-01-01T00:00:00", "ms")
        result = DetectionResult(timestamp=ts, value=10.5, is_anomaly=False)

        assert result.timestamp == ts
        assert result.value == 10.5
        assert result.is_anomaly is False
        assert result.confidence_lower is None
        assert result.confidence_upper is None
        assert result.detection_metadata is None

    def test_to_dict(self):
        """Test conversion to dictionary."""
        ts = np.datetime64("2024-01-01T00:00:00", "ms")
        result = DetectionResult(
            timestamp=ts,
            value=10.5,
            is_anomaly=True,
            confidence_lower=5.0,
            confidence_upper=15.0,
            detection_metadata={"severity": "high", "direction": "up"},
        )

        d = result.to_dict()

        assert d["timestamp"] == ts
        assert d["value"] == 10.5
        assert d["is_anomaly"] is True
        assert d["confidence_lower"] == 5.0
        assert d["confidence_upper"] == 15.0

        # Parse metadata JSON and check values
        import json
        metadata = json.loads(d["detection_metadata"])
        assert metadata["direction"] == "up"
        assert metadata["severity"] == "high"

    def test_to_dict_no_metadata(self):
        """Test to_dict with no metadata."""
        ts = np.datetime64("2024-01-01T00:00:00", "ms")
        result = DetectionResult(timestamp=ts, value=10.5, is_anomaly=False)

        d = result.to_dict()

        assert d["detection_metadata"] == "{}"


class TestBaseDetector:
    """Test BaseDetector abstract class."""

    def test_init(self):
        """Test detector initialization."""
        detector = MockDetector(threshold=5.0)

        assert detector.params["threshold"] == 5.0
        assert detector.params["min_samples"] == 30  # default

    def test_init_with_defaults(self):
        """Test initialization with all defaults."""
        detector = MockDetector()

        assert detector.params["threshold"] == 3.0
        assert detector.params["min_samples"] == 30

    def test_init_validation_error(self):
        """Test that validation is called during init."""
        with pytest.raises(ValueError, match="threshold must be positive"):
            MockDetector(threshold=-1.0)

        with pytest.raises(ValueError, match="min_samples must be at least 1"):
            MockDetector(min_samples=0)

    def test_detect(self):
        """Test detect method."""
        detector = MockDetector(threshold=5.0)

        data = {
            "timestamp": np.array(
                [
                    np.datetime64("2024-01-01T00:00:00", "ms"),
                    np.datetime64("2024-01-01T00:10:00", "ms"),
                    np.datetime64("2024-01-01T00:20:00", "ms"),
                ]
            ),
            "value": np.array([3.0, 6.0, 4.0]),
            "seasonality_data": np.array(["{}"] * 3),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert len(results) == 3
        assert results[0].is_anomaly == False  # 3.0 <= 5.0
        assert results[1].is_anomaly == True  # 6.0 > 5.0
        assert results[2].is_anomaly == False  # 4.0 <= 5.0

    def test_detect_with_nan(self):
        """Test detect with NaN values."""
        detector = MockDetector(threshold=5.0)

        data = {
            "timestamp": np.array(
                [
                    np.datetime64("2024-01-01T00:00:00", "ms"),
                    np.datetime64("2024-01-01T00:10:00", "ms"),
                ]
            ),
            "value": np.array([3.0, np.nan]),
            "seasonality_data": np.array(["{}"] * 2),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert len(results) == 2
        assert results[0].is_anomaly == False
        assert results[1].is_anomaly == False  # NaN is not anomaly

    def test_get_detector_id_same_params(self):
        """Test that same params produce same ID."""
        detector1 = MockDetector(threshold=5.0, min_samples=30)
        detector2 = MockDetector(threshold=5.0, min_samples=30)

        assert detector1.get_detector_id() == detector2.get_detector_id()

    def test_get_detector_id_different_params(self):
        """Test that different params produce different ID."""
        detector1 = MockDetector(threshold=5.0)
        detector2 = MockDetector(threshold=3.0)

        assert detector1.get_detector_id() != detector2.get_detector_id()

    def test_get_detector_id_default_vs_explicit(self):
        """Test that default param equals explicit param."""
        detector1 = MockDetector()  # threshold=3.0 by default
        detector2 = MockDetector(threshold=3.0)  # explicit

        # Should be same because both have threshold=3.0
        assert detector1.get_detector_id() == detector2.get_detector_id()

    def test_get_detector_id_format(self):
        """Test that detector ID is 16-char hex string."""
        detector = MockDetector()
        detector_id = detector.get_detector_id()

        assert len(detector_id) == 16
        assert all(c in "0123456789abcdef" for c in detector_id)

    def test_get_detector_params(self):
        """Test get_detector_params returns JSON."""
        detector = MockDetector(threshold=5.0)
        params_json = detector.get_detector_params()

        # Parse JSON and check values
        import json
        params = json.loads(params_json)
        assert params["threshold"] == 5.0
        # min_samples=30 is default, so not included
        assert "min_samples" not in params

    def test_get_detector_params_all_defaults(self):
        """Test params JSON with all defaults."""
        detector = MockDetector()
        params_json = detector.get_detector_params()

        # All defaults → empty JSON
        assert params_json == "{}"

    def test_get_detector_params_sorted(self):
        """Test that params are sorted."""
        detector = MockDetector(threshold=5.0, min_samples=50)
        params_json = detector.get_detector_params()

        # Should be sorted: min_samples before threshold
        import json

        params = json.loads(params_json)
        keys = list(params.keys())
        assert keys == sorted(keys)

    def test_repr(self):
        """Test string representation."""
        detector = MockDetector(threshold=5.0, min_samples=30)
        repr_str = repr(detector)

        assert "MockDetector" in repr_str
        assert "threshold=5.0" in repr_str
        assert "min_samples=30" in repr_str
