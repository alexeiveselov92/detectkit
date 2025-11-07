"""Tests for Manual Bounds detector."""

import numpy as np
import pytest

from detectkit.detectors.statistical.manual_bounds import ManualBoundsDetector


class TestManualBoundsDetectorInit:
    """Test Manual Bounds detector initialization and validation."""

    def test_init_upper_bound_only(self):
        """Test initialization with upper bound only."""
        detector = ManualBoundsDetector(upper_bound=100.0)

        assert detector.params["upper_bound"] == 100.0
        assert detector.params["lower_bound"] is None

    def test_init_lower_bound_only(self):
        """Test initialization with lower bound only."""
        detector = ManualBoundsDetector(lower_bound=10.0)

        assert detector.params["lower_bound"] == 10.0
        assert detector.params["upper_bound"] is None

    def test_init_both_bounds(self):
        """Test initialization with both bounds."""
        detector = ManualBoundsDetector(lower_bound=10.0, upper_bound=100.0)

        assert detector.params["lower_bound"] == 10.0
        assert detector.params["upper_bound"] == 100.0

    def test_validation_no_bounds(self):
        """Test that no bounds raises error."""
        with pytest.raises(ValueError, match="At least one of lower_bound or upper_bound"):
            ManualBoundsDetector()

    def test_validation_invalid_range(self):
        """Test that lower >= upper raises error."""
        with pytest.raises(ValueError, match="lower_bound must be less than upper_bound"):
            ManualBoundsDetector(lower_bound=100.0, upper_bound=50.0)

    def test_validation_equal_bounds(self):
        """Test that equal bounds raise error."""
        with pytest.raises(ValueError, match="lower_bound must be less than upper_bound"):
            ManualBoundsDetector(lower_bound=50.0, upper_bound=50.0)


class TestManualBoundsDetectorDetect:
    """Test Manual Bounds detector detection logic."""

    def test_detect_upper_bound_only(self):
        """Test detection with upper bound only."""
        detector = ManualBoundsDetector(upper_bound=50.0)

        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(5)]
            ),
            "value": np.array([10.0, 40.0, 50.0, 60.0, 100.0]),
            "seasonality_data": np.array(["{}"] * 5),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert len(results) == 5
        assert results[0].is_anomaly == False  # 10.0 <= 50.0
        assert results[1].is_anomaly == False  # 40.0 <= 50.0
        assert results[2].is_anomaly == False  # 50.0 <= 50.0
        assert results[3].is_anomaly == True   # 60.0 > 50.0
        assert results[4].is_anomaly == True   # 100.0 > 50.0

    def test_detect_lower_bound_only(self):
        """Test detection with lower bound only."""
        detector = ManualBoundsDetector(lower_bound=20.0)

        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(5)]
            ),
            "value": np.array([5.0, 10.0, 20.0, 30.0, 100.0]),
            "seasonality_data": np.array(["{}"] * 5),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert len(results) == 5
        assert results[0].is_anomaly == True   # 5.0 < 20.0
        assert results[1].is_anomaly == True   # 10.0 < 20.0
        assert results[2].is_anomaly == False  # 20.0 >= 20.0
        assert results[3].is_anomaly == False  # 30.0 >= 20.0
        assert results[4].is_anomaly == False  # 100.0 >= 20.0

    def test_detect_both_bounds(self):
        """Test detection with both bounds."""
        detector = ManualBoundsDetector(lower_bound=20.0, upper_bound=80.0)

        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(6)]
            ),
            "value": np.array([10.0, 20.0, 50.0, 80.0, 90.0, 100.0]),
            "seasonality_data": np.array(["{}"] * 6),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert len(results) == 6
        assert results[0].is_anomaly == True   # 10.0 < 20.0
        assert results[1].is_anomaly == False  # 20.0 in range
        assert results[2].is_anomaly == False  # 50.0 in range
        assert results[3].is_anomaly == False  # 80.0 in range
        assert results[4].is_anomaly == True   # 90.0 > 80.0
        assert results[5].is_anomaly == True   # 100.0 > 80.0

    def test_detect_with_nan(self):
        """Test detection with NaN values."""
        detector = ManualBoundsDetector(lower_bound=10.0, upper_bound=100.0)

        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(4)]
            ),
            "value": np.array([50.0, np.nan, 150.0, 5.0]),
            "seasonality_data": np.array(["{}"] * 4),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert len(results) == 4
        assert results[0].is_anomaly == False  # 50.0 in range
        assert results[1].is_anomaly == False  # NaN is not anomaly
        assert results[1].detection_metadata["reason"] == "missing_data"
        assert results[2].is_anomaly == True   # 150.0 > 100.0
        assert results[3].is_anomaly == True   # 5.0 < 10.0

    def test_detect_direction(self):
        """Test that direction is correctly identified."""
        detector = ManualBoundsDetector(lower_bound=20.0, upper_bound=80.0)

        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(3)]
            ),
            "value": np.array([10.0, 50.0, 90.0]),
            "seasonality_data": np.array(["{}"] * 3),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert results[0].detection_metadata["direction"] == "below"
        assert results[2].detection_metadata["direction"] == "above"

    def test_detect_distance(self):
        """Test that distance from bound is calculated."""
        detector = ManualBoundsDetector(lower_bound=20.0, upper_bound=80.0)

        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(2)]
            ),
            "value": np.array([10.0, 100.0]),
            "seasonality_data": np.array(["{}"] * 2),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # 10.0 is 10 below lower bound (20.0)
        assert results[0].detection_metadata["distance"] == 10.0
        # 100.0 is 20 above upper bound (80.0)
        assert results[1].detection_metadata["distance"] == 20.0

    def test_detect_severity(self):
        """Test that severity is calculated."""
        detector = ManualBoundsDetector(lower_bound=20.0, upper_bound=80.0)

        data = {
            "timestamp": np.array(
                [np.datetime64(f"2024-01-01T00:{i:02d}:00", "ms") for i in range(2)]
            ),
            "value": np.array([10.0, 100.0]),
            "seasonality_data": np.array(["{}"] * 2),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Both should have severity > 0
        assert results[0].detection_metadata["severity"] > 0
        assert results[1].detection_metadata["severity"] > 0

    def test_detect_confidence_intervals(self):
        """Test that confidence intervals match specified bounds."""
        detector = ManualBoundsDetector(lower_bound=20.0, upper_bound=80.0)

        data = {
            "timestamp": np.array(
                [np.datetime64("2024-01-01T00:00:00", "ms")]
            ),
            "value": np.array([50.0]),
            "seasonality_data": np.array(["{}"] * 1),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        assert results[0].confidence_lower == 20.0
        assert results[0].confidence_upper == 80.0

    def test_detect_no_metadata_for_normal(self):
        """Test that normal values have minimal metadata."""
        detector = ManualBoundsDetector(lower_bound=20.0, upper_bound=80.0)

        data = {
            "timestamp": np.array(
                [np.datetime64("2024-01-01T00:00:00", "ms")]
            ),
            "value": np.array([50.0]),
            "seasonality_data": np.array(["{}"] * 1),
            "seasonality_columns": [],
        }

        results = detector.detect(data)

        # Normal value should have empty metadata (no direction, distance, severity)
        assert results[0].is_anomaly == False
        assert "direction" not in results[0].detection_metadata
        assert "distance" not in results[0].detection_metadata
        assert "severity" not in results[0].detection_metadata


class TestManualBoundsDetectorHashAndParams:
    """Test detector ID and parameter handling."""

    def test_get_detector_id_same_params(self):
        """Test that same params produce same ID."""
        detector1 = ManualBoundsDetector(lower_bound=10.0, upper_bound=100.0)
        detector2 = ManualBoundsDetector(lower_bound=10.0, upper_bound=100.0)

        assert detector1.get_detector_id() == detector2.get_detector_id()

    def test_get_detector_id_different_params(self):
        """Test that different params produce different ID."""
        detector1 = ManualBoundsDetector(upper_bound=100.0)
        detector2 = ManualBoundsDetector(upper_bound=200.0)

        assert detector1.get_detector_id() != detector2.get_detector_id()

    def test_get_detector_id_different_bound_types(self):
        """Test that lower vs upper bound produces different IDs."""
        detector1 = ManualBoundsDetector(lower_bound=50.0)
        detector2 = ManualBoundsDetector(upper_bound=50.0)

        assert detector1.get_detector_id() != detector2.get_detector_id()

    def test_get_detector_params_both_bounds(self):
        """Test parameter extraction with both bounds."""
        detector = ManualBoundsDetector(lower_bound=10.0, upper_bound=100.0)
        params_json = detector.get_detector_params()

        import json
        params = json.loads(params_json)
        assert params["lower_bound"] == 10.0
        assert params["upper_bound"] == 100.0

    def test_get_detector_params_one_bound(self):
        """Test parameter extraction with one bound."""
        detector = ManualBoundsDetector(upper_bound=100.0)
        params_json = detector.get_detector_params()

        import json
        params = json.loads(params_json)
        assert params["upper_bound"] == 100.0
        assert "lower_bound" not in params  # None is excluded

    def test_repr(self):
        """Test string representation."""
        detector = ManualBoundsDetector(lower_bound=10.0, upper_bound=100.0)
        repr_str = repr(detector)

        assert "ManualBoundsDetector" in repr_str
        assert "lower_bound=10.0" in repr_str
        assert "upper_bound=100.0" in repr_str
