"""The autotune orchestrator: runs the stages and assembles the result.

Pure and DB-free — operates entirely on the in-memory ``data`` dict. The CLI
command handles loading, persistence, config emission and candidate cleanup.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from detectkit.autotune._base import AutoTuneError, _AutoTuneBase
from detectkit.autotune._types import CandidateEval, TuneMode
from detectkit.autotune.axis_spec import max_context_size
from detectkit.autotune.crossval import build_cv_plan, predictions_from_results
from detectkit.autotune.detector_select import select_detector_types
from detectkit.autotune.grid_search import grid_search
from detectkit.autotune.labels import GroundTruth
from detectkit.autotune.result import AutoTuneResult
from detectkit.autotune.scoring import arrays_for_metric, score_predictions
from detectkit.autotune.seasonality_search import search_seasonality
from detectkit.autotune.settings import TuneSettings
from detectkit.autotune.window_select import window_grid
from detectkit.detectors.factory import DetectorFactory

_ALERT_WINDOW_GRID = (1, 2, 3, 4, 5)

# The windowed detectors emit a one-time "seasonality group can't fill this
# window → falls back to global" warning per *instance*. A tune builds dozens of
# throwaway candidate detectors, so that warning would flood the terminal and
# bury the structured decision log. The engine already surfaces an under-fill of
# the *chosen* seasonality as a `window` advisory in its own log, so the raw
# per-candidate warnings are pure noise here.
_WINDOWED_LOGGER = "detectkit.detectors.statistical._windowed"


@contextlib.contextmanager
def _quiet_per_candidate_warnings() -> Iterator[None]:
    """Silence the windowed detectors' per-instance under-fill warning for a tune.

    Scoped + restored, so a real ``dtk run`` (which builds one detector and *does*
    want the warning) is unaffected — only the candidate sweep inside the engine
    is quieted.
    """
    logger = logging.getLogger(_WINDOWED_LOGGER)
    prev_level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(prev_level)


def _ts_to_dt(ts64: np.datetime64) -> datetime:
    ms = int(ts64.astype("datetime64[ms]").astype(np.int64))
    return datetime(1970, 1, 1) + timedelta(milliseconds=ms)


def _consecutive(flags: np.ndarray, k: int) -> np.ndarray:
    """Mark index i where the last *k* grid points are all anomalous."""
    if k <= 1:
        return flags.copy()
    out = flags.copy()
    for shift in range(1, k):
        shifted = np.concatenate([np.zeros(shift, dtype=bool), flags[:-shift]])
        out &= shifted
    return out


def _fraction_fire(flags: np.ndarray, window_points: int, share: float) -> np.ndarray:
    """Mark index i where the fraction alert rule fires — the pure-numpy sibling
    of ``_decision._share_fire``: the latest point itself is anomalous (a stale
    window never fires) AND the anomalous share over the trailing
    ``window_points`` slots (current point inclusive) reaches *share*. Slots
    before the series start, gaps and invalid points all count in the
    denominator only, exactly like the pipeline's missing-slot handling."""
    n = len(flags)
    if n == 0 or window_points <= 0:
        return flags.copy()
    counts = np.convolve(flags.astype(np.int64), np.ones(window_points, dtype=np.int64))[:n]
    return flags & (counts >= share * window_points)


@dataclass(frozen=True)
class _AlertRuleChoice:
    """Outcome of the supervised alert-rule sweep.

    ``window_points``/``min_anomaly_share`` are set only when the OR-ed
    fraction rule strictly beat the consecutive-only optimum; the deployed
    behavior (consecutive OR fraction) is exactly what was scored."""

    consecutive_anomalies: int | None
    window_points: int | None = None
    min_anomaly_share: float | None = None


class AutoTuner(_AutoTuneBase):
    """Runs the load-free tuning pipeline and returns an :class:`AutoTuneResult`."""

    def tune(self) -> AutoTuneResult:
        timestamps = self.data["timestamp"]
        n = int(len(timestamps))
        if n == 0:
            raise AutoTuneError(
                "no datapoints to tune on — run `dtk run --select <metric> --steps load` first"
            )

        grid = window_grid(self)
        # Reserve the largest context any candidate the search can build might
        # need (window + stabilization warm-up + AR lags), not just the raw
        # window size — otherwise folds silently score points where detect()
        # returns insufficient_data / missing_lags (valid=False), degrading
        # the CV signal without erroring.
        max_context = max_context_size(self, grid)
        self.cv_plan = build_cv_plan(n, max_context, self.settings.fold_count)
        if not self.cv_plan.fold_bounds:
            raise AutoTuneError(
                f"not enough datapoints ({n}) for {self.settings.fold_count}-fold "
                f"cross-validation with a {max_context}-point context window"
            )

        gt = self.ground_truth
        objective = (
            f"scoring={self.settings.metric.value}"
            if gt.mode == TuneMode.SUPERVISED
            else "objective=unsupervised (band-fit + flag-budget)"
        )
        self.log(
            "labels",
            f"{gt.n_intervals} interval(s) + {gt.n_points} point(s) → {gt.mode.value} mode "
            f"({gt.n_positive} labeled grid point(s)); {objective}",
            mode=gt.mode.value,
            n_positive=gt.n_positive,
        )

        seasonality = search_seasonality(self)
        detector_types = select_detector_types(self, seasonality)
        best = grid_search(self, detector_types, seasonality, grid)
        if best is None:
            raise AutoTuneError("no viable detector candidate found for this data")

        alert_rule = self._select_alert_window(best.detector_type, best.params)

        return self._build_result(seasonality, best, alert_rule)

    # ------------------------------------------------------------------

    def _select_alert_window(
        self, detector_type: str, params: dict[str, Any]
    ) -> _AlertRuleChoice | None:
        """Sweep the alert rule on labeled incidents (supervised only).

        Two passes over one ``detect()`` run: the legacy 1-D
        ``consecutive_anomalies`` sweep first, then a 2-D (window × share)
        sweep of the fraction rule **OR-ed with the chosen consecutive rule**
        — scoring exactly the composite the pipeline would deploy. The pair is
        adopted only on a strictly greater score, so the legacy rule wins ties
        and existing behavior is byte-stable when the fraction rule doesn't
        help.
        """
        if self.ground_truth.mode != TuneMode.SUPERVISED:
            return None
        detector = DetectorFactory.create(detector_type, params)
        y_pred, y_score, valid = predictions_from_results(detector.detect(self.data))
        y_true = self.ground_truth.y_true
        metric, beta = self.settings.metric, self.settings.beta

        def _score(alert: np.ndarray) -> float:
            # Same invalid-point handling seam as the CV folds (pointwise
            # metrics mask; the segment-aware one keeps unmasked arrays).
            yt, yp, ys = arrays_for_metric(y_true, alert, y_score, valid, metric)
            return score_predictions(yt, yp, ys, metric, beta)

        best_k = 1
        best_score = float("-inf")
        for k in _ALERT_WINDOW_GRID:
            score = _score(_consecutive(y_pred, k))
            if score > best_score:
                best_score, best_k = score, k

        consecutive_fire = _consecutive(y_pred, best_k)
        n = len(y_pred)
        best_pair: tuple[int, float] | None = None
        for window_points in self.settings.alert_window_points_grid:
            # < 2 would degenerate to consecutive_anomalies=1 (MetricConfig
            # rejects it); a window longer than the series can never be
            # observed at its own width.
            if window_points < 2 or window_points > n:
                continue
            for share in self.settings.alert_share_grid:
                alert = consecutive_fire | _fraction_fire(y_pred, window_points, share)
                score = _score(alert)
                if score > best_score:
                    best_score, best_pair = score, (window_points, share)

        if best_pair is not None:
            window_points, share = best_pair
            self.log(
                "window",
                f"consecutive_anomalies={best_k} OR anomaly_window={window_points}p × "
                f"min_anomaly_share={share} "
                f"(max {metric.value}={best_score:.3f} on labeled incidents)",
                consecutive_anomalies=best_k,
                anomaly_window_points=window_points,
                min_anomaly_share=share,
            )
            return _AlertRuleChoice(best_k, window_points, share)

        self.log(
            "window",
            f"consecutive_anomalies={best_k} "
            f"(max {metric.value}={best_score:.3f} on labeled incidents)",
            consecutive_anomalies=best_k,
        )
        return _AlertRuleChoice(best_k)

    def _clean_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Drop None/empty values so the emitted config is tidy."""
        out: dict[str, Any] = {}
        for key, value in params.items():
            if value is None:
                continue
            if key == "seasonality_components" and not value:
                continue
            out[key] = value
        return out

    def _build_result(
        self, seasonality: list | None, best: CandidateEval, alert_rule: _AlertRuleChoice | None
    ) -> AutoTuneResult:
        timestamps = self.data["timestamp"]
        training_start = _ts_to_dt(timestamps[0]) if len(timestamps) else None
        training_end = _ts_to_dt(timestamps[-1]) if len(timestamps) else None
        gt = self.ground_truth

        candidates = [
            {
                "detector_type": ev.detector_type,
                "params": self._clean_params(ev.params),
                "detector_id": ev.detector_id,
            }
            for ev in self._evaluated.values()
        ]
        group_votes = [
            {"group": gv.group, "features": gv.features, "ranked_types": gv.ranked_types}
            for gv in self.group_votes
        ]

        return AutoTuneResult(
            metric_name=self.metric_name,
            mode=gt.mode.value,
            scoring_metric=self.settings.metric.value,
            training_start=training_start,
            training_end=training_end,
            interval_seconds=self.interval_seconds,
            n_points=int(len(timestamps)),
            labels_summary={
                "intervals": gt.n_intervals,
                "points": gt.n_points,
                "positive_grid_points": gt.n_positive,
            },
            chosen_seasonality=seasonality,
            chosen_detector_type=best.detector_type,
            chosen_detector_params=self._clean_params(best.params),
            winning_detector_id=best.detector_id,
            score=best.score,
            cv_per_fold=best.fold_scores.per_fold,
            cv_stability_penalty=best.fold_scores.stability_penalty,
            consecutive_anomalies=alert_rule.consecutive_anomalies if alert_rule else None,
            anomaly_window=(
                f"{alert_rule.window_points * self.interval_seconds}s"
                if alert_rule and alert_rule.window_points is not None
                else None
            ),
            min_anomaly_share=alert_rule.min_anomaly_share if alert_rule else None,
            candidate_detector_ids=self.evaluated_ids(),
            candidates=candidates,
            group_votes=group_votes,
            decision_log=[entry.to_dict() for entry in self.decision_log],
        )


def run_autotune_engine(
    *,
    metric_name: str,
    data: dict[str, np.ndarray],
    ground_truth: GroundTruth,
    interval_seconds: int,
    settings: TuneSettings,
    on_stage: Callable[[str, str], None] | None = None,
) -> AutoTuneResult:
    """Build an :class:`AutoTuner` and run it (the command↔engine entry point)."""
    tuner = AutoTuner(
        metric_name=metric_name,
        data=data,
        ground_truth=ground_truth,
        interval_seconds=interval_seconds,
        settings=settings,
        on_stage=on_stage,
    )
    with _quiet_per_candidate_warnings():
        return tuner.tune()
