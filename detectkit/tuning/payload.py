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
from detectkit.core.interval import Interval
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
# A point only gets a band where the trailing window can fill, so showing fewer
# than a few windows of history would leave a large-window metric with almost no
# scored region (the band never reaches its real width). Floor the shown points
# at this many windows so the seeded window is actually exercised in the preview.
_TUNE_WINDOW_COVERAGE = 3


def default_window_points(seed_window: int) -> int:
    """Smart default point count for a seeded window size.

    Inversely sized to the window under a recompute budget (small windows can
    afford far more points), but floored at a few windows' worth of history so a
    large-window metric still has a meaningful scored region, and clamped to a
    render/payload-comfortable range.
    """
    w = max(int(seed_window or 0), 1)
    budget_points = round(_TUNE_COMPUTE_BUDGET / w)
    fill_points = w * _TUNE_WINDOW_COVERAGE
    return max(_TUNE_MIN_POINTS, min(_TUNE_MAX_POINTS, max(budget_points, fill_points)))


# Per-type interval-width defaults (mirror the detector class defaults and the
# website demo's DETECTOR_THRESHOLD_DEFAULT). autoreg has no per-group entry —
# it has no seasonality.
_THRESHOLD_DEFAULT = {"mad": 3.0, "zscore": 3.0, "iqr": 1.5, "autoreg": 3.0}
# Per-type min-samples-per-group defaults (mirror the detector subclasses).
_MIN_SAMPLES_PER_GROUP_DEFAULT = {"mad": 10, "zscore": 3, "iqr": 4}
# Detector types the interactive tuner can seed/emit: the windowed statistical
# detectors, the stateless manual_bounds (lower/upper threshold) detector, and
# the prediction-based autoreg (its own runAutoreg branch in the TS port).
# Hand-synced with config_writer._TUNABLE_TYPES.
_TUNABLE_TYPES = ("mad", "zscore", "iqr", "manual_bounds", "autoreg")
# The windowed statistical detectors — the ones you tune against a live band. When
# a metric mixes a windowed detector with a manual_bounds hard floor (the documented
# combo), the cockpit opens on the windowed one (the manual floor is a fixed business
# threshold, not something you slide against a baseline); the picker can still switch.
_WINDOWED_TYPES = ("mad", "zscore", "iqr")

# Built-in false-alert-rate budget used by the cockpit's quality bar when neither
# the metric nor the project sets one. Lax on purpose (warn only when more than
# half the alerts are false) — a per-metric/project `false_alert_budget` tightens it.
DEFAULT_FALSE_ALERT_BUDGET = 0.5


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


def _incident_span(incidents: list[dict[str, str]]) -> tuple[datetime, datetime] | None:
    """``(earliest start, latest end)`` (naive UTC) over seeded display dicts, or ``None``.

    The display dicts carry ``"YYYY-MM-DD HH:MM:SS"`` naive-UTC strings (see
    ``autotune.labels.incidents_to_display``), matching the naive datetimes the
    builder compares against the loaded series bounds.
    """

    def _parse(raw: Any) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    earliest: datetime | None = None
    latest: datetime | None = None
    for inc in incidents:
        start = _parse(inc.get("start"))
        end = _parse(inc.get("end")) or start
        if start is not None and (earliest is None or start < earliest):
            earliest = start
        if end is not None and (latest is None or end > latest):
            latest = end
    if earliest is None or latest is None:
        return None
    return earliest, latest


def seed_detector_params(dtype: str, params: dict[str, Any]) -> dict[str, Any]:
    """Map a (detector type, snake_case params) pair to the TS ``DetectorParams`` shape.

    The single snake→camel mapping used both to seed the controls from the
    metric's current config and to re-seed them from a server-side **Autotune**
    result, so the two paths produce an identical control state. The windowed
    knobs always carry sane defaults (even for a ``manual_bounds`` seed) so
    switching detector type in the UI never hits an empty slider;
    ``lowerBound``/``upperBound`` carry the manual thresholds (``None`` for a
    windowed config — the client picks a data default).
    """
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
        "stabilization": params.get("stabilization") or "none",
        "seasonalityComponents": _normalize_seasonality_components(
            params.get("seasonality_components")
        ),
        "minSamplesPerGroup": params.get(
            "min_samples_per_group", _MIN_SAMPLES_PER_GROUP_DEFAULT.get(dtype, 10)
        ),
        # manual_bounds thresholds (None for a windowed metric).
        "lowerBound": params.get("lower_bound"),
        "upperBound": params.get("upper_bound"),
        # autoreg AR order (harmless default for the other types' seeds).
        "lags": params.get("lags", 5),
    }
    if dtype == "autoreg":
        # autoreg's stabilization is default-ON (unlike the windowed detectors),
        # so an absent key must seed the control to "clamp", and only an
        # explicit null in the config reads as "none".
        raw_stab = params.get("stabilization", "clamp")
        seed["stabilization"] = raw_stab or "none"
    return seed


def _choose_seed_index(metric_config: MetricConfig) -> int | None:
    """Index (into ``metric_config.detectors``) of the detector to open the cockpit on.

    Prefers the first **windowed** detector (mad/zscore/iqr) — the one you tune
    against a live band — then the first tunable one (a manual_bounds floor), then
    ``None`` when the metric has no tunable detector at all (e.g. only prophet).
    The picker can switch to any other tunable detector afterwards.
    """
    detectors = metric_config.detectors
    for i, d in enumerate(detectors):
        if d.type in _WINDOWED_TYPES:
            return i
    for i, d in enumerate(detectors):
        if d.type in _TUNABLE_TYPES:
            return i
    return None


def _detector_summary(dtype: str, params: dict[str, Any]) -> str:
    """A compact one-line summary of a detector for the cockpit's picker / preserve note.

    e.g. ``mad · threshold=3.0 · window=8640`` or ``manual_bounds · lower=1``. Used
    only for display; the emitted config comes from the (re)seeded controls.
    """
    if dtype == "manual_bounds":
        bits = []
        if params.get("lower_bound") is not None:
            bits.append(f"lower={params['lower_bound']}")
        if params.get("upper_bound") is not None:
            bits.append(f"upper={params['upper_bound']}")
        return " · ".join(["manual_bounds", *bits]) if bits else "manual_bounds"
    if dtype == "autoreg":
        thr = params.get("threshold", 3.0)
        win = params.get("window_size", 200)
        return f"autoreg · lags={params.get('lags', 5)} · threshold={thr} · window={win}"
    if dtype in _WINDOWED_TYPES:
        thr = params.get("threshold", _THRESHOLD_DEFAULT.get(dtype, 3.0))
        win = params.get("window_size", 100)
        return f"{dtype} · threshold={thr} · window={win}"
    # prophet / timesfm and any future non-tunable type: name only.
    return dtype


def _detectors_payload(metric_config: MetricConfig) -> tuple[list[dict[str, Any]], int | None]:
    """Bake **every** detector for the cockpit's picker, plus the active index.

    Returns ``(entries, active_index)`` where each entry is
    ``{index, type, tunable, seed, summary}`` — ``seed`` is the camelCase control
    seed for tunable detectors and ``None`` for non-tunable ones (prophet/timesfm),
    which the cockpit surfaces read-only as "preserved on Apply". ``active_index`` is
    the slot the cockpit opens on (see :func:`_choose_seed_index`), or ``None`` when
    the metric has no tunable detector (the cockpit then seeds fresh MAD defaults and
    Apply adds them without touching the existing detectors).
    """
    entries: list[dict[str, Any]] = []
    for i, d in enumerate(metric_config.detectors):
        tunable = d.type in _TUNABLE_TYPES
        params = dict(d.params)
        entries.append(
            {
                "index": i,
                "type": d.type,
                "tunable": tunable,
                "seed": seed_detector_params(d.type, params) if tunable else None,
                "summary": _detector_summary(d.type, params),
            }
        )
    return entries, _choose_seed_index(metric_config)


def _seed_detector(metric_config: MetricConfig) -> dict[str, Any]:
    """Seed the controls from the detector the cockpit opens on.

    Uses :func:`_choose_seed_index` (first windowed, then first tunable); falls back
    to MAD defaults when the metric has no tunable detector, then maps it via
    :func:`seed_detector_params`.
    """
    idx = _choose_seed_index(metric_config)
    chosen = metric_config.detectors[idx] if idx is not None else None
    dtype = chosen.type if chosen is not None else "mad"
    params = dict(chosen.params) if chosen is not None else {}
    return seed_detector_params(dtype, params)


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


def _ai_context_payload(metric_config: MetricConfig) -> dict[str, Any] | None:
    """Serialize the metric's OSI ``ai_context`` for the cockpit (``None`` when unset).

    Read-only grounding the cockpit HUD can show so the human tuner sees the KPI's
    business meaning + alternative names while labeling. Purely descriptive — it
    never touches the band, the recompute or the quality metrics.
    """
    ac = metric_config.ai_context
    if ac is None:
        return None
    return {
        "instructions": ac.instructions,
        "synonyms": list(ac.synonyms),
        "examples": list(ac.examples),
    }


def build_tune_payload(
    *,
    metric_config: MetricConfig,
    internal: InternalTablesManager,
    start: datetime | None = None,
    end: datetime | None = None,
    project_name: str | None = None,
    save_url: str | None = None,
    incidents: list[dict[str, str]] | None = None,
    capture_windows: list[dict[str, str]] | None = None,
    alert_reviews: list[dict[str, str]] | None = None,
    false_alert_budget: float | None = None,
) -> dict[str, Any]:
    """Assemble the interactive tuning payload from the persisted ``_dtk_datapoints``.

    ``save_url`` is the localhost POST endpoint the **Apply** button targets; it
    is ``None`` for a static (read-only, no write-back) preview. With no explicit
    ``start``/``end`` the window defaults to a budget-sized recent slice
    (``default_window_points``), not the whole history.

    ``incidents`` seeds the synced labeler with already-marked spans (display dicts
    ``{start, end, label}`` from ``incidents_to_display``). When incidents are
    seeded the (still budget-sized) window is anchored on the incident region — it
    ends just past the latest incident rather than at the last datapoint — so they
    render on the chart and count toward the live recall/FDR metrics, while the
    window stays bounded (a single old outlier incident can't pull the whole
    history in). An explicit ``start``/``--from`` is still honored verbatim.
    ``capture_windows`` seeds the threshold-capture regime scope (display dicts
    ``{start, end}``). ``labels_save_url`` (the POST endpoint for **Save
    incidents**) and ``autotune_url`` (the POST endpoint for the server-side
    **Autotune** mode) are injected by the server, like ``save_url`` — both are
    ``None`` here.
    """
    seed_incidents = incidents or []
    seed_capture = capture_windows or []
    seed_reviews = alert_reviews or []
    fa_budget = false_alert_budget if false_alert_budget is not None else DEFAULT_FALSE_ALERT_BUDGET
    name = metric_config.name
    interval = metric_config.get_interval()
    interval_seconds = interval.seconds

    seed = _seed_detector(metric_config)
    detector_entries, active_index = _detectors_payload(metric_config)
    ai_ctx = _ai_context_payload(metric_config)

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
        budget = timedelta(seconds=interval_seconds * default_points)
        # When incidents are seeded, ANCHOR the (still budget-sized) window on the
        # incident region instead of always ending at the last datapoint, so the
        # incidents render and can be scored. Crucially the window stays bounded:
        # the end is pulled back to just past the LATEST incident (a few windows of
        # recovery context) only when that is older than the last datapoint, so a
        # single old outlier incident can't drag the whole history in — it would
        # blow the recompute budget (the page hangs). Incidents older than the
        # bounded window stay in the list and are excluded from the live metrics.
        span = _incident_span(seed_incidents)
        if span is not None:
            _, latest = span
            # Align awareness to end (both represent UTC) so the comparison is valid
            # on backends that return tz-aware timestamps.
            if end.tzinfo is not None and latest.tzinfo is None:
                latest = latest.replace(tzinfo=end.tzinfo)
            elif end.tzinfo is None and latest.tzinfo is not None:
                latest = latest.replace(tzinfo=None)
            context = timedelta(
                seconds=interval_seconds * max(_TUNE_WINDOW_COVERAGE * int(seed["windowSize"]), 200)
            )
            end = min(end, latest + context)
        start = end - budget
        if first is not None:
            start = max(start, first)

    consecutive = 3
    anomaly_window_points: int | None = None
    min_anomaly_share: float | None = None
    if metric_config.alerting:
        first_alert = metric_config.alerting[0]
        consecutive = first_alert.consecutive_anomalies
        # Fraction rule seeds (issue #101): pre-resolved to grid points with the
        # same floor-div as AlertConditions.from_alert_config, since the worker
        # sweeps in points.
        if first_alert.anomaly_window is not None and first_alert.min_anomaly_share is not None:
            anomaly_window_points = max(
                1, Interval(first_alert.anomaly_window).seconds // interval_seconds
            )
            min_anomaly_share = first_alert.min_anomaly_share
    direction = _seed_direction(metric_config)

    empty: dict[str, Any] = {
        "metric": name,
        "project": project_name,
        "description": metric_config.description,
        "ai_context": ai_ctx,
        "interval_seconds": interval_seconds,
        "period": {"start": 0, "end": 0},
        "points": [],
        "seasonality": [],
        "seasonality_columns": [],
        "detector": seed,
        "detectors": detector_entries,
        "detector_index": active_index,
        "consecutive_anomalies": consecutive,
        "anomaly_window_points": anomaly_window_points,
        "min_anomaly_share": min_anomaly_share,
        "direction": direction,
        "save_url": save_url,
        "incidents": seed_incidents,
        "capture_windows": seed_capture,
        "alert_reviews": seed_reviews,
        "false_alert_budget": fa_budget,
        "labels_save_url": None,
        "autotune_url": None,
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
        "ai_context": ai_ctx,
        "interval_seconds": interval_seconds,
        "period": {"start": _ms(start), "end": end_ms},
        "points": points,
        "seasonality": seasonality,
        "seasonality_columns": season_cols,
        "detector": seed,
        "detectors": detector_entries,
        "detector_index": active_index,
        "consecutive_anomalies": consecutive,
        "anomaly_window_points": anomaly_window_points,
        "min_anomaly_share": min_anomaly_share,
        "direction": direction,
        "save_url": save_url,
        "incidents": seed_incidents,
        "capture_windows": seed_capture,
        "alert_reviews": seed_reviews,
        "false_alert_budget": fa_budget,
        "labels_save_url": None,
        "autotune_url": None,
    }
