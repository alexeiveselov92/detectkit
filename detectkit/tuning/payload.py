"""Build the JSON payload baked into the interactive tuning page.

Unlike the read-only report payload (``reporting/builder.py``), the tuning
payload carries everything the **client-side detector port** needs to *recompute*
bands live as the user turns the knobs: the raw gap-filled series, the per-point
seasonality keys, the metric's current detector config (to seed the controls)
and the alert ``consecutive_anomalies``. It deliberately does NOT bake any
precomputed detection — the browser runs the detector itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from detectkit.config.metric_config import MetricConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.reporting.builder import _ms, _num_or_none, _parse_seasonality

# How many (most recent) points to show when no explicit window is given.
#
# Tuning recomputes the detector client-side on every knob change, which is
# O(points x window); baking the whole history (10k-100k points) makes the page
# slow to load and laggy. The renderer runs detection in a Web Worker (off the UI
# thread), so the budget is "how many window-touches keep a debounced recompute
# under ~1s" rather than "what keeps the UI from freezing". We size the default
# point count INVERSELY to the seeded window — small windows can afford far more
# points than large ones — clamped to a render/payload-comfortable range. An
# explicit --from/--to span is honored in full (the user opted into that cost).
_TUNE_COMPUTE_BUDGET = 20_000_000  # ~points x window per recompute (off-thread)
_TUNE_MIN_POINTS = 3000
_TUNE_MAX_POINTS = 15000


def default_window_points(seed_window: int) -> int:
    """Smart default point count for a seeded window size (budget-bound + clamped)."""
    w = max(int(seed_window or 0), 1)
    return max(_TUNE_MIN_POINTS, min(_TUNE_MAX_POINTS, round(_TUNE_COMPUTE_BUDGET / w)))


# Per-type interval-width defaults (mirror the detector class defaults and the
# website demo's DETECTOR_THRESHOLD_DEFAULT).
_THRESHOLD_DEFAULT = {"mad": 3.0, "zscore": 3.0, "iqr": 1.5}
# Per-type min-samples-per-group defaults (mirror the detector subclasses).
_MIN_SAMPLES_PER_GROUP_DEFAULT = {"mad": 10, "zscore": 3, "iqr": 4}
# Detector types the interactive tuner can seed/emit: the windowed statistical
# detectors plus the stateless manual_bounds (lower/upper threshold) detector.
_TUNABLE_TYPES = ("mad", "zscore", "iqr", "manual_bounds")


def _normalize_seasonality_components(
    components: list[str | list[str]] | None,
) -> list[list[str]] | None:
    """Normalize the YAML ``seasonality_components`` to a list of column groups.

    The YAML accepts a bare string (single-column group) or a list of columns
    (conjunctive group); the TS port wants ``string[][]``.
    """
    if not components:
        return None
    groups: list[list[str]] = []
    for comp in components:
        groups.append([comp] if isinstance(comp, str) else list(comp))
    return groups or None


def _seed_detector(metric_config: MetricConfig) -> dict[str, Any]:
    """Map the metric's current detector config to the TS ``DetectorParams`` shape.

    Picks the first tunable (mad/zscore/iqr/manual_bounds) detector to seed the
    sliders; falls back to MAD defaults when the metric has none. Param names are
    camelCased to match the client port. The windowed knobs always carry sane
    defaults (even for a manual_bounds seed) so switching detector type in the UI
    never hits an empty slider; ``lowerBound``/``upperBound`` carry the manual
    thresholds (``None`` for a windowed metric — the client picks a data default).
    """
    chosen = next(
        (d for d in metric_config.detectors if d.type in _TUNABLE_TYPES),
        None,
    )
    dtype = chosen.type if chosen is not None else "mad"
    params = dict(chosen.params) if chosen is not None else {}

    half_life = params.get("half_life")
    seed: dict[str, Any] = {
        "type": dtype,
        "threshold": params.get("threshold", _THRESHOLD_DEFAULT.get(dtype, 3.0)),
        "windowSize": params.get("window_size", 100),
        "minSamples": params.get("min_samples", 30),
        "inputType": params.get("input_type", "values"),
        "smoothing": params.get("smoothing") or "none",
        "smoothingAlpha": params.get("smoothing_alpha", 0.3),
        "smoothingWindow": params.get("smoothing_window", 10),
        "windowWeights": params.get("window_weights") or "none",
        # The TS control is in points; a duration-string half_life can't seed a
        # numeric slider, so fall back to adaptive (null) and let the user re-pick.
        "halfLife": (
            half_life if isinstance(half_life, int) and not isinstance(half_life, bool) else None
        ),
        "detrend": params.get("detrend") or "none",
        "seasonalityComponents": _normalize_seasonality_components(
            params.get("seasonality_components")
        ),
        "minSamplesPerGroup": params.get(
            "min_samples_per_group", _MIN_SAMPLES_PER_GROUP_DEFAULT.get(dtype, 10)
        ),
        # manual_bounds thresholds (None for a windowed metric).
        "lowerBound": params.get("lower_bound"),
        "upperBound": params.get("upper_bound"),
    }
    return seed


def _seed_direction(metric_config: MetricConfig) -> str:
    """Seed the tuner's direction view-filter from the first alerting block.

    The tuner offers ``any``/``up``/``down``; the alerting policy may also be
    ``same`` (a multi-detector agreement rule). Tuning is single-detector, so
    ``same`` reads as ``any`` for the preview. Defaults to ``any``.
    """
    if not metric_config.alerting:
        return "any"
    raw = (metric_config.alerting[0].direction or "any").lower()
    return raw if raw in ("up", "down", "any") else "any"


def build_tune_payload(
    *,
    metric_config: MetricConfig,
    internal: InternalTablesManager,
    start: datetime | None = None,
    end: datetime | None = None,
    project_name: str | None = None,
    save_url: str | None = None,
) -> dict[str, Any]:
    """Assemble the interactive tuning payload from the persisted ``_dtk_datapoints``.

    ``save_url`` is the localhost POST endpoint the **Apply** button targets; it
    is ``None`` for a static (read-only, no write-back) preview. With no explicit
    ``start``/``end`` the window defaults to a budget-sized recent slice
    (``default_window_points``), not the whole history.
    """
    name = metric_config.name
    interval = metric_config.get_interval()
    interval_seconds = interval.seconds

    seed = _seed_detector(metric_config)

    # Resolve the window. ``end`` defaults to the last datapoint. ``start``
    # defaults to a budget-sized number of intervals before ``end`` (clamped to the
    # first datapoint) — sized inversely to the seeded window, NOT the whole
    # history — so the page stays interactive on large metrics. An explicit
    # ``start`` (``--from``) is honored as-is.
    if end is None:
        end = internal.get_last_datapoint_timestamp(name)
    if start is None and end is not None:
        first = internal.get_first_datapoint_timestamp(name)
        default_points = default_window_points(int(seed["windowSize"]))
        lookback = end - timedelta(seconds=interval_seconds * default_points)
        start = max(first, lookback) if first is not None else lookback

    consecutive = 3
    if metric_config.alerting:
        consecutive = metric_config.alerting[0].consecutive_anomalies
    direction = _seed_direction(metric_config)

    empty: dict[str, Any] = {
        "metric": name,
        "project": project_name,
        "description": metric_config.description,
        "interval_seconds": interval_seconds,
        "period": {"start": 0, "end": 0},
        "points": [],
        "seasonality": [],
        "seasonality_columns": [],
        "detector": seed,
        "consecutive_anomalies": consecutive,
        "direction": direction,
        "save_url": save_url,
    }
    if start is None or end is None:
        return empty

    to_exclusive = end + timedelta(seconds=interval_seconds)
    data = internal.load_datapoints(name, start, to_exclusive)
    timestamps = data["timestamp"]
    if len(timestamps) == 0:
        return empty

    values = data["value"]
    season_raw: Any = data.get("seasonality_data", [])
    season_cols = list(data.get("seasonality_columns", []) or [])
    end_ms = _ms(end)

    points: list[dict[str, Any]] = []
    seasonality: list[dict[str, Any]] = []
    for i in range(len(timestamps)):
        t_ms = _ms(timestamps[i])
        if t_ms > end_ms:
            continue
        points.append({"t": t_ms, "v": _num_or_none(values[i])})
        cell = season_raw[i] if i < len(season_raw) else None
        seasonality.append(_parse_seasonality(cell) if season_cols else {})

    return {
        "metric": name,
        "project": project_name,
        "description": metric_config.description,
        "interval_seconds": interval_seconds,
        "period": {"start": _ms(start), "end": end_ms},
        "points": points,
        "seasonality": seasonality,
        "seasonality_columns": season_cols,
        "detector": seed,
        "consecutive_anomalies": consecutive,
        "direction": direction,
        "save_url": save_url,
    }
