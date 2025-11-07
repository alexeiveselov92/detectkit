"""Tests for MAD (Median Absolute Deviation) detector."""

import numpy as np
import pytest

from detectkit.detectors.statistical.mad import MADDetector


class TestMADDetectorInit:
    """Test MAD detector initialization and validation."""

    def test_init_defaults(self):
        """Test initialization with default parameters."""
        detector = MADDetector()

        assert detector.params["threshold"] == 3.0
        assert detector.params["window_size"] == 100
        assert detector.params["min_samples"] == 30

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        detector = MADDetector(threshold=2.5, window_size=50, min_samples=20)

        assert detector.params["threshold"] == 2.5
        assert detector.params["window_size"] == 50
        assert detector.params["min_samples"] == 20

    def test_validation_negative_threshold(self):
        """Test that negative threshold raises error."""
        with pytest.raises(ValueError, match="threshold must be positive"):
            MADDetector(threshold=-1.0)

    def test_validation_zero_threshold(self):
        """Test that zero threshold raises error."""
        with pytest.raises(ValueError, match="threshold must be positive"):
            MADDetector(threshold=0.0)

    def test_validation_invalid_window_size(self):
        """Test that invalid window_size raises error."""
        with pytest.raises(ValueError, match="window_size must be at least 1"):
            MADDetector(window_size=0)

    def test_validation_invalid_min_samples(self):
        """Test that invalid min_samples raises error."""
        with pytest.raises(ValueError, match="min_samples must be at least 1"):
            MADDetector(min_samples=0)

    def test_validation_min_samples_exceeds_window(self):
        """Test that min_samples > window_size raises error."""
        with pytest.raises(ValueError, match="min_samples cannot exceed window_size"):
            MADDetector(window_size=50, min_samples=100)


class TestMADDetectorDetect:
    """Test MAD detector detection logic."""

    def test_detect_no_anomalies(self):
        """Test detection with no anomalies."""
        detector = MADDetector(threshold=3.0, window_size=10, min_samples=5)

        # Generate normal data
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(20)]
            ),
            "value": np.array([10.0] * 20),  # All values identical
            "seasonality_data": np.array(["{}"] * 20),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert len(results) == 20
        # First min_samples-1 points skipped
        for i in range(5):
            assert results[i].is_anomaly == False
            assert results[i].detection_metadata["reason"] == "insufficient_data"
        # Rest should be normal
        for i in range(5, 20):
            assert results[i].is_anomaly == False

    def test_detect_with_anomalies(self):
        """Test detection with clear anomalies."""
        detector = MADDetector(threshold=3.0, window_size=10, min_samples=5)

        # Generate data with anomaly
        values = [10.0] * 10 + [10.0, 10.0, 10.0, 50.0, 10.0]  # 50.0 is anomaly
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(15)]
            ),
            "value": np.array(values),
            "seasonality_data": np.array(["{}"] * 15),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert len(results) == 15
        # Point at index 13 (value=50.0) should be anomaly
        assert results[13].is_anomaly == True
        assert results[13].detection_metadata["direction"] == "above"

    def test_detect_with_nan(self):
        """Test detection with NaN values."""
        detector = MADDetector(threshold=3.0, window_size=10, min_samples=5)

        # Generate data with NaN
        values = [10.0] * 10 + [np.nan, 10.0, 10.0]
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(13)]
            ),
            "value": np.array(values),
            "seasonality_data": np.array(["{}"] * 13),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert len(results) == 13
        # NaN should not be anomaly
        assert results[10].is_anomaly == False
        assert results[10].detection_metadata["reason"] == "missing_data"

    def test_detect_below_threshold(self):
        """Test detection of values below threshold."""
        detector = MADDetector(threshold=3.0, window_size=10, min_samples=5)

        # Generate data with low anomaly
        values = [10.0] * 10 + [10.0, 10.0, 10.0, 0.0, 10.0]  # 0.0 is anomaly
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(15)]
            ),
            "value": np.array(values),
            "seasonality_data": np.array(["{}"] * 15),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Point at index 13 (value=0.0) should be anomaly
        assert results[13].is_anomaly == True
        assert results[13].detection_metadata["direction"] == "below"

    def test_detect_confidence_intervals(self):
        """Test that confidence intervals are computed correctly."""
        detector = MADDetector(threshold=3.0, window_size=10, min_samples=5)

        # Generate simple data
        values = [10.0] * 10 + [10.0]
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(11)]
            ),
            "value": np.array(values),
            "seasonality_data": np.array(["{}"] * 11),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Check last result (has full window)
        result = results[-1]
        assert result.confidence_lower is not None
        assert result.confidence_upper is not None
        # For identical values, interval should be very tight
        assert abs(result.confidence_upper - result.confidence_lower) < 1e-8

    def test_detect_window_size_limit(self):
        """Test that window size is respected."""
        detector = MADDetector(threshold=3.0, window_size=5, min_samples=3)

        # Generate data where early points would look different with larger window
        values = [1.0, 1.0, 1.0, 1.0, 1.0] + [10.0] * 5 + [10.0]
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(11)]
            ),
            "value": np.array(values),
            "seasonality_data": np.array(["{}"] * 11),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Last result should only consider last 5 points (all 10.0)
        # So 10.0 should not be anomaly
        assert results[-1].is_anomaly == False

    def test_detect_metadata(self):
        """Test that detection metadata is populated."""
        detector = MADDetector(threshold=3.0, window_size=10, min_samples=5)

        values = [10.0] * 10 + [10.0]
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(11)]
            ),
            "value": np.array(values),
            "seasonality_data": np.array(["{}"] * 11),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Check metadata structure (after seasonality implementation)
        result = results[-1]
        assert "global_median" in result.detection_metadata
        assert "global_mad" in result.detection_metadata
        assert "adjusted_median" in result.detection_metadata
        assert "adjusted_mad" in result.detection_metadata
        assert "window_size" in result.detection_metadata

    def test_detect_severity(self):
        """Test that severity is calculated for anomalies."""
        detector = MADDetector(threshold=3.0, window_size=10, min_samples=5)

        # Generate data with clear anomaly
        values = [10.0] * 10 + [10.0, 10.0, 10.0, 100.0, 10.0]
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(15)]
            ),
            "value": np.array(values),
            "seasonality_data": np.array(["{}"] * 15),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Anomalous point should have severity
        anomaly_result = results[13]
        assert anomaly_result.is_anomaly == True
        assert "severity" in anomaly_result.detection_metadata
        assert anomaly_result.detection_metadata["severity"] > 0


class TestMADDetectorHashAndParams:
    """Test detector ID and parameter handling."""

    def test_get_detector_id_same_params(self):
        """Test that same params produce same ID."""
        detector1 = MADDetector(threshold=2.5)
        detector2 = MADDetector(threshold=2.5)

        assert detector1.get_detector_id() == detector2.get_detector_id()

    def test_get_detector_id_different_params(self):
        """Test that different params produce different ID."""
        detector1 = MADDetector(threshold=2.5)
        detector2 = MADDetector(threshold=3.0)

        assert detector1.get_detector_id() != detector2.get_detector_id()

    def test_get_detector_id_defaults(self):
        """Test that default params don't affect ID."""
        detector1 = MADDetector()
        detector2 = MADDetector(threshold=3.0, window_size=100, min_samples=30)

        # Both have all defaults, should be same
        assert detector1.get_detector_id() == detector2.get_detector_id()

    def test_get_detector_params(self):
        """Test parameter extraction."""
        detector = MADDetector(threshold=2.5)
        params_json = detector.get_detector_params()

        # Only non-default param
        import json
        params = json.loads(params_json)
        assert params["threshold"] == 2.5
        assert "window_size" not in params  # default
        assert "min_samples" not in params  # default

    def test_repr(self):
        """Test string representation."""
        detector = MADDetector(threshold=2.5, window_size=50)
        repr_str = repr(detector)

        assert "MADDetector" in repr_str
        assert "threshold=2.5" in repr_str
        assert "window_size=50" in repr_str
