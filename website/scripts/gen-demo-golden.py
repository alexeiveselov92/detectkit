#!/usr/bin/env python3
"""gen-demo-golden.py — golden-parity vectors for the landing demo detector.

The interactive landing demo re-implements detectkit's windowed statistical
detectors (MAD / Z-Score / IQR) in TypeScript (``website/src/scripts/demo/
detector.ts``). To prove that port stays faithful, we do NOT eyeball it: this
script runs the *real* detectkit detectors over a handful of fixed, seeded
series and freezes their per-point output to ``website/src/scripts/demo/
golden.json``. ``check-demo-parity.mjs`` then bundles ``detector.ts`` and asserts
the TS ``runDetector`` reproduces every band within 1e-6.

Run it from the repo (same generated-asset pattern as ``gen-report-bundle.mjs`` /
``make-bot-icon.mjs``):

    python website/scripts/gen-demo-golden.py

The output is fully deterministic — fixed seeds (``numpy.random.RandomState``),
integer half-lives (so the JS, which takes half-life in points, matches exactly),
and sorted JSON keys — so re-running only changes the file when the detector
behavior actually changes, keeping git diffs meaningful.

Each case pins:
  - a seeded series (a few hundred points + a couple of injected outliers),
  - a detectkit param set (built straight into the matching detector via
    ``DetectorFactory``),
  - and, for the seasonal case, a per-point ``seasonality_data`` payload
    (JSON strings, exactly what the loader hands ``detect()``).

The emitted ``params`` block uses the camelCase ``DetectorParams`` shape from
``types.ts`` (detectkit's snake_case names mapped over), so the TS side can feed
it to ``runDetector`` unchanged.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from detectkit.detectors.factory import DetectorFactory
from detectkit.utils.json_utils import json_dumps_sorted

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUT = _REPO_ROOT / "website" / "src" / "scripts" / "demo" / "golden.json"

# Grid start used for every case (fixed so timestamps are deterministic).
_BASE = np.datetime64("2026-01-01T00:00:00", "ms")


# ---------------------------------------------------------------------------
# Series builders (seeded, deterministic)
# ---------------------------------------------------------------------------


def _grid(n: int, interval_seconds: int) -> np.ndarray:
    """A complete, evenly-spaced datetime64[ms] grid of ``n`` points."""
    step = np.timedelta64(interval_seconds * 1000, "ms")
    return (_BASE + np.arange(n) * step).astype("datetime64[ms]")


def _noisy_level(
    seed: int, n: int, level: float, sigma: float, spikes: dict[int, float]
) -> np.ndarray:
    """A flat noisy level with a few injected outliers at fixed indices."""
    rng = np.random.RandomState(seed)
    vals = level + rng.normal(0.0, sigma, n)
    for idx, mag in spikes.items():
        vals[idx] += mag
    return vals.astype(float)


def _trending_level(
    seed: int, n: int, level: float, slope: float, sigma: float, spikes: dict[int, float]
) -> np.ndarray:
    """A linearly trending noisy level with injected outliers (for detrend)."""
    rng = np.random.RandomState(seed)
    vals = level + slope * np.arange(n) + rng.normal(0.0, sigma, n)
    for idx, mag in spikes.items():
        vals[idx] += mag
    return vals.astype(float)


def _hourly_seasonal(
    seed: int, n: int, interval_seconds: int, spikes: dict[int, float]
) -> tuple[np.ndarray, np.ndarray]:
    """A series with a strong hour-of-day cycle + per-point seasonality_data.

    The seasonality payload mirrors what the loader hands ``detect()``: an
    object array of sorted-key JSON strings carrying a single ``hour_of_day``
    integer per point (0-23). The amplitude is hour-dependent, so conditioning
    on ``hour_of_day`` genuinely tightens the per-group band.
    """
    rng = np.random.RandomState(seed)
    ts = _grid(n, interval_seconds)
    hours = (ts.astype("datetime64[h]").astype(np.int64)) % 24
    vals = 100.0 + 40.0 * np.sin(2.0 * np.pi * hours / 24.0) + rng.normal(0.0, 5.0, n)
    for idx, mag in spikes.items():
        vals[idx] += mag

    payload = np.array(
        [json_dumps_sorted({"hour_of_day": int(h)}) for h in hours],
        dtype=object,
    )
    return vals.astype(float), payload


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------
#
# Each case carries everything the detector needs plus the camelCase param
# overrides for the TS side. ``params`` overrides are merged onto the detector
# defaults below, so a case only states what it changes.

_DEFAULT_INTERVAL = 600  # 10 minutes


def _make_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    # 1. MAD base — robust median/MAD band, two opposite-sign outliers.
    vals = _noisy_level(101, 360, level=50.0, sigma=4.0, spikes={180: 45.0, 300: -40.0})
    cases.append(
        {
            "name": "mad_base",
            "detector_type": "mad",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {"threshold": 3.0, "window_size": 100, "min_samples": 30},
            "ts_params": {
                "type": "mad",
                "threshold": 3.0,
                "windowSize": 100,
                "minSamples": 30,
            },
        }
    )

    # 2. Z-Score base — mean/std band.
    vals = _noisy_level(202, 360, level=200.0, sigma=12.0, spikes={150: 120.0, 280: -110.0})
    cases.append(
        {
            "name": "zscore_base",
            "detector_type": "zscore",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {"threshold": 3.0, "window_size": 100, "min_samples": 30},
            "ts_params": {
                "type": "zscore",
                "threshold": 3.0,
                "windowSize": 100,
                "minSamples": 30,
            },
        }
    )

    # 3. IQR base — Tukey fences (default threshold 1.5).
    vals = _noisy_level(303, 360, level=1000.0, sigma=30.0, spikes={170: 320.0, 290: -300.0})
    cases.append(
        {
            "name": "iqr_base",
            "detector_type": "iqr",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {"threshold": 1.5, "window_size": 100, "min_samples": 30},
            "ts_params": {
                "type": "iqr",
                "threshold": 1.5,
                "windowSize": 100,
                "minSamples": 30,
            },
        }
    )

    # 4. Exponential recency weighting with an INTEGER half_life (points), so
    #    the JS (half-life in points) matches exactly.
    vals = _noisy_level(404, 360, level=80.0, sigma=6.0, spikes={200: 60.0, 320: -55.0})
    cases.append(
        {
            "name": "mad_exp_weight",
            "detector_type": "mad",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {
                "threshold": 3.0,
                "window_size": 100,
                "min_samples": 30,
                "window_weights": "exponential",
                "half_life": 25,  # integer points -> exact JS parity
            },
            "ts_params": {
                "type": "mad",
                "threshold": 3.0,
                "windowSize": 100,
                "minSamples": 30,
                "windowWeights": "exponential",
                "halfLife": 25,
            },
        }
    )

    # 5. Linear detrend — a trending series so the slow drift isn't flagged.
    vals = _trending_level(
        505, 360, level=20.0, slope=0.25, sigma=5.0, spikes={210: 55.0, 330: -50.0}
    )
    cases.append(
        {
            "name": "zscore_detrend_linear",
            "detector_type": "zscore",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {
                "threshold": 3.0,
                "window_size": 100,
                "min_samples": 30,
                "detrend": "linear",
            },
            "ts_params": {
                "type": "zscore",
                "threshold": 3.0,
                "windowSize": 100,
                "minSamples": 30,
                "detrend": "linear",
            },
        }
    )

    # 6. Smoothing (EMA) — noise damped before the band math.
    vals = _noisy_level(606, 360, level=500.0, sigma=25.0, spikes={190: 220.0, 310: -200.0})
    cases.append(
        {
            "name": "mad_smoothing_ema",
            "detector_type": "mad",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {
                "threshold": 3.0,
                "window_size": 100,
                "min_samples": 30,
                "smoothing": "ema",
                "smoothing_alpha": 0.3,
            },
            "ts_params": {
                "type": "mad",
                "threshold": 3.0,
                "windowSize": 100,
                "minSamples": 30,
                "smoothing": "ema",
                "smoothingAlpha": 0.3,
            },
        }
    )

    # 7. input_type='changes' — score relative point-to-point changes.
    vals = _noisy_level(707, 360, level=300.0, sigma=8.0, spikes={205: 90.0, 315: -85.0})
    cases.append(
        {
            "name": "zscore_input_changes",
            "detector_type": "zscore",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {
                "threshold": 3.0,
                "window_size": 100,
                "min_samples": 30,
                "input_type": "changes",
            },
            "ts_params": {
                "type": "zscore",
                "threshold": 3.0,
                "windowSize": 100,
                "minSamples": 30,
                "inputType": "changes",
            },
        }
    )

    # 8. Seasonality grouping by hour_of_day — hourly series + JSON payload.
    n = 24 * 21  # three weeks of hourly points
    vals, payload = _hourly_seasonal(808, n, interval_seconds=3600, spikes={250: 90.0, 400: -85.0})
    cases.append(
        {
            "name": "mad_seasonality_hour",
            "detector_type": "mad",
            "interval_seconds": 3600,
            "values": vals,
            "seasonality_data": payload,
            "seasonality_columns": ["hour_of_day"],
            "detector_params": {
                "threshold": 3.0,
                "window_size": 168,  # one week of hourly history
                "min_samples": 30,
                "seasonality_components": [["hour_of_day"]],
                "min_samples_per_group": 3,
            },
            "ts_params": {
                "type": "mad",
                "threshold": 3.0,
                "windowSize": 168,
                "minSamples": 30,
                "seasonalityComponents": [["hour_of_day"]],
                "minSamplesPerGroup": 3,
            },
        }
    )

    # 9. Stabilization (clamp) — a sustained incident: flagged points enter
    #    subsequent windows clamped to the violated bound, so the band does not
    #    inflate and mask the incident tail (Z-Score is the most vulnerable).
    vals = _noisy_level(1111, 360, level=100.0, sigma=6.0, spikes={})
    vals[200:230] += 70.0  # 30-point incident inside the 100-point window
    cases.append(
        {
            "name": "zscore_stabilization_clamp",
            "detector_type": "zscore",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {
                "threshold": 3.0,
                "window_size": 100,
                "min_samples": 30,
                "stabilization": "clamp",
            },
            "ts_params": {
                "type": "zscore",
                "threshold": 3.0,
                "windowSize": 100,
                "minSamples": 30,
                "stabilization": "clamp",
            },
        }
    )

    # 10. Stabilization composed with exponential recency weighting — the
    #     worst case stabilization guards against (recent incident points get
    #     MORE weight), on the robust MAD detector.
    vals = _noisy_level(1212, 360, level=40.0, sigma=3.0, spikes={330: -25.0})
    vals[220:250] += 30.0
    cases.append(
        {
            "name": "mad_stabilization_exp_weight",
            "detector_type": "mad",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {
                "threshold": 3.0,
                "window_size": 100,
                "min_samples": 30,
                "window_weights": "exponential",
                "half_life": 25,
                "stabilization": "clamp",
            },
            "ts_params": {
                "type": "mad",
                "threshold": 3.0,
                "windowSize": 100,
                "minSamples": 30,
                "windowWeights": "exponential",
                "halfLife": 25,
                "stabilization": "clamp",
            },
        }
    )

    # 11. Manual bounds — stateless lower/upper thresholds on the raw values.
    #    No window/min_samples: every non-NaN point is scored straight away.
    vals = _noisy_level(909, 360, level=50.0, sigma=4.0, spikes={120: 30.0, 240: -30.0})
    cases.append(
        {
            "name": "manual_bounds_values",
            "detector_type": "manual_bounds",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {"lower_bound": 40.0, "upper_bound": 60.0},
            "ts_params": {
                "type": "manual_bounds",
                "lowerBound": 40.0,
                "upperBound": 60.0,
            },
        }
    )

    # 12. Manual bounds on absolute point-to-point changes — exercises the
    #     input_type preprocessing path (the first point is NaN -> not scored).
    vals = _noisy_level(1010, 360, level=300.0, sigma=8.0, spikes={150: 70.0, 270: -65.0})
    cases.append(
        {
            "name": "manual_bounds_abs_changes",
            "detector_type": "manual_bounds",
            "interval_seconds": _DEFAULT_INTERVAL,
            "values": vals,
            "seasonality_data": None,
            "seasonality_columns": None,
            "detector_params": {
                "lower_bound": -15.0,
                "upper_bound": 15.0,
                "input_type": "absolute_changes",
            },
            "ts_params": {
                "type": "manual_bounds",
                "lowerBound": -15.0,
                "upperBound": 15.0,
                "inputType": "absolute_changes",
            },
        }
    )

    return cases


# ---------------------------------------------------------------------------
# Detection + emission
# ---------------------------------------------------------------------------


def _clean_float(x: float | None) -> float | None:
    """Render a band bound for JSON; pass NaN/None through as null."""
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    return float(x)


# Complete DetectorParams defaults (types.ts shape). Each case states only its
# overrides; we merge them onto these so the emitted `params` is the FULL,
# type-correct object `runDetector(series, params)` expects — every field
# present (e.g. `seasonalityComponents: null` on non-seasonal cases), never a
# partial dict the TS side has to defensively pad.
_TS_PARAM_DEFAULTS: dict[str, Any] = {
    "type": "mad",
    "threshold": 3.0,
    "windowSize": 100,
    "minSamples": 30,
    "inputType": "values",
    "smoothing": "none",
    "smoothingAlpha": 0.3,
    "smoothingWindow": 10,
    "windowWeights": "none",
    "halfLife": None,
    "detrend": "none",
    "stabilization": "none",
    "seasonalityComponents": None,
    "minSamplesPerGroup": 10,
    "consecutiveAnomalies": 1,
    # manual_bounds thresholds (None for the windowed detectors) + the alert-layer
    # direction filter (ignored by runDetector, present for object completeness).
    "lowerBound": None,
    "upperBound": None,
    "direction": "any",
}


def _full_ts_params(overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge a case's camelCase overrides onto the complete DetectorParams."""
    unknown = set(overrides) - set(_TS_PARAM_DEFAULTS)
    if unknown:
        raise ValueError(f"unknown ts_params keys: {sorted(unknown)}")
    return {**_TS_PARAM_DEFAULTS, **overrides}


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    n = len(case["values"])
    interval_seconds = case["interval_seconds"]
    timestamps = _grid(n, interval_seconds)
    values = np.asarray(case["values"], dtype=np.float64)

    seasonality_data = case["seasonality_data"]
    if seasonality_data is None:
        seasonality_data = np.array([], dtype=object)
    seasonality_columns = case["seasonality_columns"] or []

    detector = DetectorFactory.create(case["detector_type"], case["detector_params"])

    data = {
        "timestamp": timestamps,
        "value": values,
        "seasonality_data": seasonality_data,
        "seasonality_columns": seasonality_columns,
    }
    results = detector.detect(data)

    expected: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        reason = (r.detection_metadata or {}).get("reason")
        scored = r.confidence_lower is not None and r.confidence_upper is not None
        expected.append(
            {
                "index": i,
                "scored": bool(scored),
                "isAnomaly": bool(r.is_anomaly),
                "lower": _clean_float(r.confidence_lower),
                "upper": _clean_float(r.confidence_upper),
                "reason": reason if reason is not None else ("ok" if scored else None),
            }
        )

    # Series block in the camelCase shape the TS `Series` type expects.
    series: dict[str, Any] = {
        "timestamps": [int(t) for t in timestamps.astype("datetime64[ms]").astype(np.int64)],
        "values": [_clean_float(float(v)) for v in values],
        "intervalSeconds": interval_seconds,
    }
    if case["seasonality_data"] is not None:
        series["seasonalityData"] = [json.loads(s) for s in case["seasonality_data"]]
        series["seasonalityColumns"] = seasonality_columns

    return {
        "name": case["name"],
        "series": series,
        "params": _full_ts_params(case["ts_params"]),
        "expected": expected,
    }


def main() -> None:
    cases = [_run_case(c) for c in _make_cases()]
    doc = {"cases": cases}
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, sort_keys=True, allow_nan=False)
    _OUT.write_text(text + "\n", encoding="utf-8")

    n_points = sum(len(c["expected"]) for c in cases)
    print(
        f"gen-demo-golden: wrote {_OUT.relative_to(_REPO_ROOT)} "
        f"({len(cases)} cases, {n_points} points, {len(text)} bytes)"
    )


if __name__ == "__main__":
    main()
