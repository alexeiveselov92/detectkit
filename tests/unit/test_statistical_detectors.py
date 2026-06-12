"""Per-detector behavior tests for MAD / Z-Score / IQR, parametrized.

Replaces the three ~90%-identical legacy files (test_mad_detector.py,
test_zscore_detector.py, test_iqr_detector.py). Shared machinery (weights,
detrend, validation of preprocessing params, hashing of result-affecting
params) is covered separately in test_windowed_detectors.py; this file pins
the basic detection contract and per-detector specifics.
"""

import json

import numpy as np
import pytest

from detectkit.detectors.statistical.iqr import IQRDetector
from detectkit.detectors.statistical.mad import MADDetector
from detectkit.detectors.statistical.zscore import ZScoreDetector

ALL = [MADDetector, ZScoreDetector, IQRDetector]

# (class, default threshold, min_samples floor, metadata stat keys)
SPECS = {
    MADDetector: {"threshold": 3.0, "floor": 1, "stats": ("median", "mad")},
    ZScoreDetector: {"threshold": 3.0, "floor": 2, "stats": ("mean", "std")},
    IQRDetector: {"threshold": 1.5, "floor": 4, "stats": ("q1", "q3", "iqr")},
}


def make_data(values):
    values = np.asarray(values, dtype=float)
    n = len(values)
    return {
        "timestamp": np.array(
            [np.datetime64("2024-01-01T00:00:00", "ms") + np.timedelta64(i, "m") for i in range(n)]
        ),
        "value": values,
        "seasonality_data": np.array(["{}"] * n),
        "seasonality_columns": [],
    }


class TestInitAndValidation:
    @pytest.mark.parametrize("cls", ALL)
    def test_init_defaults(self, cls):
        detector = cls()
        assert detector.params["threshold"] == SPECS[cls]["threshold"]
        assert detector.params["window_size"] == 100
        assert detector.params["min_samples"] == 30

    @pytest.mark.parametrize("cls", ALL)
    def test_init_custom_params(self, cls):
        detector = cls(threshold=2.5, window_size=50, min_samples=20)
        assert detector.params["threshold"] == 2.5
        assert detector.params["window_size"] == 50
        assert detector.params["min_samples"] == 20

    @pytest.mark.parametrize("cls", ALL)
    @pytest.mark.parametrize("bad_threshold", [-1.0, 0.0])
    def test_validation_non_positive_threshold(self, cls, bad_threshold):
        with pytest.raises(ValueError, match="threshold must be positive"):
            cls(threshold=bad_threshold)

    @pytest.mark.parametrize("cls", ALL)
    def test_validation_invalid_window_size(self, cls):
        with pytest.raises(ValueError, match="window_size must be at least 1"):
            cls(window_size=0)

    @pytest.mark.parametrize("cls", ALL)
    def test_validation_min_samples_floor(self, cls):
        with pytest.raises(ValueError, match="min_samples must be at least"):
            cls(min_samples=SPECS[cls]["floor"] - 1)

    @pytest.mark.parametrize("cls", ALL)
    def test_validation_min_samples_exceeds_window(self, cls):
        with pytest.raises(ValueError, match="min_samples cannot exceed window_size"):
            cls(window_size=50, min_samples=100)


class TestDetect:
    @pytest.mark.parametrize("cls", ALL)
    def test_detect_no_anomalies(self, cls):
        detector = cls(window_size=10, min_samples=5)
        results = detector.detect(make_data([10.0] * 20))

        assert len(results) == 20
        # First min_samples-1 points lack history
        for i in range(5):
            assert not results[i].is_anomaly
            assert results[i].detection_metadata["reason"] == "insufficient_data"
        for i in range(5, 20):
            assert not results[i].is_anomaly

    @pytest.mark.parametrize("cls", ALL)
    def test_detect_anomaly_above(self, cls):
        detector = cls(window_size=10, min_samples=5)
        values = [10.0] * 13 + [50.0, 10.0]
        results = detector.detect(make_data(values))

        assert len(results) == 15
        assert results[13].is_anomaly
        assert results[13].detection_metadata["direction"] == "above"

    @pytest.mark.parametrize("cls", ALL)
    def test_detect_anomaly_below(self, cls):
        detector = cls(window_size=10, min_samples=5)
        values = [10.0] * 13 + [0.0, 10.0]
        results = detector.detect(make_data(values))

        assert results[13].is_anomaly
        assert results[13].detection_metadata["direction"] == "below"

    @pytest.mark.parametrize("cls", ALL)
    def test_detect_nan_marked_missing(self, cls):
        detector = cls(window_size=10, min_samples=5)
        values = [10.0] * 10 + [np.nan, 10.0, 10.0]
        results = detector.detect(make_data(values))

        assert len(results) == 13
        assert not results[10].is_anomaly
        assert results[10].detection_metadata["reason"] == "missing_data"

    @pytest.mark.parametrize("cls", ALL)
    def test_detect_confidence_intervals_tight_for_constant_series(self, cls):
        detector = cls(window_size=10, min_samples=5)
        results = detector.detect(make_data([10.0] * 11))

        result = results[-1]
        assert result.confidence_lower is not None
        assert result.confidence_upper is not None
        assert abs(result.confidence_upper - result.confidence_lower) < 1e-8

    @pytest.mark.parametrize("cls", ALL)
    def test_detect_window_size_limit(self, cls):
        """Old regime outside the window must not influence detection."""
        detector = cls(window_size=5, min_samples=4)
        values = [1.0] * 5 + [10.0] * 5 + [10.0]
        results = detector.detect(make_data(values))
        assert not results[-1].is_anomaly

    @pytest.mark.parametrize("cls", ALL)
    def test_detect_metadata_keys(self, cls):
        detector = cls(window_size=10, min_samples=5)
        results = detector.detect(make_data([10.0] * 11))

        metadata = results[-1].detection_metadata
        for stat in SPECS[cls]["stats"]:
            assert f"global_{stat}" in metadata
            assert f"adjusted_{stat}" in metadata
        assert "window_size" in metadata

    @pytest.mark.parametrize("cls", ALL)
    def test_detect_severity_positive_for_anomaly(self, cls):
        detector = cls(window_size=10, min_samples=5)
        values = [10.0] * 13 + [100.0, 10.0]
        results = detector.detect(make_data(values))

        anomaly = results[13]
        assert anomaly.is_anomaly
        assert anomaly.detection_metadata["severity"] > 0
        assert "distance" in anomaly.detection_metadata


class TestDetectorSpecific:
    def test_zscore_normal_distribution_outliers(self):
        np.random.seed(42)
        detector = ZScoreDetector(threshold=2.5, window_size=50, min_samples=30)
        values = np.random.normal(loc=10.0, scale=2.0, size=100)
        values[60] = 30.0  # ~10 std away
        values[70] = -10.0
        results = detector.detect(make_data(values))

        assert results[60].is_anomaly
        assert results[70].is_anomaly

    def test_iqr_quartile_calculation(self):
        detector = IQRDetector(threshold=1.5, window_size=10, min_samples=5)
        # Quartiles computed on the prior window [1..10] (current excluded):
        # Q1≈2.5-3, Q3≈7.5-8 depending on interpolation convention.
        values = list(range(1, 11)) + [5.0]
        results = detector.detect(make_data(values))

        metadata = results[-1].detection_metadata
        assert 2.0 < metadata["global_q1"] < 3.5
        assert 7.0 < metadata["global_q3"] < 8.5
        assert 4.0 < metadata["global_iqr"] < 6.0

    def test_iqr_skewed_distribution(self):
        detector = IQRDetector(threshold=1.5, window_size=20, min_samples=10)
        values = [1.0] * 10 + [2.0] * 5 + [3.0] * 3 + [5.0, 8.0] + [50.0]
        results = detector.detect(make_data(values))
        assert results[-1].is_anomaly


class TestHashAndParams:
    @pytest.mark.parametrize("cls", ALL)
    def test_same_params_same_id(self, cls):
        assert cls(threshold=2.5).get_detector_id() == cls(threshold=2.5).get_detector_id()

    @pytest.mark.parametrize("cls", ALL)
    def test_different_params_different_id(self, cls):
        assert cls(threshold=2.5).get_detector_id() != cls(threshold=2.0).get_detector_id()

    @pytest.mark.parametrize("cls", ALL)
    def test_explicit_defaults_dont_affect_id(self, cls):
        explicit = cls(threshold=SPECS[cls]["threshold"], window_size=100, min_samples=30)
        assert cls().get_detector_id() == explicit.get_detector_id()

    def test_detector_classes_have_distinct_ids(self):
        ids = {cls(threshold=3.0).get_detector_id() for cls in ALL}
        assert len(ids) == 3

    @pytest.mark.parametrize("cls", ALL)
    def test_get_detector_params_only_non_default(self, cls):
        params = json.loads(cls(threshold=2.5).get_detector_params())
        assert params == {"threshold": 2.5}

    @pytest.mark.parametrize("cls", ALL)
    def test_repr(self, cls):
        repr_str = repr(cls(threshold=2.5, window_size=50))
        assert cls.__name__ in repr_str
        assert "threshold=2.5" in repr_str
        assert "window_size=50" in repr_str
