"""Tests for weighted statistics helpers (detectkit.utils.stats)."""

import numpy as np
import pytest

from detectkit.utils.stats import (
    effective_sample_size,
    weighted_mad,
    weighted_mean,
    weighted_median,
    weighted_percentile,
    weighted_std,
)


class TestWeightedPercentile:
    def test_uniform_median_matches_numpy_odd(self):
        data = np.array([3.0, 1.0, 2.0, 5.0, 4.0])
        weights = np.ones(5)
        assert weighted_median(data, weights) == np.median(data)

    def test_uniform_median_matches_numpy_even(self):
        data = np.array([1.0, 2.0, 3.0, 4.0])
        weights = np.ones(4)
        # Midpoint convention averages the two central values, like np.median
        assert weighted_median(data, weights) == np.median(data)

    def test_uniform_median_matches_numpy_random(self):
        rng = np.random.default_rng(7)
        for n in (5, 10, 31, 100):
            data = rng.normal(0, 1, n)
            assert weighted_median(data, np.ones(n)) == pytest.approx(np.median(data))

    def test_weights_do_not_need_normalization(self):
        data = np.array([1.0, 2.0, 3.0])
        assert weighted_median(data, np.array([10.0, 10.0, 10.0])) == 2.0

    def test_heavy_weight_dominates(self):
        data = np.array([1.0, 2.0, 100.0])
        weights = np.array([0.01, 0.01, 0.98])
        # Midpoint convention interpolates near the dominant value
        assert weighted_median(data, weights) > 95.0

    def test_percentile_bounds(self):
        data = np.array([1.0, 2.0, 3.0])
        weights = np.ones(3)
        assert weighted_percentile(data, weights, 0) == 1.0
        assert weighted_percentile(data, weights, 100) == 3.0

    def test_invalid_percentile_raises(self):
        with pytest.raises(ValueError):
            weighted_percentile(np.array([1.0]), np.array([1.0]), 101)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            weighted_percentile(np.array([1.0, 2.0]), np.array([1.0]), 50)

    def test_zero_weights_raise(self):
        with pytest.raises(ValueError):
            weighted_median(np.array([1.0, 2.0]), np.array([0.0, 0.0]))


class TestWeightedMad:
    def test_symmetric_data(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        weights = np.ones(5)
        assert weighted_mad(data, weights) == 1.0

    def test_uniform_matches_classic_mad(self):
        rng = np.random.default_rng(11)
        data = rng.normal(10, 2, 101)
        weights = np.ones(101)
        classic = np.median(np.abs(data - np.median(data)))
        assert weighted_mad(data, weights) == pytest.approx(classic)


class TestWeightedMeanStd:
    def test_uniform_matches_numpy(self):
        rng = np.random.default_rng(3)
        data = rng.normal(5, 3, 50)
        weights = np.ones(50)
        assert weighted_mean(data, weights) == pytest.approx(np.mean(data))
        assert weighted_std(data, weights, ddof=1) == pytest.approx(np.std(data, ddof=1))
        assert weighted_std(data, weights, ddof=0) == pytest.approx(np.std(data))

    def test_degenerate_ess_falls_back_to_population(self):
        # One point dominates: correction 1 - sum(w^2) ~ 0 must not blow up
        data = np.array([1.0, 2.0])
        weights = np.array([1e9, 1e-9])
        result = weighted_std(data, weights, ddof=1)
        assert np.isfinite(result)


class TestEffectiveSampleSize:
    def test_uniform(self):
        assert effective_sample_size(np.ones(42)) == pytest.approx(42.0)

    def test_single_dominant_weight(self):
        ess = effective_sample_size(np.array([1.0, 1e-9, 1e-9]))
        assert ess == pytest.approx(1.0, abs=1e-6)

    def test_exponential_half_life(self):
        # ESS of 0.5^(age/H) over a long window ≈ 2H/ln2 ≈ 2.885·H
        ages = np.arange(1, 10001)
        weights = np.power(0.5, ages / 100.0)
        assert effective_sample_size(weights) == pytest.approx(2.885 * 100, rel=0.01)
