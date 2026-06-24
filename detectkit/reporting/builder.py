"""Assemble a report payload from the persisted internal tables.

Pure-ish: reads ``_dtk_datapoints`` / ``_dtk_detections`` through an
``InternalTablesManager`` and replays alerts in memory (no dispatch, no state
writes), returning the JSON-serializable payload the report renderer consumes
(contract: ``website/src/scripts/report/payload.ts``). The detector band series
is derived straight from the stored detection rows — the report shows *what
actually ran*, not what the current YAML would produce.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from detectkit.alerting.orchestrator import AlertOrchestrator
from detectkit.alerting.orchestrator._types import (
    AlertConditions,
    DetectionRecord,
    _direction_from_metadata,
    _parse_detection_metadata,
)
from detectkit.config.metric_config import MetricConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.orchestration.task_manager import make_alert_config_id
from detectkit.utils.datetime_utils import to_naive_utc
from detectkit.utils.json_utils import json_loads

# Default lookback when the caller does not pin a window: the most recent slice
# of history, capped so a baked report stays small and fast to open.
DEFAULT_REPORT_POINTS = 1500

# Detector defaults used to compute the "effective start" (first point past every
# warm-up). The stored detector_params JSON holds only NON-DEFAULT params, so we
# fill these before mirroring the TS effectiveStartIndex (detector.ts). Keep in
# lockstep with the detector classes' class-level defaults / floors.
_WINDOW_SIZE_DEFAULT = 100
_MIN_SAMPLES_DEFAULT = 30
_SMOOTHING_WINDOW_DEFAULT = 10
_SMOOTHING_ALPHA_DEFAULT = 0.3

# Per-detector-type floors / per-group defaults, keyed by the lowercase type.
_MIN_SAMPLES_FLOOR: dict[str, int] = {"mad": 1, "zscore": 2, "iqr": 4}
_MIN_SAMPLES_PER_GROUP_DEFAULT: dict[str, int] = {"mad": 10, "zscore": 3, "iqr": 4}


def _detector_type(detector_name: str) -> str:
    """Map a stored detector class name (e.g. ``MADDetector``) to its type key.

    Falls back to ``"mad"`` floors when the class is unrecognized (a foreign /
    future detector) so the warm-up estimate stays conservative rather than
    raising.
    """
    name = detector_name.lower()
    if name.startswith("zscore"):
        return "zscore"
    if name.startswith("iqr"):
        return "iqr"
    return "mad"


def _effective_start_index(
    *,
    detector_name: str,
    params: dict,
    seasonality_rows: list[dict],
    n_points: int,
) -> int:
    """Mirror ``effectiveStartIndex`` (website detector.ts) over the report window.

    ``seasonality_rows`` is the parsed ``seasonality_data`` for every datapoint in
    the report window (in grid order). Returns a warm-up point count clamped to
    ``[0, n_points]``; the timestamp at this index is the band's "full power"
    onset.
    """
    dtype = _detector_type(detector_name)
    window_size = int(params.get("window_size", _WINDOW_SIZE_DEFAULT) or _WINDOW_SIZE_DEFAULT)
    min_samples = int(params.get("min_samples", _MIN_SAMPLES_DEFAULT) or _MIN_SAMPLES_DEFAULT)
    min_samples_per_group = int(
        params.get("min_samples_per_group", _MIN_SAMPLES_PER_GROUP_DEFAULT[dtype])
        or _MIN_SAMPLES_PER_GROUP_DEFAULT[dtype]
    )
    smoothing = params.get("smoothing", "none") or "none"
    smoothing_window = int(
        params.get("smoothing_window", _SMOOTHING_WINDOW_DEFAULT) or _SMOOTHING_WINDOW_DEFAULT
    )
    smoothing_alpha = float(
        params.get("smoothing_alpha", _SMOOTHING_ALPHA_DEFAULT) or _SMOOTHING_ALPHA_DEFAULT
    )
    input_type = params.get("input_type", "values") or "values"
    seasonality_components = params.get("seasonality_components")

    warm = max(min_samples, _MIN_SAMPLES_FLOOR[dtype])
    if smoothing == "sma":
        warm = max(warm, smoothing_window - 1)
    elif smoothing == "ema":
        warm = max(warm, math.ceil(5.0 / smoothing_alpha))
    if input_type != "values":
        warm = max(warm, 1)

    groups = seasonality_components if isinstance(seasonality_components, list) else None
    if groups and seasonality_rows:
        # Cardinality = max distinct value-tuple count across the groupings.
        card = 0
        for group in groups:
            cols = group if isinstance(group, list) else [group]
            seen: set[tuple] = set()
            for row in seasonality_rows:
                seen.add(tuple(str((row or {}).get(c, "")) for c in cols))
            card = max(card, len(seen))
        if card > 0:
            group_warm = min_samples_per_group * card
            # Groups only engage if the window can hold enough same-key points;
            # otherwise the detector stays in global fallback the whole way.
            if window_size >= group_warm:
                warm = max(warm, group_warm)

    return min(warm, n_points)


def _ms(value: Any) -> int:
    """Coerce a datetime / datetime64 to integer ms-epoch (UTC)."""
    if isinstance(value, datetime):
        value = to_naive_utc(value)
    return int(np.datetime64(value, "ms").astype("int64"))


def _parse_seasonality(value: Any) -> dict:
    """Parse a stored ``seasonality_data`` cell (JSON string or dict) to a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json_loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _num_or_none(value: Any) -> float | None:
    """Pass a stored Nullable number through, mapping NaN/None to ``None``."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def resolve_window(
    internal: InternalTablesManager,
    metric_name: str,
    interval_seconds: int,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    """Fill in a default [start, end] window from the persisted datapoints.

    ``end`` defaults to the last datapoint; ``start`` defaults to
    ``DEFAULT_REPORT_POINTS`` intervals before it (clamped to the first
    datapoint). Returns ``(None, None)`` when the metric has no datapoints yet.
    """
    if end is None:
        end = internal.get_last_datapoint_timestamp(metric_name)
    if end is None:
        return None, None
    if start is None:
        first = internal.get_first_datapoint_timestamp(metric_name)
        lookback = end - timedelta(seconds=interval_seconds * DEFAULT_REPORT_POINTS)
        start = max(first, lookback) if first is not None else lookback
    return start, end


def _record_from_row(row: dict) -> DetectionRecord:
    """Build a :class:`DetectionRecord` from a flat ``load_detections`` row.

    Mirrors ``hydrate_detection_records`` (direction/severity derived from
    ``detection_metadata``) so replayed alerts match production exactly.
    """
    metadata = _parse_detection_metadata(row.get("detection_metadata"))
    is_anomaly = bool(row["is_anomaly"])
    try:
        severity = float(metadata.get("severity", 0.0) or 0.0)
    except (TypeError, ValueError):
        severity = 0.0
    value = _num_or_none(row.get("value"))
    return DetectionRecord(
        timestamp=np.datetime64(to_naive_utc(row["timestamp"]), "ms"),
        detector_name=row["detector_name"],
        detector_id=row["detector_id"],
        detector_params=row.get("detector_params") or "{}",
        value=float("nan") if value is None else value,
        is_anomaly=is_anomaly,
        confidence_lower=_num_or_none(row.get("confidence_lower")),
        confidence_upper=_num_or_none(row.get("confidence_upper")),
        direction=_direction_from_metadata(metadata, is_anomaly),
        severity=severity,
        detection_metadata=metadata,
    )


def _event_to_payload(event: Any, config_id: str) -> dict:
    """Project a ``ReplayedEvent`` into the payload alert shape."""
    ad = event.alert_data
    rule = (
        f"min_detectors={ad.min_detectors} · direction={ad.direction_policy} "
        f"· consecutive={ad.consecutive_required}"
    )
    return {
        "kind": event.kind,
        "t": _ms(event.timestamp),
        "onset": _ms(ad.onset_timestamp) if ad.onset_timestamp is not None else None,
        "consecutive": int(ad.consecutive_count or 0),
        "direction": ad.direction or "none",
        "severity": float(ad.severity or 0.0),
        "value": _num_or_none(ad.value),
        "detector": ad.detector_name,
        "rule": rule,
        "config_id": config_id,
    }


def build_report_payload(
    *,
    metric_config: MetricConfig,
    internal: InternalTablesManager,
    start: datetime | None = None,
    end: datetime | None = None,
    project_name: str | None = None,
    generated_at: str | None = None,
) -> dict:
    """Read the internal tables for one metric and assemble the report payload.

    ``start`` / ``end`` bound the report window (inclusive of both grid points);
    when omitted they default via :func:`resolve_window`.
    """
    name = metric_config.name
    interval = metric_config.get_interval()
    interval_seconds = interval.seconds

    start, end = resolve_window(internal, name, interval_seconds, start, end)
    empty: dict = {
        "metric": name,
        "project": project_name,
        "interval_seconds": interval_seconds,
        "period": {"start": 0, "end": 0},
        "generated_at": generated_at,
        "description": metric_config.description,
        "points": [],
        "detectors": [],
        "alerts": [],
        "summary": {"anomalies": 0, "alerts": 0, "recoveries": 0, "no_data": 0},
    }
    if start is None or end is None:
        return empty

    # Half-open readers: pull one extra step so the grid point at exactly `end`
    # is included, then clamp on `end` below.
    to_exclusive = end + timedelta(seconds=interval_seconds)

    # ---- value series ---------------------------------------------------------
    dp = internal.load_datapoints(name, start, to_exclusive)
    ts_arr = dp["timestamp"]
    val_arr = dp["value"]
    raw_seas = dp.get("seasonality_data")
    seas_arr: Any = raw_seas if raw_seas is not None else [None] * len(ts_arr)
    end_ms = _ms(end)
    points: list[dict] = []
    value_at: dict[np.datetime64, float | None] = {}
    # Parallel grid arrays restricted to the report window, in order — used to map
    # each detector's warm-up point count to a "full power" onset timestamp and to
    # measure seasonality cardinality over the actual report datapoints.
    grid_ms: list[int] = []
    seasonality_rows: list[dict] = []
    for ts, v, sd in zip(ts_arr, val_arr, seas_arr, strict=False):
        t_ms = _ms(ts)
        if t_ms > end_ms:
            continue
        fv = None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)
        points.append({"t": t_ms, "v": fv})
        value_at[np.datetime64(ts, "ms")] = fv
        grid_ms.append(t_ms)
        seasonality_rows.append(_parse_seasonality(sd))

    # ---- detector band series (grouped from the stored rows) ------------------
    det_rows = internal.load_detections(name, None, start, to_exclusive)
    det_rows = [r for r in det_rows if _ms(r["timestamp"]) <= end_ms]

    detectors: dict[str, dict] = {}
    anomalous_timestamps: set[int] = set()
    for row in det_rows:
        det_id = row["detector_id"]
        slot = detectors.get(det_id)
        if slot is None:
            try:
                params = json_loads(row.get("detector_params") or "{}")
            except (ValueError, TypeError):
                params = {}
            slot = {
                "id": det_id,
                "name": row["detector_name"],
                "params": params if isinstance(params, dict) else {},
                "points": [],
                "anomaly_count": 0,
                "effective_start": None,
            }
            detectors[det_id] = slot
        metadata = _parse_detection_metadata(row.get("detection_metadata"))
        is_anom = bool(row["is_anomaly"])
        t_ms = _ms(row["timestamp"])
        slot["points"].append(
            {
                "t": t_ms,
                "lo": _num_or_none(row.get("confidence_lower")),
                "hi": _num_or_none(row.get("confidence_upper")),
                "a": 1 if is_anom else 0,
                "sev": (_num_or_none(metadata.get("severity")) if is_anom else None),
                "dir": (metadata.get("direction") if is_anom else None),
            }
        )
        if is_anom:
            slot["anomaly_count"] += 1
            anomalous_timestamps.add(t_ms)

    # ---- effective-start onset (warm-up boundary) per detector ----------------
    # The band before this timestamp is a degraded lead-in (global fallback /
    # partial window); the renderer dims it. None means the whole window is past
    # warm-up — nothing to hide.
    n_grid = len(grid_ms)
    for slot in detectors.values():
        warm = _effective_start_index(
            detector_name=slot["name"],
            params=slot["params"],
            seasonality_rows=seasonality_rows,
            n_points=n_grid,
        )
        slot["effective_start"] = grid_ms[warm] if 0 < warm < n_grid else None

    # ---- alerts: replay every active alert config over the period -------------
    records = [_record_from_row(r) for r in det_rows]
    alerts: list[dict] = []
    active_configs = [c for c in (metric_config.alerting or []) if c.enabled and c.channels]
    for cfg in active_configs:
        config_id = make_alert_config_id(cfg)
        orchestrator = AlertOrchestrator(
            metric_name=name,
            interval=interval,
            alert_config_id=config_id,
            conditions=AlertConditions(
                min_detectors=cfg.min_detectors,
                direction=cfg.direction,
                consecutive_anomalies=cfg.consecutive_anomalies,
            ),
            timezone_display=cfg.timezone,
            internal=internal,
            alert_config=cfg,
            description=metric_config.description,
            mentions=cfg.mentions,
            dashboard_url=cfg.dashboard_url,
            links=cfg.links,
            project_name=project_name,
            help_url=None,
        )
        for event in orchestrator.replay(records, value_at, start, end):
            alerts.append(_event_to_payload(event, config_id))

    alerts.sort(key=lambda a: a["t"])
    summary = {
        "anomalies": len(anomalous_timestamps),
        "alerts": sum(1 for a in alerts if a["kind"] == "anomaly"),
        "recoveries": sum(1 for a in alerts if a["kind"] == "recovery"),
        "no_data": sum(1 for a in alerts if a["kind"] == "no_data"),
    }

    return {
        "metric": name,
        "project": project_name,
        "interval_seconds": interval_seconds,
        "period": {"start": _ms(start), "end": end_ms},
        "generated_at": generated_at,
        "description": metric_config.description,
        "points": points,
        "detectors": list(detectors.values()),
        "alerts": alerts,
        "summary": summary,
    }
