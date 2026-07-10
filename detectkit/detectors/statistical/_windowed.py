"""Shared template for windowed statistical detectors (MAD, Z-Score, IQR).

The three detectors share the same detection pipeline and differ only in
which statistics they compute and how a confidence interval is built from
them. This module owns the whole per-point loop:

1. Preprocessing (smoothing + input_type transformation) — from BaseDetector.
2. Trailing window slice (current point excluded) with NaN filtering.
3. Optional recency weighting (time-aware: weights depend on a point's age
   on the time grid, so data gaps do not compress the decay and seasonality
   groups share the same recency horizon as global statistics).
4. Optional robust linear detrending (split-median slope), so metrics with
   a gradual trend don't drift out of their own confidence interval.
5. Global statistics + per-seasonality-group multipliers (TECHNICAL_SPEC §8).
6. Confidence interval, anomaly flag, direction/severity metadata.

Subclasses define:
    - THRESHOLD_DEFAULT, MIN_SAMPLES_FLOOR, MIN_SAMPLES_PER_GROUP_DEFAULT,
      MIN_SAMPLES_PER_GROUP_FLOOR class attributes;
    - STATS: ordered (name, kind) pairs, kind in {"center", "spread"} —
      kind controls the zero-division guard for seasonality multipliers;
    - _compute_stats(values, weights) -> dict of named statistics;
    - _build_interval(stats, threshold) -> (lower, upper);
    - _severity(current, stats, distance) -> float.
"""

from __future__ import annotations

import logging
import math
from abc import abstractmethod
from typing import Any

import numpy as np

from detectkit.core.interval import Interval
from detectkit.detectors.base import BaseDetector, DetectionResult
from detectkit.detectors.seasonality import (
    create_seasonality_mask,
    parse_seasonality_data,
)
from detectkit.utils.stats import effective_sample_size, weighted_median

logger = logging.getLogger(__name__)

_INPUT_TYPES = {"values", "changes", "absolute_changes", "log_changes"}
_CHANGE_INPUT_TYPES = {"changes", "absolute_changes", "log_changes"}
_SMOOTHING_METHODS = {None, "ema", "sma"}
_WEIGHT_METHODS = {None, "exponential", "linear"}
_DETREND_METHODS = {None, "linear"}
_STABILIZATION_METHODS = {None, "clamp"}


class WindowedStatDetector(BaseDetector):
    """Base class for detectors that compare each point against statistics
    of a trailing window, with optional recency weighting, detrending and
    seasonality-group adjustments.

    Common parameters (all subclasses):
        threshold (float): Interval width in spread units
            (default: class-specific THRESHOLD_DEFAULT)
        window_size (int): Trailing window size in points (default: 100)
        min_samples (int): Minimum valid points in window required to
            run detection (default: 30; class-specific floor)
        seasonality_components (list, optional): Seasonality groupings,
            e.g. ["hour_of_day"], [["hour_of_day", "day_of_week"]]
        min_samples_per_group (int): Minimum samples per seasonality group;
            groups below this fall back to global statistics
        input_type (str): "values" (default), "changes",
            "absolute_changes" or "log_changes"
        smoothing (str | None): None (default), "ema" or "sma"
        smoothing_alpha (float): EMA factor, 0 < alpha <= 1 (default 0.3)
        smoothing_window (int): SMA window in points (default 10)
        window_weights (str | None): None = uniform (default),
            "exponential" = recency decay with half_life,
            "linear" = weight decreases linearly with age
        half_life (int | str | None): For exponential weights: the age at
            which a point's weight halves. Integer = points, string =
            duration ("1d", "12h", parsed against the data grid step).
            Default None = max(window_size / 20, min_samples / 2) points —
            the window/20 adaptation horizon, floored so the effective
            (weighted) sample size never drops below the raw min_samples gate.
        weight_decay (float | None): Deprecated alias for half_life:
            per-point multiplier in (0, 1); decay d is equivalent to
            half_life = ln(0.5)/ln(d) points. Mutually exclusive with
            half_life.
        detrend (str | None): None (default) or "linear" — estimate a
            robust linear trend over the window (split-median slope) and
            compute statistics on values projected to the current point.
            Recommended for metrics with a gradual trend so the slow
            drift itself is not flagged as anomalous.
        stabilization (str | None): None (default) or "clamp" — when a
            point is flagged anomalous, subsequent trailing windows see
            the confidence bound it violated (winsorized value) instead
            of the observed value. Keeps a long incident from poisoning
            the baseline (inflating spread / dragging the center toward
            the incident), so the detector keeps flagging it instead of
            adapting to it. Clamping to the bound (not the center) is
            deliberate: substituting the band center feeds zero-deviation
            points back into the spread statistics, which collapses the
            band and cascades into false flags after a long incident.
            The scored/persisted values are unchanged — only the
            statistics windows read the substituted history.

    All parameters that change detection output participate in the
    detector ID hash (only non-default values are hashed).
    """

    THRESHOLD_DEFAULT: float
    MIN_SAMPLES_FLOOR: int = 1
    MIN_SAMPLES_PER_GROUP_DEFAULT: int = 10
    MIN_SAMPLES_PER_GROUP_FLOOR: int = 1
    # Ordered statistic spec: (name, kind); kind "center" guards the
    # seasonality multiplier with != 0, "spread" with > 0.
    STATS: tuple[tuple[str, str], ...]

    # v2: σ-equivalent MAD scaling, Hazen-midpoint weighted percentiles,
    # unified severity convention — same params now produce different
    # bounds than v1, so the ID must change to force recomputation.
    # v3: default half_life floored at min_samples/2 (was window_size/20
    # unconditionally) — exponential weighting with an unset half_life now
    # produces different bounds, so the ID must change to recompute.
    ALGORITHM_VERSION = 3

    def __init__(
        self,
        threshold: float | None = None,
        window_size: int = 100,
        min_samples: int = 30,
        seasonality_components: list[str | list[str]] | None = None,
        min_samples_per_group: int | None = None,
        input_type: str = "values",
        smoothing: str | None = None,
        smoothing_alpha: float = 0.3,
        smoothing_window: int = 10,
        window_weights: str | None = None,
        half_life: int | str | None = None,
        weight_decay: float | None = None,
        detrend: str | None = None,
        stabilization: str | None = None,
    ):
        super().__init__(
            threshold=self.THRESHOLD_DEFAULT if threshold is None else threshold,
            window_size=window_size,
            min_samples=min_samples,
            seasonality_components=seasonality_components,
            min_samples_per_group=(
                self.MIN_SAMPLES_PER_GROUP_DEFAULT
                if min_samples_per_group is None
                else min_samples_per_group
            ),
            input_type=input_type,
            smoothing=smoothing,
            smoothing_alpha=smoothing_alpha,
            smoothing_window=smoothing_window,
            window_weights=window_weights,
            half_life=half_life,
            weight_decay=weight_decay,
            detrend=detrend,
            stabilization=stabilization,
        )
        # Whether the one-time "seasonality groups can't fill this window" check
        # has run for this instance (so the warning fires at most once per run,
        # not once per detect() batch).
        self._underfill_checked: bool = False

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def _compute_stats(self, values: np.ndarray, weights: np.ndarray) -> dict[str, float]:
        """Compute the named statistics declared in STATS."""

    @abstractmethod
    def _build_interval(self, stats: dict[str, float], threshold: float) -> tuple[float, float]:
        """Build the (lower, upper) confidence interval from statistics."""

    @abstractmethod
    def _severity(self, current: float, stats: dict[str, float], distance: float) -> float:
        """Severity of an anomalous point (in detector-specific units)."""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_params(self):
        """Validate all parameters eagerly so misconfiguration fails at
        detector construction, not mid-detection."""
        p = self.params

        threshold = p.get("threshold")
        if threshold is None or threshold <= 0:
            raise ValueError("threshold must be positive")

        window_size = p.get("window_size")
        if window_size is None or window_size < 1:
            raise ValueError("window_size must be at least 1")

        min_samples = p.get("min_samples")
        if min_samples is None or min_samples < self.MIN_SAMPLES_FLOOR:
            raise ValueError(f"min_samples must be at least {self.MIN_SAMPLES_FLOOR}")
        if min_samples > window_size:
            raise ValueError("min_samples cannot exceed window_size")

        mspg = p.get("min_samples_per_group", self.MIN_SAMPLES_PER_GROUP_DEFAULT)
        if mspg < self.MIN_SAMPLES_PER_GROUP_FLOOR:
            raise ValueError(
                f"min_samples_per_group must be at least {self.MIN_SAMPLES_PER_GROUP_FLOOR}"
            )

        input_type = p.get("input_type", "values")
        if input_type not in _INPUT_TYPES:
            raise ValueError(
                f"Unknown input_type: {input_type}. "
                f"Supported values: {', '.join(sorted(_INPUT_TYPES))}"
            )

        smoothing = p.get("smoothing")
        if smoothing not in _SMOOTHING_METHODS:
            raise ValueError(f"Unknown smoothing method: {smoothing}. Supported: ema, sma")
        alpha = p.get("smoothing_alpha", 0.3)
        if not (0 < alpha <= 1):
            raise ValueError(f"smoothing_alpha must be in (0, 1], got {alpha}")
        if p.get("smoothing_window", 10) < 1:
            raise ValueError("smoothing_window must be at least 1")

        window_weights = p.get("window_weights")
        if window_weights not in _WEIGHT_METHODS:
            raise ValueError(
                f"Unknown window_weights method: {window_weights}. "
                f"Supported methods: exponential, linear"
            )

        half_life = p.get("half_life")
        weight_decay = p.get("weight_decay")
        if half_life is not None and weight_decay is not None:
            raise ValueError("half_life and weight_decay are mutually exclusive; set only one")
        if weight_decay is not None and not (0 < weight_decay < 1):
            raise ValueError(f"weight_decay must be in (0, 1), got {weight_decay}")
        if half_life is not None:
            if isinstance(half_life, bool) or not isinstance(half_life, (int, str)):
                raise ValueError("half_life must be an int (points) or a duration string")
            if isinstance(half_life, int) and half_life < 1:
                raise ValueError(f"half_life must be at least 1 point, got {half_life}")
            if isinstance(half_life, str):
                Interval(half_life)  # raises ValueError on bad format

        detrend = p.get("detrend")
        if detrend not in _DETREND_METHODS:
            raise ValueError(f"Unknown detrend method: {detrend}. Supported: linear")

        stabilization = p.get("stabilization")
        if stabilization not in _STABILIZATION_METHODS:
            raise ValueError(f"Unknown stabilization method: {stabilization}. Supported: clamp")

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def _defaults(self) -> dict[str, Any]:
        return {
            "threshold": self.THRESHOLD_DEFAULT,
            "window_size": 100,
            "min_samples": 30,
            "seasonality_components": None,
            "min_samples_per_group": self.MIN_SAMPLES_PER_GROUP_DEFAULT,
            "input_type": "values",
            "smoothing": None,
            "smoothing_alpha": 0.3,
            "smoothing_window": 10,
            "window_weights": None,
            "half_life": None,
            "weight_decay": None,
            "detrend": None,
            "stabilization": None,
        }

    def _get_non_default_params(self) -> dict[str, Any]:
        """Every parameter that changes detection output is hashed.

        Unlike earlier versions, weighting/smoothing/seasonality parameters
        are NOT excluded: changing them changes detection results, so they
        must produce a new detector_id (otherwise old and new detection
        regimes silently mix under one ID in ``_dtk_detections``).
        """
        defaults = self._defaults()
        return {k: v for k, v in self.params.items() if v != defaults.get(k)}

    # ------------------------------------------------------------------
    # Context / weights
    # ------------------------------------------------------------------

    def get_context_size(self) -> int:
        """Historical points needed before the first detected point.

        window_size for the statistics window, plus the smoothing warm-up
        (so the oldest window point is itself properly smoothed), plus one
        point when input_type computes changes.
        """
        context = int(self.params.get("window_size", 0) or 0)

        smoothing = self.params.get("smoothing")
        if smoothing == "sma":
            context += int(self.params.get("smoothing_window", 10))
        elif smoothing == "ema":
            # EMA influence horizon: weight of a point ~alpha*(1-alpha)^k
            # is negligible after ~5/alpha points.
            context += math.ceil(5.0 / float(self.params.get("smoothing_alpha", 0.3)))

        if self.params.get("input_type", "values") in _CHANGE_INPUT_TYPES:
            context += 1

        if self.params.get("stabilization"):
            # A point's substituted-history state depends on whether its own
            # window points were flagged, which depends on THEIR windows. One
            # extra window of warm-up lets every context point be scored on a
            # full window, so incremental batches reproduce the same
            # substitution history as a continuous run (residual differences
            # decay geometrically past that).
            context += int(self.params.get("window_size", 0) or 0)

        return context

    def _resolve_half_life_points(self, timestamps: np.ndarray) -> float:
        """Resolve the half_life parameter to a number of grid points."""
        window_size = self.params["window_size"]
        half_life = self.params.get("half_life")
        weight_decay = self.params.get("weight_decay")

        if half_life is None and weight_decay is not None:
            # decay d per point  <=>  half-life ln(0.5)/ln(d) points
            return math.log(0.5) / math.log(weight_decay)
        if half_life is None:
            # /20 preserves the adaptation horizon the large-window trending
            # recipe is tuned for (window 8640 -> 432 pts ≈ "3d"); the
            # min_samples/2 floor keeps the effective (Kish) sample size at
            # parity with the raw min_samples gate (exponential-window ESS
            # ≈ 2.9·half_life), so small/default windows aren't more
            # trigger-happy than the legacy weight_decay=0.95 default this
            # replaced (window 100: 5 pts/ESS≈14 -> 15 pts/ESS≈42).
            return max(window_size / 20.0, self.params["min_samples"] / 2.0, 1.0)
        if isinstance(half_life, int):
            return float(half_life)

        # Duration string: convert via the observed grid step.
        if len(timestamps) < 2:
            raise ValueError(
                "half_life as a duration string requires at least 2 timestamps "
                "to determine the data grid step; pass an int (points) instead"
            )
        diffs = np.diff(timestamps.astype("datetime64[ms]").astype(np.int64))
        step_seconds = float(np.median(diffs)) / 1000.0
        if step_seconds <= 0:
            raise ValueError("Cannot determine data grid step from timestamps")
        return max(Interval(half_life).seconds / step_seconds, 1.0)

    def _build_weight_lut(self, timestamps: np.ndarray) -> np.ndarray | None:
        """Precompute weight-by-age lookup table (index = age - 1).

        Age is measured in grid positions relative to the evaluated point
        (1 = immediately preceding point). Weights are looked up by actual
        age, so NaN gaps do not compress the decay and seasonality-group
        statistics share the recency horizon of global statistics.
        Returns None for uniform weighting.
        """
        method = self.params.get("window_weights")
        if method is None:
            return None

        window_size = self.params["window_size"]
        ages = np.arange(1, window_size + 1, dtype=float)

        if method == "exponential":
            if isinstance(self.params.get("half_life"), str) and len(timestamps) < 2:
                # The grid step can't be inferred from <2 timestamps, and
                # no point in such a batch can pass min_samples anyway —
                # fall back to uniform instead of failing the run.
                return None
            half_life_points = self._resolve_half_life_points(timestamps)
            # Cap the exponent so weights never underflow to exact 0.0:
            # an all-zero weight vector (tiny half_life + a long NaN gap)
            # would otherwise crash the statistics instead of degrading.
            exponents = np.minimum(ages / half_life_points, 1000.0)
            return np.power(0.5, exponents)

        # linear: newest age 1 gets weight window_size, oldest gets 1
        return (window_size + 1 - ages) / window_size

    @staticmethod
    def _weights_for(ages: np.ndarray, weight_lut: np.ndarray | None) -> np.ndarray:
        if weight_lut is None:
            return np.ones(len(ages))
        return weight_lut[ages.astype(np.int64) - 1]

    # ------------------------------------------------------------------
    # Detrending
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_slope(values: np.ndarray, ages: np.ndarray, weights: np.ndarray) -> float:
        """Robust per-point slope via split-median: the window is split at
        its median age and the slope is taken between the weighted medians
        of the two halves. Robust to outliers, O(n)."""
        if len(values) < 4:
            return 0.0

        mid = (ages.max() + ages.min()) / 2.0
        old_mask = ages > mid
        new_mask = ~old_mask
        if old_mask.sum() < 2 or new_mask.sum() < 2:
            return 0.0

        med_new = weighted_median(values[new_mask], weights[new_mask])
        med_old = weighted_median(values[old_mask], weights[old_mask])
        age_new = weighted_median(ages[new_mask].astype(float), weights[new_mask])
        age_old = weighted_median(ages[old_mask].astype(float), weights[old_mask])

        if age_old == age_new:
            return 0.0
        # values ~ c - slope * age  =>  projecting to the current point
        # (age 0) is values + slope * age
        return (med_new - med_old) / (age_old - age_new)

    def _warn_if_groups_cannot_fill(
        self,
        seasonality_components: list[str | list[str]],
        seasonality_dict: dict[str, np.ndarray],
        window_size: int,
        min_samples_per_group: int,
    ) -> None:
        """Warn once if the window is too small to ever fill a seasonality group.

        Per-group statistics only engage when the trailing window holds at least
        ``min_samples_per_group`` points sharing the current point's seasonal key.
        Same-key points recur every *cardinality* positions on the grid, so the
        window must hold roughly ``min_samples_per_group * cardinality`` points
        before any group fills — otherwise EVERY point silently falls back to the
        global (un-conditioned) band and the configured seasonality has no effect.
        This is easy to hit by accident (e.g. the default ``window_size=100`` with
        24-key hourly seasonality needs ``>= 240``), so surface it loudly once.
        """
        if self._underfill_checked:
            return
        self._underfill_checked = True

        for group in seasonality_components:
            cols = [group] if isinstance(group, str) else list(group)
            present = [c for c in cols if c in seasonality_dict]
            if not present:
                continue
            # Distinct seasonal keys actually present in the data (conjunction of
            # the group's columns) — the per-key recurrence period on the grid.
            keys = set(zip(*[seasonality_dict[c].tolist() for c in present], strict=False))
            cardinality = len(keys)
            if cardinality <= 0:
                continue
            needed = min_samples_per_group * cardinality
            if window_size < needed:
                logger.warning(
                    "%s: seasonality group %s has %d distinct key(s) but window_size=%d "
                    "holds only ~%d same-key point(s) (< min_samples_per_group=%d), so this "
                    "group falls back to global statistics and the seasonality has no effect. "
                    "Increase window_size to >= %d (min_samples_per_group * distinct keys), "
                    "lower min_samples_per_group, or use a coarser grouping.",
                    self.__class__.__name__,
                    cols,
                    cardinality,
                    window_size,
                    window_size // cardinality,
                    min_samples_per_group,
                    needed,
                )

    # ------------------------------------------------------------------
    # Detection pipeline
    # ------------------------------------------------------------------

    def detect(self, data: dict[str, np.ndarray]) -> list[DetectionResult]:
        """Run windowed detection with weighting, detrending and
        seasonality support. See class docstring for the algorithm."""
        timestamps = data["timestamp"]
        values = data["value"]  # ORIGINAL values (always kept)
        seasonality_data = data.get("seasonality_data", np.array([]))
        seasonality_columns = data.get("seasonality_columns", [])

        threshold = self.params["threshold"]
        window_size = self.params["window_size"]
        min_samples = self.params["min_samples"]
        seasonality_components = self.params.get("seasonality_components")
        min_samples_per_group = self.params.get(
            "min_samples_per_group", self.MIN_SAMPLES_PER_GROUP_DEFAULT
        )
        detrend = self.params.get("detrend")
        stabilization = self.params.get("stabilization")
        weighted = self.params.get("window_weights") is not None

        # STEP 0: Preprocessing (smoothing first, then input_type)
        smoothed_values = self._apply_smoothing(values)
        processed_values = self._preprocess_input(smoothed_values)

        # Stabilization (opt-in): statistics windows read from a working copy
        # where every previously-flagged point is clamped to the confidence
        # bound it violated, so an ongoing incident cannot inflate the spread
        # or drag the center toward itself. The scored value and the persisted
        # processed_value stay the raw observations; genuinely missing (NaN)
        # points are never substituted.
        work_values = processed_values.copy() if stabilization else processed_values
        replaced = np.zeros(len(processed_values), dtype=bool) if stabilization else None

        seasonality_dict = {}
        if seasonality_components and len(seasonality_data) > 0 and seasonality_columns:
            seasonality_dict = parse_seasonality_data(seasonality_data, seasonality_columns)
            self._warn_if_groups_cannot_fill(
                seasonality_components, seasonality_dict, window_size, min_samples_per_group
            )

        weight_lut = self._build_weight_lut(timestamps)

        results: list[DetectionResult] = []
        n_points = len(timestamps)

        for i in range(n_points):
            current_val = values[i]
            current_processed = processed_values[i]
            current_ts = timestamps[i]

            if np.isnan(current_processed):
                results.append(
                    DetectionResult(
                        timestamp=current_ts,
                        value=current_val,
                        processed_value=current_processed,
                        is_anomaly=False,
                        detection_metadata={"reason": "missing_data"},
                    )
                )
                continue

            # Trailing window, current point excluded. Both the global slice
            # and the seasonality-group slices below read window_processed, so
            # sourcing it from work_values covers every statistics consumer.
            window_start = max(0, i - window_size)
            window_processed = work_values[window_start:i]
            valid_mask = ~np.isnan(window_processed)
            window_valid = window_processed[valid_mask]

            if len(window_valid) < min_samples:
                results.append(
                    DetectionResult(
                        timestamp=current_ts,
                        value=current_val,
                        processed_value=current_processed,
                        is_anomaly=False,
                        detection_metadata={
                            "reason": "insufficient_data",
                            "window_size": int(len(window_valid)),
                            "min_samples": min_samples,
                        },
                    )
                )
                continue

            # Ages on the time grid: 1 = previous point, i - window_start = oldest
            ages = np.arange(i - window_start, 0, -1, dtype=np.int64)
            valid_ages = ages[valid_mask]
            weights = self._weights_for(valid_ages, weight_lut)

            # Detrend: project every window point to the current point
            # along a robust linear trend, so a gradual drift does not
            # pull the interval away from the current level.
            slope = 0.0
            if detrend == "linear":
                slope = self._estimate_slope(window_valid, valid_ages, weights)
            window_for_stats = window_valid + slope * valid_ages if slope != 0.0 else window_valid

            # STEP 1: Global statistics over the window
            global_stats = self._compute_stats(window_for_stats, weights)
            adjusted_stats = dict(global_stats)

            # STEP 2: Seasonality multipliers
            multipliers_applied = []
            if seasonality_components and seasonality_dict:
                for group in seasonality_components:
                    group_cols = [group] if isinstance(group, str) else group
                    season_mask = create_seasonality_mask(
                        seasonality_dict, window_start, i, group_cols
                    )
                    combined_mask = valid_mask & season_mask
                    group_values = window_processed[combined_mask]

                    if len(group_values) < min_samples_per_group:
                        entry = {
                            "group": group_cols,
                            "reason": "insufficient_group_data",
                            "group_size": int(len(group_values)),
                        }
                        for name, _ in self.STATS:
                            entry[f"{name}_multiplier"] = 1.0
                        multipliers_applied.append(entry)
                        continue

                    group_ages = ages[combined_mask]
                    group_weights = self._weights_for(group_ages, weight_lut)
                    if slope != 0.0:
                        group_values = group_values + slope * group_ages
                    group_stats = self._compute_stats(group_values, group_weights)

                    entry = {"group": group_cols, "group_size": int(len(group_values))}
                    for name, kind in self.STATS:
                        global_val = global_stats[name]
                        ok = global_val > 0 if kind == "spread" else global_val != 0
                        multiplier = group_stats[name] / global_val if ok else 1.0
                        adjusted_stats[name] *= multiplier
                        entry[f"{name}_multiplier"] = float(multiplier)
                    multipliers_applied.append(entry)

            # STEP 3: Confidence interval
            confidence_lower, confidence_upper = self._build_interval(adjusted_stats, threshold)
            if confidence_lower > confidence_upper:
                # Seasonality multipliers are applied per-statistic and can
                # invert a degenerate band; normalize deterministically.
                confidence_lower, confidence_upper = confidence_upper, confidence_lower

            # STEP 4: Anomaly check on the PROCESSED value
            is_anomaly = (current_processed < confidence_lower) or (
                current_processed > confidence_upper
            )

            # Stabilization write-back: later windows see this point clamped
            # to the bound it violated, not the anomalous observation.
            if stabilization == "clamp" and is_anomaly:
                work_values[i] = (
                    confidence_lower if current_processed < confidence_lower else confidence_upper
                )
                replaced[i] = True  # type: ignore[index]

            # STEP 5: Metadata
            metadata: dict[str, Any] = {}
            for name, _ in self.STATS:
                metadata[f"global_{name}"] = float(global_stats[name])
            for name, _ in self.STATS:
                metadata[f"adjusted_{name}"] = float(adjusted_stats[name])
            metadata["window_size"] = int(len(window_valid))

            if weighted:
                metadata["ess"] = round(effective_sample_size(weights), 1)
            if detrend == "linear":
                metadata["trend_slope_per_point"] = float(slope)
            if replaced is not None:
                n_replaced = int(np.count_nonzero(replaced[window_start:i]))
                if n_replaced:
                    metadata["stabilized_in_window"] = n_replaced

            if self.params.get("smoothing") or self.params.get("input_type") != "values":
                metadata["preprocessing"] = {
                    "input_type": self.params.get("input_type", "values"),
                    "smoothing": self.params.get("smoothing"),
                }
                if self.params.get("smoothing"):
                    metadata["preprocessing"]["smoothed_value"] = float(smoothed_values[i])

            if seasonality_components and multipliers_applied:
                metadata["seasonality_groups"] = multipliers_applied

            if is_anomaly:
                if current_processed < confidence_lower:
                    direction = "below"
                    distance = confidence_lower - current_processed
                else:
                    direction = "above"
                    distance = current_processed - confidence_upper
                metadata.update(
                    {
                        "direction": direction,
                        "severity": float(
                            self._severity(current_processed, adjusted_stats, distance)
                        ),
                        "distance": float(distance),
                    }
                )

            results.append(
                DetectionResult(
                    timestamp=current_ts,
                    value=current_val,
                    processed_value=current_processed,
                    is_anomaly=is_anomaly,
                    confidence_lower=float(confidence_lower),
                    confidence_upper=float(confidence_upper),
                    detection_metadata=metadata,
                )
            )

        return results
