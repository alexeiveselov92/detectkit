"""Shared behavior tests for windowed detectors (MAD / Z-Score / IQR).

Covers the WindowedStatDetector machinery: recency weighting (half_life,
legacy weight_decay), robust detrending, eager validation, detector-id
hashing of result-affecting params, context size, seasonality robustness.
"""

import json

import numpy as np
import pytest

from detectkit.detectors.statistical.iqr import IQRDetector
from detectkit.detectors.statistical.mad import MADDetector
from detectkit.detectors.statistical.zscore import ZScoreDetector

ALL_DETECTORS = [MADDetector, ZScoreDetector, IQRDetector]


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


def trending_series(n=600, noise=0.01, slope_per_point=-0.001, seed=5):
    """Flat at 100, then a steady linear decline."""
    rng = np.random.default_rng(seed)
    base = np.full(n, 100.0)
    decline_start = n // 2
    drift = np.where(
        np.arange(n) > decline_start,
        (np.arange(n) - decline_start) * slope_per_point * 100.0,
        0.0,
    )
    return base + drift + rng.normal(0, noise * 100.0, n)


class TestValidation:
    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_bad_input_type_fails_at_init(self, cls):
        with pytest.raises(ValueError, match="input_type"):
            cls(input_type="diff")

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_bad_smoothing_fails_at_init(self, cls):
        with pytest.raises(ValueError, match="smoothing"):
            cls(smoothing="ma3")

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_bad_window_weights_fails_at_init(self, cls):
        with pytest.raises(ValueError, match="window_weights"):
            cls(window_weights="quadratic")

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_bad_detrend_fails_at_init(self, cls):
        with pytest.raises(ValueError, match="detrend"):
            cls(detrend="quadratic")

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_half_life_and_weight_decay_are_mutually_exclusive(self, cls):
        with pytest.raises(ValueError, match="mutually exclusive"):
            cls(window_weights="exponential", half_life=100, weight_decay=0.95)

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_bad_half_life_string_fails_at_init(self, cls):
        with pytest.raises(ValueError):
            cls(window_weights="exponential", half_life="3 parsecs")

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_min_samples_per_group_floor(self, cls):
        with pytest.raises(ValueError, match="min_samples_per_group"):
            cls(min_samples_per_group=0)


class TestDetectorId:
    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_result_affecting_params_change_id(self, cls):
        base = cls(window_size=500, min_samples=50)
        variants = [
            cls(window_size=500, min_samples=50, window_weights="exponential"),
            cls(window_size=500, min_samples=50, window_weights="exponential", half_life=100),
            cls(window_size=500, min_samples=50, window_weights="exponential", weight_decay=0.9),
            cls(window_size=500, min_samples=50, detrend="linear"),
            cls(window_size=500, min_samples=50, smoothing="sma", smoothing_window=20),
            cls(window_size=500, min_samples=50, seasonality_components=["hour_of_day"]),
        ]
        ids = {d.get_detector_id() for d in variants}
        assert base.get_detector_id() not in ids
        assert len(ids) == len(variants), "every variant must hash differently"

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_default_params_produce_stable_id(self, cls):
        assert cls().get_detector_id() == cls().get_detector_id()
        assert cls()._get_non_default_params() == {}


class TestContextSize:
    def test_window_only(self):
        assert MADDetector(window_size=100, min_samples=10).get_context_size() == 100

    def test_sma_adds_warmup(self):
        det = MADDetector(window_size=100, min_samples=10, smoothing="sma", smoothing_window=15)
        assert det.get_context_size() == 115

    def test_changes_adds_one(self):
        det = MADDetector(window_size=100, min_samples=10, input_type="changes")
        assert det.get_context_size() == 101


class TestRecencyWeighting:
    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_half_life_adapts_to_level_shift(self, cls):
        """After a permanent level shift, short half_life re-centers the
        interval while the uniform window is still anchored at the old level."""
        rng = np.random.default_rng(2)
        values = np.concatenate([rng.normal(100, 1, 400), rng.normal(70, 1, 200)])  # -30% shift
        data = make_data(values)

        uniform = cls(window_size=300, min_samples=50).detect(data)
        weighted = cls(
            window_size=300, min_samples=50, window_weights="exponential", half_life=30
        ).detect(data)

        # Soon after the shift (70 post-shift points out of a 300-point
        # window) the weighted interval has already re-centered near 70...
        idx = 470
        w_mid = (weighted[idx].confidence_lower + weighted[idx].confidence_upper) / 2
        u_mid = (uniform[idx].confidence_lower + uniform[idx].confidence_upper) / 2
        assert w_mid < 80
        # ...while the uniform center is still anchored near the old level
        assert u_mid > 85

    def test_half_life_duration_string_equivalent_to_points(self):
        values = trending_series()
        data = make_data(values, step_minutes=10)
        a = MADDetector(window_size=300, min_samples=50, window_weights="exponential", half_life=18)
        b = MADDetector(
            window_size=300, min_samples=50, window_weights="exponential", half_life="3h"
        )  # 3h / 10min = 18 points
        ra, rb = a.detect(data), b.detect(data)
        assert [r.confidence_lower for r in ra] == pytest.approx(
            [r.confidence_lower for r in rb], nan_ok=True
        )

    def test_legacy_weight_decay_maps_to_half_life(self):
        values = trending_series()
        data = make_data(values)
        # decay 0.95 per point <=> half-life ln(0.5)/ln(0.95) ≈ 13.51 points
        legacy = MADDetector(
            window_size=300, min_samples=50, window_weights="exponential", weight_decay=0.95
        )
        assert legacy._resolve_half_life_points(data["timestamp"]) == pytest.approx(
            np.log(0.5) / np.log(0.95)
        )

    def test_weights_are_age_based_not_position_based(self):
        """A NaN gap must not compress the decay: the weight of a point
        depends on how long ago it was, not on how many valid points sit
        between it and the present."""
        det = MADDetector(
            window_size=100, min_samples=5, window_weights="exponential", half_life=10
        )
        lut = det._build_weight_lut(make_data(np.zeros(100))["timestamp"])
        ages = np.array([1, 50], dtype=np.int64)
        w = det._weights_for(ages, lut)
        # age 50 vs age 1 → weight ratio 0.5^(49/10)
        assert w[1] / w[0] == pytest.approx(0.5 ** (49 / 10))

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_ess_reported_in_metadata(self, cls):
        rng = np.random.default_rng(0)
        data = make_data(rng.normal(100, 1, 200))
        results = cls(
            window_size=100, min_samples=30, window_weights="exponential", half_life=10
        ).detect(data)
        assert "ess" in results[-1].detection_metadata
        assert 0 < results[-1].detection_metadata["ess"] < 100


class TestDetrend:
    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_steady_trend_not_flagged(self, cls):
        """A clean linear decline must produce (almost) no anomalies when
        detrend is enabled, while still catching a sharp drop."""
        rng = np.random.default_rng(9)
        n = 600
        values = 100.0 + np.arange(n) * (-0.05) + rng.normal(0, 0.5, n)
        data = make_data(values)
        det = cls(window_size=200, min_samples=50, detrend="linear")
        results = det.detect(data)
        flagged = sum(1 for r in results[250:] if r.is_anomaly)
        assert flagged <= 5  # ~1% tolerance for noise tails

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_sharp_drop_still_caught_with_detrend(self, cls):
        rng = np.random.default_rng(10)
        n = 600
        values = 100.0 + np.arange(n) * (-0.05) + rng.normal(0, 0.5, n)
        values[500:506] -= 20  # sharp incident against the trend
        data = make_data(values)
        det = cls(window_size=200, min_samples=50, detrend="linear")
        results = det.detect(data)
        assert any(r.is_anomaly for r in results[500:506])

    def test_slope_estimate_recovers_true_slope(self):
        rng = np.random.default_rng(1)
        n = 400
        slope = -0.07
        values = 50.0 + np.arange(n) * slope + rng.normal(0, 0.1, n)
        det = MADDetector(window_size=300, min_samples=50, detrend="linear")
        results = det.detect(make_data(values))
        est = results[-1].detection_metadata["trend_slope_per_point"]
        assert est == pytest.approx(slope, rel=0.15)


class TestTrendSpamScenario:
    """The original production problem: a gradually declining metric must
    not spam 'below' alerts when recency weighting is enabled."""

    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_recency_weighting_kills_trend_spam(self, cls):
        rng = np.random.default_rng(21)
        n = 900
        decline = np.where(np.arange(n) > 450, (np.arange(n) - 450) * -0.02, 0.0)
        values = 100.0 + decline + rng.normal(0, 0.1, n)
        data = make_data(values)

        uniform = cls(window_size=300, min_samples=100).detect(data)
        weighted = cls(
            window_size=300, min_samples=100, window_weights="exponential", half_life=30
        ).detect(data)

        spam_uniform = sum(
            1
            for r in uniform[460:]
            if r.is_anomaly and r.detection_metadata.get("direction") == "below"
        )
        spam_weighted = sum(
            1
            for r in weighted[460:]
            if r.is_anomaly and r.detection_metadata.get("direction") == "below"
        )
        assert spam_uniform > 50, "sanity: uniform weighting must spam on this trend"
        assert spam_weighted < spam_uniform / 10


class TestMadCalibration:
    def test_threshold_is_sigma_equivalent(self):
        """threshold=3 on Gaussian noise must behave like 3σ (FPR ≪ 1%),
        not like raw 3×MAD (≈2σ → ≈4.5% FPR)."""
        rng = np.random.default_rng(33)
        data = make_data(rng.normal(100, 5, 3000))
        results = MADDetector(window_size=500, min_samples=300).detect(data)
        evaluated = [r for r in results if "reason" not in (r.detection_metadata or {})]
        fpr = sum(1 for r in evaluated if r.is_anomaly) / max(len(evaluated), 1)
        assert fpr < 0.01


class TestSeasonalityRobustness:
    @pytest.mark.parametrize("cls", ALL_DETECTORS)
    def test_numpy_unicode_seasonality_strings_are_parsed(self, cls):
        """Regression: numpy U-dtype strings used to fail orjson parsing
        silently, disabling seasonality grouping entirely."""
        rng = np.random.default_rng(4)
        n = 480
        hours = np.arange(n) % 24
        # hour 12 sits at a much higher level
        values = rng.normal(100, 1, n) + np.where(hours == 12, 50.0, 0.0)
        data = make_data(values)
        # U-dtype on purpose (no dtype=object)
        data["seasonality_data"] = np.array([json.dumps({"hour_of_day": int(h)}) for h in hours])
        data["seasonality_columns"] = ["hour_of_day"]

        det = cls(
            window_size=480,
            min_samples=48,
            seasonality_components=["hour_of_day"],
            min_samples_per_group=4,
        )
        results = det.detect(data)
        last_groups = results[-1].detection_metadata.get("seasonality_groups")
        assert last_groups, "seasonality grouping must be active"
        assert last_groups[0]["group_size"] < n / 2, (
            "the hour-of-day mask must select a subset, not the whole window "
            "(whole-window selection means parsing silently failed)"
        )


class TestEmaNanHandling:
    def test_leading_nan_does_not_poison_series(self):
        det = MADDetector(window_size=50, min_samples=5, smoothing="ema")
        values = np.array([np.nan, np.nan] + list(np.linspace(10, 12, 60)))
        smoothed = det._apply_smoothing(values)
        assert np.isnan(smoothed[0]) and np.isnan(smoothed[1])
        assert np.isfinite(smoothed[2:]).all()
