"""Tests for the autoregressive (AR) detector.

Covers prediction correctness on a deterministic AR(2) series, dynamics-based
anomaly detection (a value within the normal range that breaks the metric's
usual dynamics), strict NaN handling, stabilization (clamp), batch-boundary
determinism, detector-id hashing, eager validation, and factory/config
wiring.
"""

import numpy as np
import pytest

from detectkit.config.metric_config import DetectorConfig
from detectkit.detectors.factory import DetectorFactory
from detectkit.detectors.statistical.autoreg import AutoregDetector


def make_data(values, start="2026-01-01", step_minutes=10):
    values = np.asarray(values, dtype=float)
    n = len(values)
    timestamps = np.datetime64(start) + np.arange(n) * np.timedelta64(step_minutes, "m")
    return {
        "timestamp": timestamps,
        "value": values,
        "seasonality_data": np.array([], dtype=object),
        "seasonality_columns": [],
    }


def ar2_series(n=300, y0=5.0, y1=-3.0, a=0.6, b=-0.3, c=5.0, noise=0.0, seed=None):
    """Deterministic AR(2) recurrence ``y_t = a*y_{t-1} + b*y_{t-2} + c``,
    optionally perturbed with small Gaussian noise. Damped-oscillatory by
    default (complex roots), so the series is non-trivial before it settles
    near its fixed point."""
    y = np.zeros(n)
    y[0], y[1] = y0, y1
    for t in range(2, n):
        y[t] = a * y[t - 1] + b * y[t - 2] + c
    if noise:
        rng = np.random.default_rng(seed)
        y = y + rng.normal(0, noise, n)
    return y


class TestPredictionCorrectness:
    """A deterministic (noise-free) AR(2) series must be predicted almost
    exactly once enough history has accumulated to fit the model."""

    def test_deterministic_ar2_predicted_near_exactly(self):
        n = 300
        values = ar2_series(n=n)
        data = make_data(values)
        det = AutoregDetector(
            lags=2, window_size=50, min_samples=10, threshold=3.0, stabilization=None
        )
        results = det.detect(data)

        for r in results[200:]:
            assert r.detection_metadata.get("reason") is None
            pred = r.detection_metadata["prediction"]
            sigma = r.detection_metadata["sigma_r"]
            assert abs(r.value - pred) < 1e-6
            assert sigma < 1e-6
            # The band must contain the point (small tolerance for the
            # degenerate near-zero-sigma band).
            assert r.confidence_lower - 1e-6 <= r.value <= r.confidence_upper + 1e-6
            assert not r.is_anomaly


class TestDynamicsAnomaly:
    """A value within the metric's historical range can still break its
    short-range dynamics; the AR detector must catch that, while a value
    that the dynamics *do* predict must not be flagged."""

    def test_dynamics_break_flagged_value_predicted_not_flagged(self):
        n = 300
        base = ar2_series(n=n, noise=0.05, seed=1)
        data = make_data(base)
        det = AutoregDetector(
            lags=2, window_size=60, min_samples=15, threshold=3.0, stabilization=None
        )

        clean_results = det.detect(data)
        idx = 250
        clean_point = clean_results[idx]
        # The naturally-generated point (noise only) must not be flagged.
        assert not clean_point.is_anomaly
        sigma0 = clean_point.detection_metadata["sigma_r"]
        pred0 = clean_point.detection_metadata["prediction"]
        assert sigma0 > 0

        # Break dynamics: jump far beyond what the AR model predicts, but
        # stay near the series' historical value range (well within [-10, 20]).
        injected = base.copy()
        injected[idx] = pred0 + 8 * sigma0
        injected_data = make_data(injected)
        injected_results = AutoregDetector(
            lags=2, window_size=60, min_samples=15, threshold=3.0, stabilization=None
        ).detect(injected_data)

        assert injected_results[idx].is_anomaly
        assert injected_results[idx].detection_metadata["direction"] in ("above", "below")
        assert injected_results[idx].detection_metadata["distance"] > 0


class TestNanHandling:
    def test_missing_data_and_missing_lags_reasons(self):
        n = 150
        lags = 3
        rng = np.random.default_rng(4)
        values = rng.normal(10, 1, n)
        gap_index = 60
        values[gap_index] = np.nan
        data = make_data(values)

        det = AutoregDetector(lags=lags, window_size=40, min_samples=10, stabilization=None)
        results = det.detect(data)

        assert results[gap_index].detection_metadata.get("reason") == "missing_data"
        assert not results[gap_index].is_anomaly
        assert results[gap_index].confidence_lower is None
        assert results[gap_index].confidence_upper is None

        for j in range(gap_index + 1, gap_index + 1 + lags):
            assert results[j].detection_metadata.get("reason") == "missing_lags"
            assert not results[j].is_anomaly
            assert results[j].confidence_lower is None

        # Well past the gap, detection resumes normally (no reason key).
        assert results[gap_index + lags + 10].detection_metadata.get("reason") is None

    def test_fit_survives_scattered_nans(self):
        n = 200
        rng = np.random.default_rng(5)
        values = rng.normal(20, 1, n)
        # Scatter a handful of NaNs — not dense enough to break min_samples.
        for k in (50, 70, 90, 110):
            values[k] = np.nan
        data = make_data(values)

        det = AutoregDetector(lags=2, window_size=60, min_samples=15, stabilization=None)
        results = det.detect(data)

        r = results[150]
        assert r.detection_metadata.get("reason") is None
        assert r.detection_metadata["fit_points"] >= 15
        # Some rows were dropped by the scattered NaNs.
        assert r.detection_metadata["fit_points"] < 60 - 2

    def test_insufficient_data_when_valid_rows_below_min_samples(self):
        n = 100
        lags = 2
        window_size = 40
        min_samples = 10
        values = np.arange(n, dtype=float)
        # Heavy gap: only the tail (90:100) stays finite, starving the fit
        # window of valid rows for points shortly after the gap.
        values[10:90] = np.nan
        data = make_data(values)

        det = AutoregDetector(
            lags=lags, window_size=window_size, min_samples=min_samples, stabilization=None
        )
        results = det.detect(data)

        idx = 93
        assert results[idx].detection_metadata.get("reason") == "insufficient_data"
        assert not results[idx].is_anomaly
        assert results[idx].confidence_lower is None


class TestStabilization:
    """Opt-in clamp: a sustained level shift must stay flagged at least as
    much with stabilization on as with it off."""

    @staticmethod
    def _incident_series(n=150, level=50.0, sigma=1.0, start=100, length=20, shift=15.0, seed=11):
        rng = np.random.default_rng(seed)
        vals = level + rng.normal(0, sigma, n)
        vals[start : start + length] += shift
        return vals

    def test_sustained_shift_flagged_at_least_as_much_with_clamp(self):
        vals = self._incident_series()
        data = make_data(vals)
        start, length = 100, 20

        clamp = AutoregDetector(
            lags=1, window_size=30, min_samples=10, threshold=3.0, stabilization="clamp"
        )
        none = AutoregDetector(
            lags=1, window_size=30, min_samples=10, threshold=3.0, stabilization=None
        )
        r_clamp = clamp.detect(data)
        r_none = none.detect(data)

        flagged_clamp = sum(r.is_anomaly for r in r_clamp[start : start + length])
        flagged_none = sum(r.is_anomaly for r in r_none[start : start + length])
        assert flagged_clamp >= flagged_none

    def test_stabilized_in_window_reported(self):
        vals = self._incident_series()
        data = make_data(vals)
        start, length = 100, 20

        det = AutoregDetector(
            lags=1, window_size=30, min_samples=10, threshold=3.0, stabilization="clamp"
        )
        results = det.detect(data)
        counts = [
            r.detection_metadata.get("stabilized_in_window", 0)
            for r in results[start : start + length + 15]
        ]
        assert max(counts) > 0

        base = AutoregDetector(
            lags=1, window_size=30, min_samples=10, threshold=3.0, stabilization=None
        ).detect(data)
        assert all("stabilized_in_window" not in r.detection_metadata for r in base)


class TestBatchDeterminism:
    def test_split_run_matches_continuous_run(self):
        rng = np.random.default_rng(21)
        n = 400
        values = rng.normal(20, 2, n)
        values[300:320] += 10  # sustained incident
        data = make_data(values)

        det = AutoregDetector(lags=2, window_size=50, min_samples=10, stabilization="clamp")
        full = det.detect(data)

        context = det.get_context_size()
        batch_start = 250
        assert batch_start - context >= 0
        sliced = {
            "timestamp": data["timestamp"][batch_start - context :],
            "value": data["value"][batch_start - context :],
            "seasonality_data": data["seasonality_data"],
            "seasonality_columns": data["seasonality_columns"],
        }
        det2 = AutoregDetector(lags=2, window_size=50, min_samples=10, stabilization="clamp")
        partial = det2.detect(sliced)
        persisted = partial[context:]
        expected = full[batch_start:]

        assert [r.is_anomaly for r in persisted] == [r.is_anomaly for r in expected]


class TestDetectorId:
    def test_default_params_produce_stable_id(self):
        assert AutoregDetector().get_detector_id() == AutoregDetector().get_detector_id()
        assert AutoregDetector()._get_non_default_params() == {}

    def test_changing_lags_or_threshold_changes_id(self):
        base = AutoregDetector()
        variants = [
            AutoregDetector(lags=8),
            AutoregDetector(threshold=2.0),
            AutoregDetector(window_size=500),
            AutoregDetector(min_samples=50),
            AutoregDetector(input_type="changes"),
            AutoregDetector(stabilization=None),
        ]
        ids = {d.get_detector_id() for d in variants}
        assert base.get_detector_id() not in ids
        assert len(ids) == len(variants)

    def test_get_detector_params_excludes_seasonality_components(self):
        det = AutoregDetector(lags=8, seasonality_components=None)
        params_json = det.get_detector_params()
        assert "seasonality_components" not in params_json
        assert "lags" in params_json

    def test_algorithm_version_changes_id(self, monkeypatch):
        # the version tag feeds the identity hash, so an algorithm change (e.g.
        # the v2 numerical hardening) forces recomputation for the same params
        base = AutoregDetector().get_detector_id()
        monkeypatch.setattr(AutoregDetector, "ALGORITHM_VERSION", 99)
        assert AutoregDetector().get_detector_id() != base


class TestValidation:
    def test_lags_below_one_fails(self):
        with pytest.raises(ValueError, match="lags"):
            AutoregDetector(lags=0)

    def test_lags_not_less_than_window_size_fails(self):
        with pytest.raises(ValueError, match="window_size"):
            AutoregDetector(lags=10, window_size=10)

    def test_window_size_below_lags_plus_two_fails(self):
        with pytest.raises(ValueError, match="window_size"):
            AutoregDetector(lags=5, window_size=6)

    def test_min_samples_below_floor_fails(self):
        with pytest.raises(ValueError, match="min_samples"):
            AutoregDetector(lags=5, window_size=200, min_samples=6)

    def test_min_samples_above_window_size_fails(self):
        with pytest.raises(ValueError, match="min_samples"):
            AutoregDetector(lags=2, window_size=20, min_samples=21)

    def test_threshold_not_positive_fails(self):
        with pytest.raises(ValueError, match="threshold"):
            AutoregDetector(threshold=0)

    def test_bad_input_type_fails(self):
        with pytest.raises(ValueError, match="input_type"):
            AutoregDetector(input_type="diff")

    def test_bad_stabilization_fails(self):
        with pytest.raises(ValueError, match="stabilization"):
            AutoregDetector(stabilization="center")

    def test_seasonality_components_rejected(self):
        with pytest.raises(ValueError, match="seasonality_components"):
            AutoregDetector(seasonality_components=["hour"])


class TestFactoryAndConfig:
    def test_factory_creates_autoreg(self):
        det = DetectorFactory.create("autoreg", {"lags": 4, "window_size": 60})
        assert isinstance(det, AutoregDetector)
        assert det.params["lags"] == 4

    def test_factory_lists_autoreg(self):
        assert "autoreg" in DetectorFactory.list_available_types()

    def test_metric_config_accepts_autoreg(self):
        config = DetectorConfig(type="autoreg", params={"lags": 4, "window_size": 60})
        assert config.type == "autoreg"


class TestContextSize:
    def test_default(self):
        det = AutoregDetector(lags=5, window_size=200, stabilization=None)
        # window_size + lags, no stabilization, no change-based input.
        assert det.get_context_size() == 205

    def test_change_based_input_adds_one(self):
        det = AutoregDetector(lags=5, window_size=200, input_type="changes", stabilization=None)
        assert det.get_context_size() == 206

    def test_stabilization_adds_a_window(self):
        det = AutoregDetector(lags=5, window_size=200, stabilization="clamp")
        assert det.get_context_size() == 205 + 200


class TestNumericalStability:
    """Phase-0 hardening (issue #97): the fit window is centered/scaled before
    the normal equations, and the clamp substitution is capped to the observed
    window range — measured on NAB, where raw ~1e9-scale series overflowed
    ``x.T @ x`` to inf and clamp-amplified the garbage into later fits."""

    def test_large_magnitude_series_stays_finite(self):
        rng = np.random.default_rng(7)
        n = 400
        values = 2.5e9 + rng.normal(0, 5e6, n)
        values[300:340] += 8e7  # sustained shift: triggers anomalies + clamp write-back
        data = make_data(values)
        det = AutoregDetector(lags=5, window_size=100, min_samples=20, stabilization="clamp")

        results = det.detect(data)

        scored = [r for r in results if r.detection_metadata.get("reason") is None]
        assert scored, "expected scored points on a gap-free series"
        for r in scored:
            assert np.isfinite(r.confidence_lower)
            assert np.isfinite(r.confidence_upper)
            assert np.isfinite(r.detection_metadata["prediction"])
            assert np.isfinite(r.detection_metadata["sigma_r"])
        # The shift must actually be caught (the run isn't degenerate).
        assert any(r.is_anomaly for r in results[300:340])

    def test_flags_invariant_under_affine_rescaling(self):
        """Centering/scaling makes detection affine-equivariant in practice:
        the same series shifted/scaled to ~1e9 magnitude must flag the same
        points as its unit-scale original."""
        rng = np.random.default_rng(11)
        n = 400
        base = ar2_series(n=n, noise=0.5, seed=3)
        base[350] += 25.0  # dynamics break
        big = 1e9 + 5e7 * base

        det_kwargs = dict(lags=3, window_size=80, min_samples=15, stabilization="clamp")
        flags_base = [r.is_anomaly for r in AutoregDetector(**det_kwargs).detect(make_data(base))]
        flags_big = [r.is_anomaly for r in AutoregDetector(**det_kwargs).detect(make_data(big))]

        assert flags_base == flags_big
        assert flags_base[350]

    def test_clamp_substitution_capped_to_window_range(self):
        """Even when the band blows far past anything observed, the value the
        working history ingests stays within the raw window range: later
        predictions can never exceed max(|window|) by orders of magnitude."""
        rng = np.random.default_rng(23)
        n = 300
        values = 100.0 + rng.normal(0, 1.0, n)
        values[200:] = 1e6  # extreme sustained incident
        data = make_data(values)
        det = AutoregDetector(lags=4, window_size=60, min_samples=15, stabilization="clamp")

        results = det.detect(data)

        for r in results:
            if r.confidence_lower is not None:
                assert np.isfinite(r.confidence_lower)
                assert np.isfinite(r.confidence_upper)
            pred = r.detection_metadata.get("prediction")
            if pred is not None:
                # Working history is capped to observed values, so predictions
                # stay within the same order of magnitude as the data.
                assert abs(pred) < 1e8
