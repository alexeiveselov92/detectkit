"""Detector evaluation runner: score one or many detectors over a set of
:class:`~benchmarks.datasets.LabeledSeries` and aggregate the results.

Reuses detectkit's own prediction-alignment helper
(``detectkit.autotune.crossval.predictions_from_results``) so the harness
scores the *same* ``(y_pred, y_score, valid)`` triple the library's own
cross-validation does — the only detectkit import in the whole harness aside
from the ``DetectorFactory`` registry lookup.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from benchmarks.datasets import LabeledSeries
from benchmarks.score import event_f1_best, event_f_beta, f1, f1_best, pr_auc
from benchmarks.spectral_residual import spectral_residual_scores
from detectkit.autotune.crossval import predictions_from_results
from detectkit.detectors.factory import DetectorFactory

logger = logging.getLogger(__name__)

SPECTRAL_RESIDUAL = "spectral_residual"

# (label, detector_type, params). `detector_type` is either a
# DetectorFactory-registered type name, or the literal SPECTRAL_RESIDUAL for
# the benchmark-local implementation. `autoreg` is included so the sweep
# picks it up automatically once it lands in DetectorFactory (see
# available_detector_matrix, which skips unknown types gracefully).
DEFAULT_DETECTOR_MATRIX: list[tuple[str, str, dict[str, Any]]] = [
    ("mad", "mad", {}),
    ("zscore", "zscore", {}),
    ("iqr", "iqr", {}),
    ("mad (clamp)", "mad", {"stabilization": "clamp"}),
    ("zscore (clamp)", "zscore", {"stabilization": "clamp"}),
    ("iqr (clamp)", "iqr", {"stabilization": "clamp"}),
    ("autoreg", "autoreg", {}),
    (SPECTRAL_RESIDUAL, SPECTRAL_RESIDUAL, {"threshold": 3.0}),
]


@dataclass
class SeriesResult:
    """Per-(series, detector) scoring outcome."""

    series_name: str
    dataset: str
    detector_label: str
    n_points: int
    n_scored: int
    event_f1: float
    f1: float
    f1_best: float
    event_f1_best: float
    pr_auc: float
    seconds: float
    error: str | None = None


@dataclass
class DetectorAggregate:
    """Mean metrics for one detector over every series in one dataset."""

    detector_label: str
    dataset: str
    n_series: int
    mean_event_f1_best: float
    mean_f1_best: float
    mean_pr_auc: float
    mean_native_event_f1: float
    mean_native_f1: float
    total_seconds: float


def _build_detector_data(series: LabeledSeries) -> dict[str, Any]:
    """The loader-contract dict a detectkit detector's ``detect()`` expects
    (see ``detectkit/detectors/base.py`` and ``_windowed.py``): timestamp +
    value arrays plus (possibly empty) seasonality columns. No seasonality is
    configured here, so every row carries the empty-object sentinel ``"{}"``
    that ``detectkit.detectors.seasonality.parse_seasonality_data`` treats as
    "no seasonality features for this point".
    """
    n = len(series.timestamps)
    return {
        "timestamp": series.timestamps,
        "value": series.values,
        "seasonality_data": np.array(["{}"] * n, dtype=object),
        "seasonality_columns": [],
    }


def run_detector(
    series: LabeledSeries, detector_type: str, params: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Run one detector over one series.

    Returns ``(y_pred, y_score, valid, context_size)``. ``valid`` excludes
    both points the detector could not score (missing data / an
    insufficiently-filled window — no confidence band) AND the detector's
    ``get_context_size()`` lead-in, since those points were never evaluated
    against a fully-formed baseline (for detectkit detectors this mostly
    overlaps with the insufficient-data exclusion already built into
    ``predictions_from_results``; it is enforced explicitly here so the rule
    holds regardless of a detector's internal ``min_samples`` floor).
    """
    if detector_type == SPECTRAL_RESIDUAL:
        threshold = float(params.get("threshold", 3.0))
        scores = spectral_residual_scores(series.values)
        y_pred = scores > threshold
        valid = np.isfinite(series.values)
        return y_pred, scores, valid, 0

    detector = DetectorFactory.create(detector_type, params)
    data = _build_detector_data(series)
    results = detector.detect(data)
    y_pred, y_score, valid = predictions_from_results(results)

    context = detector.get_context_size()
    if context > 0:
        valid = valid.copy()
        valid[: min(context, len(valid))] = False
    return y_pred, y_score, valid, context


def evaluate_one(
    series: LabeledSeries, detector_label: str, detector_type: str, params: dict[str, Any]
) -> SeriesResult:
    """Score one (series, detector) pair. Never raises: a failing series is
    captured on the returned result's ``error`` field so one bad series can't
    kill the whole sweep.
    """
    started = time.perf_counter()
    try:
        y_pred, y_score, valid, _context = run_detector(series, detector_type, params)
        n_scored = int(np.count_nonzero(valid))
        if n_scored == 0:
            raise ValueError("no scoreable points (all missing or inside detector context)")

        y_true = series.y_true[valid]
        yp = y_pred[valid]
        ys = y_score[valid]

        return SeriesResult(
            series_name=series.name,
            dataset=series.dataset,
            detector_label=detector_label,
            n_points=len(series.values),
            n_scored=n_scored,
            event_f1=event_f_beta(y_true, yp, beta=1.0),
            f1=f1(y_true, yp),
            f1_best=f1_best(y_true, ys),
            event_f1_best=event_f1_best(y_true, ys),
            pr_auc=pr_auc(y_true, ys),
            seconds=time.perf_counter() - started,
        )
    except Exception as exc:  # noqa: BLE001 - a failing series must not kill the sweep
        logger.warning("detector=%s series=%s failed: %s", detector_label, series.name, exc)
        return SeriesResult(
            series_name=series.name,
            dataset=series.dataset,
            detector_label=detector_label,
            n_points=len(series.values),
            n_scored=0,
            event_f1=0.0,
            f1=0.0,
            f1_best=0.0,
            event_f1_best=0.0,
            pr_auc=0.0,
            seconds=time.perf_counter() - started,
            error=str(exc),
        )


def available_detector_matrix(
    matrix: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Filter a requested detector matrix down to types this detectkit
    checkout actually knows about — e.g. skips ``autoreg`` gracefully with a
    warning if it hasn't been merged into ``DetectorFactory`` yet.
    """
    matrix = DEFAULT_DETECTOR_MATRIX if matrix is None else matrix
    known = set(DetectorFactory.DETECTOR_TYPES.keys()) | {SPECTRAL_RESIDUAL}

    resolved = []
    for label, detector_type, params in matrix:
        if detector_type not in known:
            logger.warning(
                "Skipping detector '%s': type '%s' is not registered in this "
                "detectkit checkout's DetectorFactory (available: %s).",
                label,
                detector_type,
                ", ".join(sorted(known)),
            )
            continue
        resolved.append((label, detector_type, params))
    return resolved


def run_sweep(
    series_list: list[LabeledSeries],
    matrix: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> list[SeriesResult]:
    """Run every (series, detector) pair in ``matrix`` (default: the full
    :data:`DEFAULT_DETECTOR_MATRIX`, minus any type unknown to this checkout).
    """
    resolved_matrix = available_detector_matrix(matrix)
    results: list[SeriesResult] = []
    for label, detector_type, params in resolved_matrix:
        for series in series_list:
            results.append(evaluate_one(series, label, detector_type, params))
    return results


def aggregate(results: list[SeriesResult]) -> list[DetectorAggregate]:
    """Mean of each metric per (dataset, detector) over all its series."""
    groups: dict[tuple[str, str], list[SeriesResult]] = {}
    for r in results:
        groups.setdefault((r.dataset, r.detector_label), []).append(r)

    aggregates = [
        DetectorAggregate(
            detector_label=label,
            dataset=dataset,
            n_series=len(rows),
            mean_event_f1_best=float(np.mean([r.event_f1_best for r in rows])),
            mean_f1_best=float(np.mean([r.f1_best for r in rows])),
            mean_pr_auc=float(np.mean([r.pr_auc for r in rows])),
            mean_native_event_f1=float(np.mean([r.event_f1 for r in rows])),
            mean_native_f1=float(np.mean([r.f1 for r in rows])),
            total_seconds=float(np.sum([r.seconds for r in rows])),
        )
        for (dataset, label), rows in groups.items()
    ]
    aggregates.sort(key=lambda a: (a.dataset, a.detector_label))
    return aggregates
