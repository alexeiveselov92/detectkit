"""Tests for IQR (Interquartile Range) detector."""

import numpy as np
import pytest

from detectkit.detectors.statistical.iqr import IQRDetector


class TestIQRDetectorInit:
    """Test IQR detector initialization and validation."""

    def test_init_defaults(self):
        """Test initialization with default parameters."""
        detector = IQRDetector()

        assert detector.params["threshold"] == 1.5
        assert detector.params["window_size"] == 100
        assert detector.params["min_samples"] == 30

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        detector = IQRDetector(threshold=3.0, window_size=50, min_samples=20)

        assert detector.params["threshold"] == 3.0
        assert detector.params["window_size"] == 50
        assert detector.params["min_samples"] == 20

    def test_validation_negative_threshold(self):
        """Test that negative threshold raises error."""
        with pytest.raises(ValueError, match="threshold must be positive"):
            IQRDetector(threshold=-1.0)

    def test_validation_zero_threshold(self):
        """Test that zero threshold raises error."""
        with pytest.raises(ValueError, match="threshold must be positive"):
            IQRDetector(threshold=0.0)

    def test_validation_invalid_window_size(self):
        """Test that invalid window_size raises error."""
        with pytest.raises(ValueError, match="window_size must be at least 1"):
            IQRDetector(window_size=0)

    def test_validation_invalid_min_samples(self):
        """Test that invalid min_samples raises error."""
        with pytest.raises(ValueError, match="min_samples must be at least 4"):
            IQRDetector(min_samples=3)

    def test_validation_min_samples_exceeds_window(self):
        """Test that min_samples > window_size raises error."""
        with pytest.raises(ValueError, match="min_samples cannot exceed window_size"):
            IQRDetector(window_size=50, min_samples=100)


class TestIQRDetectorDetect:
    """Test IQR detector detection logic."""

    def test_detect_no_anomalies(self):
        """Test detection with no anomalies."""
        detector = IQRDetector(threshold=1.5, window_size=10, min_samples=5)

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
        detector = IQRDetector(threshold=1.5, window_size=10, min_samples=5)

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
        detector = IQRDetector(threshold=1.5, window_size=10, min_samples=5)

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
        detector = IQRDetector(threshold=1.5, window_size=10, min_samples=5)

        # Generate data with low anomaly
        values = [10.0] * 10 + [10.0, 10.0, 10.0, -50.0, 10.0]  # -50.0 is anomaly
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(15)]
            ),
            "value": np.array(values),
            "seasonality_data": np.array(["{}"] * 15),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Point at index 13 (value=-50.0) should be anomaly
        assert results[13].is_anomaly == True
        assert results[13].detection_metadata["direction"] == "below"

    def test_detect_confidence_intervals(self):
        """Test that confidence intervals are computed correctly."""
        detector = IQRDetector(threshold=1.5, window_size=10, min_samples=5)

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
        # For identical values, IQR should be 0, so interval is tight
        assert abs(result.confidence_upper - result.confidence_lower) < 1e-8

    def test_detect_quartile_calculation(self):
        """Test that Q1, Q3, and IQR are calculated correctly."""
        detector = IQRDetector(threshold=1.5, window_size=10, min_samples=5)

        # Generate data with known quartiles
        # Window: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        # Q1 = 3.25, Q3 = 7.75, IQR = 4.5
        values = list(range(1, 11)) + [5.0]  # 5.0 is within range
        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(11)]
            ),
            "value": np.array(values, dtype=float),
            "seasonality_data": np.array(["{}"] * 11),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Check last result
        result = results[-1]
        metadata = result.detection_metadata

        # Verify Q1, Q3, IQR
        assert "q1" in metadata
        assert "q3" in metadata
        assert "iqr" in metadata

        # Q1 should be around 3.25, Q3 around 7.75
        assert 3.0 < metadata["q1"] < 4.0
        assert 7.5 < metadata["q3"] < 8.0
        assert 4.0 < metadata["iqr"] < 5.0

    def test_detect_skewed_distribution(self):
        """Test IQR with skewed distribution (where it performs well)."""
        detector = IQRDetector(threshold=1.5, window_size=20, min_samples=10)

        # Generate skewed data (exponential-like)
        values = [1.0] * 10 + [2.0] * 5 + [3.0] * 3 + [5.0, 8.0]
        # Add test point
        values = values + [50.0]  # Clear outlier

        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(len(values))]
            ),
            "value": np.array(values, dtype=float),
            "seasonality_data": np.array(["{}"] * len(values)),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Last point (50.0) should be detected as anomaly
        assert results[-1].is_anomaly == True

    def test_detect_metadata(self):
        """Test that detection metadata is populated."""
        detector = IQRDetector(threshold=1.5, window_size=10, min_samples=5)

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

        # Check metadata structure
        result = results[-1]
        assert "q1" in result.detection_metadata
        assert "q3" in result.detection_metadata
        assert "iqr" in result.detection_metadata
        assert "window_size" in result.detection_metadata

    def test_detect_severity(self):
        """Test that severity is calculated for anomalies."""
        detector = IQRDetector(threshold=1.5, window_size=10, min_samples=5)

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


class TestIQRDetectorHashAndParams:
    """Test detector ID and parameter handling."""

    def test_get_detector_id_same_params(self):
        """Test that same params produce same ID."""
        detector1 = IQRDetector(threshold=1.5)
        detector2 = IQRDetector(threshold=1.5)

        assert detector1.get_detector_id() == detector2.get_detector_id()

    def test_get_detector_id_different_params(self):
        """Test that different params produce different ID."""
        detector1 = IQRDetector(threshold=1.5)
        detector2 = IQRDetector(threshold=3.0)

        assert detector1.get_detector_id() != detector2.get_detector_id()

    def test_get_detector_id_defaults(self):
        """Test that default params don't affect ID."""
        detector1 = IQRDetector()
        detector2 = IQRDetector(threshold=1.5, window_size=100, min_samples=30)

        # Both have all defaults, should be same
        assert detector1.get_detector_id() == detector2.get_detector_id()

    def test_get_detector_id_different_from_others(self):
        """Test that IQR has different ID from MAD and ZScore."""
        from detectkit.detectors.statistical.mad import MADDetector
        from detectkit.detectors.statistical.zscore import ZScoreDetector

        iqr = IQRDetector(threshold=3.0)
        mad = MADDetector(threshold=3.0)
        zscore = ZScoreDetector(threshold=3.0)

        # Different detector classes should have different IDs
        assert iqr.get_detector_id() != mad.get_detector_id()
        assert iqr.get_detector_id() != zscore.get_detector_id()

    def test_get_detector_params(self):
        """Test parameter extraction."""
        detector = IQRDetector(threshold=3.0)
        params_json = detector.get_detector_params()

        # Only non-default param
        import json
        params = json.loads(params_json)
        assert params["threshold"] == 3.0
        assert "window_size" not in params  # default
        assert "min_samples" not in params  # default

    def test_repr(self):
        """Test string representation."""
        detector = IQRDetector(threshold=3.0, window_size=50)
        repr_str = repr(detector)

        assert "IQRDetector" in repr_str
        assert "threshold=3.0" in repr_str
        assert "window_size=50" in repr_str
