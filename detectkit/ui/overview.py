"""Build the project-level overview payload for ``dtk ui``.

Pure given an :class:`InternalTablesManager`: reads the persisted
``_dtk_datapoints`` / ``_dtk_detections`` / ``_dtk_tasks`` tables for each
selected metric and replays alerts via the shared
:func:`detectkit.reporting.builder.replay_alert_events` seam (the same one
``dtk run --report`` uses), so the frequency numbers here match what the
pipeline would actually have alerted. Optional quality stats (recall /
false-alert rate / reviewed) are layered in when a metric has a labels file
under ``incidents/<metric>/`` (the store ``dtk tune`` / ``dtk autotune`` share).

A single bad metric (a DB hiccup, a malformed labels file) never aborts the
whole payload — its row carries an ``error`` string and every stat field
degrades to ``null``/``0`` instead of raising.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from detectkit.alerting.orchestrator import ReplayedEvent
from detectkit.autotune.labels import IncidentLabels, newest_labels_file, parse_labels_file
from detectkit.config.metric_config import AlertConfig, MetricConfig
from detectkit.config.project_config import ProjectConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.detectors.factory import DetectorFactory
from detectkit.reporting.builder import _ms, _num_or_none, record_from_row, replay_alert_events
from detectkit.tuning.payload import DEFAULT_FALSE_ALERT_BUDGET
from detectkit.utils.datetime_utils import now_utc_naive

# Day counts for the fixed presets; "all" is handled separately (see
# _resolve_metric_window) since it has no fixed lookback.
WINDOW_PRESETS: dict[str, int] = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}
ALL_WINDOW_PRESETS = frozenset({*WINDOW_PRESETS, "all"})

# Cap on the "all" preset's lookback (in points, scaled by the metric's own
# interval) so a years-long high-frequency metric can't melt the browser/DB
# with an unbounded read.
MAX_STAT_POINTS = 20_000

_MAX_SPARK_BUCKETS = 160
_MAX_SPARK_ANOMS = 400

# The pipeline lock triple every `dtk run`/`dtk autotune` invocation acquires
# (detectkit/orchestration/task_manager/manager.py:TaskManager.run_metric) —
# mirrored here (read-only) so the overview can show a metric as "locked"
# without any of orchestration's write-side machinery.
_LOCK_DETECTOR_ID = "pipeline"
_LOCK_PROCESS_TYPE = "pipeline"


def resolve_metric_location(
    metric_path: Path, project_root: Path, metrics_dir: Path
) -> tuple[str, str]:
    """``(dir, file)`` for a metric YAML.

    ``dir`` is the parent directory relative to ``metrics/`` (``""`` for a
    root-level metric); ``file`` is the path relative to the project root.
    Both are posix-separated strings regardless of platform. Falls back to the
    raw path when it isn't actually under the expected root (defensive; never
    raises on the boot payload / overview row).
    """
    try:
        rel_dir = metric_path.parent.relative_to(metrics_dir)
        dir_str = "" if rel_dir == Path() else rel_dir.as_posix()
    except ValueError:
        dir_str = ""
    try:
        file_str = metric_path.relative_to(project_root).as_posix()
    except ValueError:
        file_str = metric_path.as_posix()
    return dir_str, file_str


def _alert_rule_summary(alerting: list[AlertConfig] | None) -> dict[str, Any] | None:
    """Summarize a metric's alerting block(s), or ``None`` when it has none.

    The scalar fields (``min_detectors``/``direction``/``consecutive``) come
    from the first configured block — a metric with several alerting blocks
    still gets one glanceable rule in the table; ``configs``/``enabled`` show
    there is more than one.
    """
    if not alerting:
        return None
    first = alerting[0]
    return {
        "configs": len(alerting),
        "enabled": sum(1 for c in alerting if c.enabled),
        "min_detectors": first.min_detectors,
        "direction": first.direction,
        "consecutive": first.consecutive_anomalies,
    }


def _configured_detector_ids(config: MetricConfig) -> list[str]:
    """The detector ids the metric's CURRENT config would run under.

    Mirrors the detect step's id derivation (``get_algorithm_params`` +
    seasonality → ``DetectorFactory.create_from_config`` → ``get_detector_id``).
    Every retune/autotune changes a detector's id, and the superseded ids'
    rows stay in ``_dtk_detections`` forever — so an unfiltered window read
    returns one row-set per historical config generation: N× the volume, and
    replayed quorums that mix live and dead configs (inflating alert counts
    a real pipeline run would never produce). The overview answers "how does
    the metric behave under its current config", so it reads only these ids.

    Returns ``[]`` when no id can be derived (no detectors configured, or a
    config the factory rejects) — the caller then falls back to unfiltered.
    """
    ids: list[str] = []
    for detector_config in config.detectors:
        try:
            params = detector_config.get_algorithm_params()
            seasonality = detector_config.get_seasonality_components()
            if seasonality is not None:
                params["seasonality_components"] = seasonality
            detector = DetectorFactory.create_from_config(
                {"type": detector_config.type, "params": params}
            )
            ids.append(detector.get_detector_id())
        except Exception:  # noqa: BLE001 — fall back to unfiltered on any bad config
            return []
    return ids


def _load_window_detections(
    internal: InternalTablesManager,
    metric_name: str,
    detector_ids: list[str],
    start: datetime,
    to_exclusive: datetime,
) -> list[dict[str, Any]]:
    """Window detections for the given detector ids (all ids when empty).

    Per-id queries push the filter into SQL instead of transferring every
    historical generation's rows; the merged result is re-sorted to the
    global ``(timestamp, detector_id)`` order ``load_detections`` guarantees,
    which the replay walk expects.
    """
    if not detector_ids:
        return internal.load_detections(metric_name, None, start, to_exclusive)
    rows: list[dict[str, Any]] = []
    for detector_id in detector_ids:
        rows.extend(internal.load_detections(metric_name, detector_id, start, to_exclusive))
    rows.sort(key=lambda r: (r["timestamp"], r["detector_id"]))
    return rows


def _resolve_metric_window(
    internal: InternalTablesManager,
    metric_name: str,
    interval_seconds: int,
    window_preset: str,
    now: datetime,
) -> tuple[datetime | None, datetime | None]:
    """Resolve ``[start, end]`` for one metric's stats under *window_preset*.

    ``end`` is always the metric's last datapoint (``None`` when it has none —
    the caller then skips all window-dependent stats). For a fixed preset,
    ``start = now - preset_days`` (mirrors ``reporting.builder.resolve_window``
    but with an explicit start rather than a lookback-from-end default, so a
    metric with a short history simply shows less than the full preset). For
    ``"all"``, the lookback is capped at :data:`MAX_STAT_POINTS` intervals
    (clamped to the first datapoint) instead of the default report window —
    "all" here means "everything, bounded", not the report's short recent
    slice.
    """
    end = internal.get_last_datapoint_timestamp(metric_name)
    if end is None:
        return None, None
    if window_preset == "all":
        first = internal.get_first_datapoint_timestamp(metric_name)
        lookback = end - timedelta(seconds=interval_seconds * MAX_STAT_POINTS)
        start = max(first, lookback) if first is not None else lookback
        return start, end
    days = WINDOW_PRESETS[window_preset]
    return now - timedelta(days=days), end


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Whether closed intervals ``[a_start, a_end]`` and ``[b_start, b_end]`` overlap."""
    return a_start <= b_end and b_start <= a_end


def _incident_spans_ms(labels: IncidentLabels) -> list[tuple[int, int]]:
    """Every labeled incident (intervals + points) as ``(start_ms, end_ms)``."""
    spans = [(_ms(iv.start), _ms(iv.end)) for iv in labels.intervals]
    spans.extend((_ms(p.at), _ms(p.at)) for p in labels.points)
    return spans


def _anomaly_event_spans(
    anomaly_events: list[tuple[str, ReplayedEvent]],
) -> list[tuple[int, int]]:
    """Each anomaly event's ``[onset, t]`` span in ms (onset falls back to ``t``)."""
    spans = []
    for _config_id, event in anomaly_events:
        t_ms = _ms(event.timestamp)
        onset = event.alert_data.onset_timestamp
        onset_ms = _ms(onset) if onset is not None else t_ms
        spans.append((onset_ms, t_ms))
    return spans


def _compute_quality(
    labels: IncidentLabels,
    anomaly_events: list[tuple[str, ReplayedEvent]],
    *,
    start_ms: int,
    end_ms: int,
    labels_rel_path: str,
) -> dict[str, Any]:
    """Recall / false-alert-rate / reviewed stats for one metric's window.

    Mirrors the overlap rules the ``dtk tune`` cockpit uses (matched on spans,
    not instants): an incident is "caught" when it overlaps at least one
    alert's ``[onset, t]`` span; an alert is "false" when its span overlaps no
    in-window incident AND no review verdict marking it valid. Only incidents
    intersecting the window count toward recall/FDR (an out-of-window label
    can't mechanically drag the numbers down).
    """
    incidents_in_window = [
        span for span in _incident_spans_ms(labels) if _overlaps(*span, start_ms, end_ms)
    ]
    review_spans = [(_ms(s), _ms(e), verdict) for s, e, verdict in labels.alert_reviews]
    alert_spans = _anomaly_event_spans(anomaly_events)

    caught = sum(
        1 for inc in incidents_in_window if any(_overlaps(*inc, *alert) for alert in alert_spans)
    )
    recall = (caught / len(incidents_in_window)) if incidents_in_window else None

    reviewed_valid = 0
    reviewed_false = 0
    false_alerts = 0
    for a_start, a_end in alert_spans:
        verdicts = {rv for r_s, r_e, rv in review_spans if _overlaps(a_start, a_end, r_s, r_e)}
        if "valid" in verdicts:
            reviewed_valid += 1
        elif "false" in verdicts:
            reviewed_false += 1
        overlaps_incident = any(_overlaps(a_start, a_end, *inc) for inc in incidents_in_window)
        if not overlaps_incident and "valid" not in verdicts:
            false_alerts += 1

    n_anomaly_events = len(alert_spans)
    fdr = (false_alerts / n_anomaly_events) if n_anomaly_events else None

    return {
        "incidents": len(labels.intervals) + len(labels.points),
        "incidents_in_window": len(incidents_in_window),
        "caught": caught,
        "recall": recall,
        "false_alerts": false_alerts,
        "fdr": fdr,
        "reviewed": reviewed_valid + reviewed_false,
        "reviewed_valid": reviewed_valid,
        "reviewed_false": reviewed_false,
        "labels_file": labels_rel_path,
    }


def _spark_series(ts_arr: np.ndarray, val_arr: np.ndarray) -> list[list[Any]]:
    """Bucket a window's datapoints into <= :data:`_MAX_SPARK_BUCKETS` ``[t, mean]`` pairs.

    ``t`` is the last timestamp of each bucket; the value is the mean of the
    bucket's non-NaN values (``None`` when every value in the bucket is NaN).
    """
    n = len(ts_arr)
    if n == 0:
        return []
    step = max(1, -(-n // _MAX_SPARK_BUCKETS))  # ceil(n / _MAX_SPARK_BUCKETS)
    out: list[list[Any]] = []
    for i in range(0, n, step):
        chunk = np.asarray(val_arr[i : i + step], dtype=np.float64)
        finite = chunk[~np.isnan(chunk)]
        mean_v = float(finite.mean()) if finite.size else None
        t_ms = _ms(ts_arr[i + len(chunk) - 1])
        out.append([t_ms, mean_v])
    return out


def _downsample_evenly(values: list[int], cap: int) -> list[int]:
    """Evenly-spaced subset of *values* (sorted, ascending), capped at *cap* entries."""
    n = len(values)
    if n <= cap:
        return values
    idx = sorted({int(round(float(x))) for x in np.linspace(0, n - 1, cap)})
    return [values[i] for i in idx]


def _empty_row(name: str) -> dict[str, Any]:
    """The full-shape row with every stat field at its "no data" default."""
    return {
        "name": name,
        "dir": "",
        "file": "",
        "tags": [],
        "enabled": True,
        "interval_seconds": 0,
        "detectors": [],
        "alert_rule": None,
        "last_point": None,
        "first_point_in_window": None,
        "lag_seconds": None,
        "locked": False,
        "points": 0,
        "flagged": 0,
        "anomaly_rate": None,
        "alerts": {"anomaly": 0, "recovery": 0, "no_data": 0, "per_day": None, "last_ts": None},
        "quality": None,
        "budget": DEFAULT_FALSE_ALERT_BUDGET,
        "spark": [],
        "spark_anoms": [],
        "error": None,
    }


def _fill_config_fields(
    row: dict[str, Any],
    *,
    project_root: Path,
    metrics_dir: Path,
    metric_path: Path,
    config: MetricConfig,
    project_budget: float,
) -> None:
    """Populate the fields derived purely from the (already-validated) config."""
    dir_str, file_str = resolve_metric_location(metric_path, project_root, metrics_dir)
    row["dir"] = dir_str
    row["file"] = file_str
    row["tags"] = list(config.tags) if config.tags else []
    row["enabled"] = config.enabled
    row["interval_seconds"] = config.get_interval().seconds
    row["detectors"] = [d.type for d in config.detectors]
    row["alert_rule"] = _alert_rule_summary(config.alerting)
    row["budget"] = (
        config.false_alert_budget if config.false_alert_budget is not None else project_budget
    )


def _fill_stats(
    row: dict[str, Any],
    *,
    config: MetricConfig,
    internal: InternalTablesManager,
    window_preset: str,
    now: datetime,
    project_root: Path,
    project_name: str | None,
) -> None:
    """Populate every DB-driven field (freshness, lock, frequency, quality, spark)."""
    name = config.name
    interval_seconds = row["interval_seconds"]

    last_point = internal.get_last_datapoint_timestamp(name)
    row["last_point"] = _ms(last_point) if last_point is not None else None
    row["lag_seconds"] = (now - last_point).total_seconds() if last_point is not None else None
    row["locked"] = internal.check_lock(name, _LOCK_DETECTOR_ID, _LOCK_PROCESS_TYPE) is not None

    start, end = _resolve_metric_window(internal, name, interval_seconds, window_preset, now)
    if start is None or end is None:
        return  # no datapoints at all — everything else stays at its default

    end_ms = _ms(end)
    to_exclusive = end + timedelta(seconds=interval_seconds)

    dp = internal.load_datapoints(name, start, to_exclusive)
    ts_arr = dp["timestamp"]
    val_arr = dp["value"]
    # Defensive clamp mirroring reporting.builder: load_datapoints' half-open
    # upper bound already excludes anything past `end`, but keep the window
    # exact in case of a misaligned/duplicate grid point.
    if len(ts_arr):
        keep = np.array([_ms(t) <= end_ms for t in ts_arr], dtype=bool)
        ts_arr = ts_arr[keep]
        val_arr = val_arr[keep]

    n_points = int(len(ts_arr))
    row["points"] = n_points
    row["first_point_in_window"] = _ms(ts_arr[0]) if n_points else None

    det_rows = _load_window_detections(
        internal, name, _configured_detector_ids(config), start, to_exclusive
    )
    det_rows = [r for r in det_rows if _ms(r["timestamp"]) <= end_ms]

    anomalous_timestamps: set[int] = set()
    for r in det_rows:
        if bool(r["is_anomaly"]):
            anomalous_timestamps.add(_ms(r["timestamp"]))
    row["flagged"] = len(anomalous_timestamps)
    row["anomaly_rate"] = (len(anomalous_timestamps) / n_points) if n_points else None

    value_at: dict[np.datetime64, float | None] = {
        np.datetime64(ts, "ms"): _num_or_none(v) for ts, v in zip(ts_arr, val_arr, strict=False)
    }
    records = [record_from_row(r) for r in det_rows]
    event_pairs = replay_alert_events(config, internal, records, value_at, start, end, project_name)

    counts = {"anomaly": 0, "recovery": 0, "no_data": 0}
    anomaly_events: list[tuple[str, ReplayedEvent]] = []
    last_anom_ms: int | None = None
    for config_id, event in event_pairs:
        counts[event.kind] += 1
        if event.kind == "anomaly":
            anomaly_events.append((config_id, event))
            t_ms = _ms(event.timestamp)
            if last_anom_ms is None or t_ms > last_anom_ms:
                last_anom_ms = t_ms

    window_days_actual = (end - start).total_seconds() / 86400.0
    per_day = (counts["anomaly"] / window_days_actual) if window_days_actual > 0 else None
    row["alerts"] = {
        "anomaly": counts["anomaly"],
        "recovery": counts["recovery"],
        "no_data": counts["no_data"],
        "per_day": per_day,
        "last_ts": last_anom_ms,
    }

    incidents_dir = project_root / "incidents" / name
    labels_path = newest_labels_file(incidents_dir)
    if labels_path is not None:
        labels = parse_labels_file(labels_path, interval_seconds=interval_seconds, metric_name=name)
        try:
            labels_rel = str(labels_path.relative_to(project_root))
        except ValueError:
            labels_rel = str(labels_path)
        row["quality"] = _compute_quality(
            labels,
            anomaly_events,
            start_ms=_ms(start),
            end_ms=end_ms,
            labels_rel_path=labels_rel,
        )

    row["spark"] = _spark_series(ts_arr, val_arr)
    row["spark_anoms"] = _downsample_evenly(sorted(anomalous_timestamps), _MAX_SPARK_ANOMS)


def resolve_project_budget(project_config: ProjectConfig) -> float:
    """The project-level ``false_alert_budget`` fallback (metric overrides it)."""
    if project_config.false_alert_budget is not None:
        return project_config.false_alert_budget
    return DEFAULT_FALSE_ALERT_BUDGET


def build_metric_row(
    *,
    project_config: ProjectConfig,
    project_root: Path,
    metric_path: Path,
    config: MetricConfig,
    internal: InternalTablesManager,
    window_preset: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One metric's overview row — the unit ``GET /api/stats/<name>`` serves.

    The cockpit fetches rows one metric at a time (bounded, seconds each)
    instead of one monolithic all-metrics payload: on a production-sized
    project the combined read (full detections of every metric × the window,
    serialized on the single DB connection) takes minutes — long enough for
    the browser to abort the request as failed while the page shows an
    endless spinner. Raises ``ValueError`` for an unknown *window_preset*.
    """
    if window_preset not in ALL_WINDOW_PRESETS:
        allowed = ", ".join(sorted(ALL_WINDOW_PRESETS))
        raise ValueError(f"Unknown window preset {window_preset!r}. Choose one of: {allowed}.")
    return _build_metric_row(
        project_root=project_root,
        metrics_dir=project_root / "metrics",
        metric_path=metric_path,
        config=config,
        internal=internal,
        window_preset=window_preset,
        now=now if now is not None else now_utc_naive(),
        project_name=project_config.name,
        project_budget=resolve_project_budget(project_config),
    )


def _build_metric_row(
    *,
    project_root: Path,
    metrics_dir: Path,
    metric_path: Path,
    config: MetricConfig,
    internal: InternalTablesManager,
    window_preset: str,
    now: datetime,
    project_name: str | None,
    project_budget: float,
) -> dict[str, Any]:
    """Build one metric's overview row; any failure is captured into ``error``."""
    row = _empty_row(config.name)
    try:
        _fill_config_fields(
            row,
            project_root=project_root,
            metrics_dir=metrics_dir,
            metric_path=metric_path,
            config=config,
            project_budget=project_budget,
        )
        _fill_stats(
            row,
            config=config,
            internal=internal,
            window_preset=window_preset,
            now=now,
            project_root=project_root,
            project_name=project_name,
        )
    except Exception as exc:  # noqa: BLE001 — one bad metric must not sink the payload
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def build_overview_payload(
    *,
    project_config: ProjectConfig,
    project_root: Path,
    metrics: list[tuple[Path, MetricConfig]],
    internal: InternalTablesManager,
    window_preset: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the ``GET /api/overview`` payload for the selected *metrics*.

    Raises ``ValueError`` for an unknown *window_preset* (validated once, up
    front — a per-metric error would be misleading for a request-level
    mistake). Every other failure is per-metric (see :func:`_build_metric_row`).
    """
    if window_preset not in ALL_WINDOW_PRESETS:
        allowed = ", ".join(sorted(ALL_WINDOW_PRESETS))
        raise ValueError(f"Unknown window preset {window_preset!r}. Choose one of: {allowed}.")

    now_dt = now if now is not None else now_utc_naive()
    metrics_dir = project_root / "metrics"
    project_budget = resolve_project_budget(project_config)

    rows = [
        _build_metric_row(
            project_root=project_root,
            metrics_dir=metrics_dir,
            metric_path=metric_path,
            config=config,
            internal=internal,
            window_preset=window_preset,
            now=now_dt,
            project_name=project_config.name,
            project_budget=project_budget,
        )
        for metric_path, config in metrics
    ]

    now_ms = _ms(now_dt)
    return {
        "project": project_config.name,
        "window": {"preset": window_preset, "days": WINDOW_PRESETS.get(window_preset)},
        "generated_at": now_ms,
        "now": now_ms,
        "metrics": rows,
    }
