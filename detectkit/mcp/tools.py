"""The 10 read-only MCP tool implementations.

Every function here is a **pure-given-a-context** call: it takes the
long-lived :class:`~detectkit.mcp.context.McpContext` plus its own arguments
and returns a JSON-serializable ``dict`` (every timestamp an ISO-8601 UTC
string, every number a plain ``float``/``int``/``None`` — see
:mod:`detectkit.mcp.serialize`). None of them import the ``mcp`` SDK; they are
plain functions so they can be unit-tested directly, with no protocol/server
machinery involved. :mod:`detectkit.mcp.server` wraps each one with a thin
``@mcp_server.tool()``-decorated closure that carries the user-facing
docstring (the actual tool description an MCP client sees).

**Session scope.** Every tool that names a metric goes through
``ctx.require_metric`` — a name outside the server's startup ``--select``
selector is refused, not silently substituted or widened. ``list_metrics`` /
``get_project_status`` intersect their own selector with that same scope.

**Excluded by design** (this module contains zero write paths): applying a
tuned config, the ``dtk ui`` metric-file CRUD, job/subprocess spawning,
writing incident labels, any ``save_*``/``delete_*`` call, and
``ensure_tables()``. Nothing here touches the filesystem for writing or the
database for anything but ``SELECT``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np

from detectkit import __version__
from detectkit.autotune.labels import incidents_to_display, newest_labels_file, parse_labels_file
from detectkit.cli.commands.run import select_metrics
from detectkit.config.metric_config import resolve_loading_delay_seconds, resolve_source_profile
from detectkit.mcp.context import McpContext
from detectkit.mcp.errors import McpProjectError
from detectkit.mcp.serialize import clamp_limit, ms_to_iso, num_or_none, parse_iso, to_iso
from detectkit.reporting.builder import _ms, record_from_row, replay_alert_events, resolve_window
from detectkit.ui.overview import (
    ALL_WINDOW_PRESETS,
    _alert_rule_summary,
    build_metric_row,
    resolve_metric_location,
)
from detectkit.utils.json_utils import json_loads

_DATAPOINTS_DEFAULT_LIMIT = 1000
_DATAPOINTS_HARD_CAP = 5000
_DETECTIONS_DEFAULT_LIMIT = 1000
_DETECTIONS_HARD_CAP = 5000
_PROJECT_STATUS_DEFAULT_LIMIT = 50
_PROJECT_STATUS_HARD_CAP = 200
_AUTOTUNE_DEFAULT_LIMIT = 5
_AUTOTUNE_HARD_CAP = 50


def _safe_json(value: Any) -> Any:
    """Parse a stored JSON-string column, or ``None`` on absence/corruption."""
    if value is None:
        return None
    try:
        return json_loads(value)
    except (ValueError, TypeError):
        return None


def _require_window(window: str) -> None:
    if window not in ALL_WINDOW_PRESETS:
        allowed = ", ".join(sorted(ALL_WINDOW_PRESETS))
        raise McpProjectError(f"Unknown window {window!r}. Choose one of: {allowed}.")


def _status_row_public(row: dict[str, Any]) -> dict[str, Any]:
    """Project a ``build_metric_row`` row to the tool contract (ms-epoch -> ISO strings)."""
    out = dict(row)
    out["last_point"] = ms_to_iso(row.get("last_point"))
    out["first_point_in_window"] = ms_to_iso(row.get("first_point_in_window"))
    alerts = dict(row.get("alerts") or {})
    alerts["last_ts"] = ms_to_iso(alerts.get("last_ts"))
    out["alerts"] = alerts
    out["spark"] = [[ms_to_iso(t), v] for t, v in (row.get("spark") or [])]
    out["spark_anoms"] = [ms_to_iso(t) for t in (row.get("spark_anoms") or [])]
    return out


# ---------------------------------------------------------------------------
# 1. list_metrics
# ---------------------------------------------------------------------------
def list_metrics(ctx: McpContext, selector: str = "*") -> dict[str, Any]:
    try:
        matched = select_metrics(selector, ctx.project_root)
    except ValueError as exc:
        raise McpProjectError(f"Error in selector {selector!r}: {exc}") from exc

    metrics_dir = ctx.project_root / "metrics"
    rows: list[dict[str, Any]] = []
    for path, config in matched:
        if config.name not in ctx.metric_names:
            continue  # outside this server's --select session scope
        dir_str, file_str = resolve_metric_location(path, ctx.project_root, metrics_dir)
        rows.append(
            {
                "name": config.name,
                "dir": dir_str,
                "file": file_str,
                "tags": list(config.tags) if config.tags else [],
                "enabled": config.enabled,
                "interval_seconds": config.get_interval().seconds,
                "detector_types": [d.type for d in config.detectors],
                "alert_summary": _alert_rule_summary(config.alerting),
            }
        )
    rows.sort(key=lambda r: str(r["name"]))
    return {
        "selector": selector,
        "scope_selector": ctx.selector,
        "count": len(rows),
        "metrics": rows,
    }


# ---------------------------------------------------------------------------
# 2. get_metric
# ---------------------------------------------------------------------------
def get_metric(ctx: McpContext, name: str) -> dict[str, Any]:
    path, config = ctx.require_metric(name)

    sql_text: str | None
    sql_error: str | None
    try:
        sql_text = config.get_query_text(ctx.project_root)
        sql_error = None
    except Exception as exc:  # noqa: BLE001 - surfaced as a field, not a raised error
        sql_text = None
        sql_error = str(exc)

    try:
        file_rel = str(path.relative_to(ctx.project_root))
    except ValueError:
        file_rel = str(path)

    return {
        "name": config.name,
        "file": file_rel,
        "description": config.description,
        "enabled": config.enabled,
        "tags": list(config.tags) if config.tags else [],
        "interval_seconds": config.get_interval().seconds,
        "loading": {
            "loading_start_time": config.loading_start_time,
            "loading_batch_size": config.loading_batch_size,
            "loading_delay_seconds": resolve_loading_delay_seconds(
                config.loading_delay, ctx.project_config.loading_delay
            ),
            # Hybrid-mode source profile NAME only (never connection details —
            # those live in profiles.yml, which this tool never reads).
            "source_profile": resolve_source_profile(
                config.source_profile, ctx.project_config.source_profile
            ),
        },
        "seasonality_columns": list(config.seasonality_columns or []),
        "detectors": [{"type": d.type, "params": dict(d.params)} for d in config.detectors],
        # AlertConfig carries channel NAMES only (`channels: list[str]`) — the
        # actual channel configs/secrets live in profiles.yml's alert_channels,
        # which this tool never touches.
        "alerting": [a.model_dump(mode="json") for a in (config.alerting or [])],
        "ai_context": config.ai_context.model_dump() if config.ai_context else None,
        "false_alert_budget": config.false_alert_budget,
        "sql_source": "inline" if config.query is not None else "file",
        "query_file": str(config.query_file) if config.query_file else None,
        "sql": sql_text,
        "sql_error": sql_error,
    }


# ---------------------------------------------------------------------------
# 3. get_metric_status
# ---------------------------------------------------------------------------
def get_metric_status(ctx: McpContext, name: str, window: str = "7d") -> dict[str, Any]:
    path, config = ctx.require_metric(name)
    internal = ctx.require_internal()
    _require_window(window)
    with ctx.lock:
        row = build_metric_row(
            project_config=ctx.project_config,
            project_root=ctx.project_root,
            metric_path=path,
            config=config,
            internal=internal,
            window_preset=window,
        )
    return _status_row_public(row)


# ---------------------------------------------------------------------------
# 4. get_project_status
# ---------------------------------------------------------------------------
def get_project_status(
    ctx: McpContext, window: str = "7d", selector: str = "*", limit: int = 50
) -> dict[str, Any]:
    internal = ctx.require_internal()
    _require_window(window)
    try:
        matched = select_metrics(selector, ctx.project_root)
    except ValueError as exc:
        raise McpProjectError(f"Error in selector {selector!r}: {exc}") from exc

    in_scope = [(p, c) for p, c in matched if c.name in ctx.metric_names]
    in_scope.sort(key=lambda pc: pc[1].name)
    effective_limit = clamp_limit(
        limit, default=_PROJECT_STATUS_DEFAULT_LIMIT, hard_cap=_PROJECT_STATUS_HARD_CAP
    )

    rows: list[dict[str, Any]] = []
    with ctx.lock:
        for path, config in in_scope[:effective_limit]:
            row = build_metric_row(
                project_config=ctx.project_config,
                project_root=ctx.project_root,
                metric_path=path,
                config=config,
                internal=internal,
                window_preset=window,
            )
            rows.append(_status_row_public(row))

    return {
        "window": window,
        "selector": selector,
        "scope_selector": ctx.selector,
        "total_metrics": len(in_scope),
        "returned": len(rows),
        "metrics": rows,
    }


# ---------------------------------------------------------------------------
# 5. query_datapoints
# ---------------------------------------------------------------------------
def query_datapoints(
    ctx: McpContext,
    metric: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    _path, config = ctx.require_metric(metric)
    internal = ctx.require_internal()
    effective_limit = clamp_limit(
        limit, default=_DATAPOINTS_DEFAULT_LIMIT, hard_cap=_DATAPOINTS_HARD_CAP
    )
    interval_seconds = config.get_interval().seconds
    from_dt = parse_iso(from_ts) if from_ts else None
    to_dt = parse_iso(to_ts) if to_ts else None

    with ctx.lock:
        end = to_dt if to_dt is not None else internal.get_last_datapoint_timestamp(metric)
        if end is None:
            return {"metric": metric, "count": 0, "points": []}
        # FINDING C: clamp the fetch start to the newest `effective_limit`
        # grid points even when `from_ts` reaches further back — the result
        # is capped to the same newest `effective_limit` points below
        # regardless, so a wide `from_ts` would otherwise materialize a span
        # only to throw almost all of it away.
        window_start = end - timedelta(seconds=interval_seconds * effective_limit)
        start = max(from_dt, window_start) if from_dt is not None else window_start
        to_exclusive = end + timedelta(seconds=interval_seconds)
        dp = internal.load_datapoints(metric, start, to_exclusive)

    ts_arr = dp["timestamp"]
    val_arr = dp["value"]
    points = [
        {"timestamp": to_iso(ts_arr[i]), "value": num_or_none(val_arr[i])}
        for i in range(len(ts_arr))
    ]
    points.reverse()  # newest first
    points = points[:effective_limit]
    return {"metric": metric, "count": len(points), "points": points}


# ---------------------------------------------------------------------------
# 6. query_detections
# ---------------------------------------------------------------------------
def query_detections(
    ctx: McpContext,
    metric: str,
    detector_id: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    anomalies_only: bool = False,
    limit: int = 1000,
) -> dict[str, Any]:
    _path, config = ctx.require_metric(metric)
    internal = ctx.require_internal()
    effective_limit = clamp_limit(
        limit, default=_DETECTIONS_DEFAULT_LIMIT, hard_cap=_DETECTIONS_HARD_CAP
    )
    interval_seconds = config.get_interval().seconds
    from_dt = parse_iso(from_ts) if from_ts else None
    to_dt = parse_iso(to_ts) if to_ts else None

    with ctx.lock:
        end = to_dt if to_dt is not None else internal.get_last_datapoint_timestamp(metric)
        if end is None:
            return {"metric": metric, "detector_id": detector_id, "count": 0, "detections": []}
        # FINDING C: same clamp as query_datapoints, EXCEPT when
        # anomalies_only=True — there the post-filter can thin out the fetched
        # rows a lot, so clamping the fetch to the newest `effective_limit`
        # grid points first could silently miss anomalies further back that
        # a wide `from_ts` was deliberately asking for. Keep that one path's
        # fetch wide (see the tool docstring in server.py).
        window_start = end - timedelta(seconds=interval_seconds * effective_limit)
        if from_dt is None:
            start = window_start
        elif anomalies_only:
            start = from_dt
        else:
            start = max(from_dt, window_start)
        to_exclusive = end + timedelta(seconds=interval_seconds)
        rows = internal.load_detections(metric, detector_id, start, to_exclusive)

    if anomalies_only:
        rows = [r for r in rows if bool(r["is_anomaly"])]

    out = [
        {
            "timestamp": to_iso(r["timestamp"]),
            "detector_id": r["detector_id"],
            "detector_name": r["detector_name"],
            "is_anomaly": bool(r["is_anomaly"]),
            "value": num_or_none(r.get("value")),
            "processed_value": num_or_none(r.get("processed_value")),
            "confidence_lower": num_or_none(r.get("confidence_lower")),
            "confidence_upper": num_or_none(r.get("confidence_upper")),
        }
        for r in rows
    ]
    out.reverse()  # newest first
    out = out[:effective_limit]
    return {"metric": metric, "detector_id": detector_id, "count": len(out), "detections": out}


# ---------------------------------------------------------------------------
# 7. replay_alerts
# ---------------------------------------------------------------------------
def replay_alerts(
    ctx: McpContext,
    metric: str,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> dict[str, Any]:
    _path, config = ctx.require_metric(metric)
    internal = ctx.require_internal()
    interval_seconds = config.get_interval().seconds
    from_dt = parse_iso(from_ts) if from_ts else None
    to_dt = parse_iso(to_ts) if to_ts else None

    with ctx.lock:
        start, end = resolve_window(internal, metric, interval_seconds, from_dt, to_dt)
        if start is None or end is None:
            return {"metric": metric, "period": None, "count": 0, "events": []}
        to_exclusive = end + timedelta(seconds=interval_seconds)

        dp = internal.load_datapoints(metric, start, to_exclusive)
        ts_arr, val_arr = dp["timestamp"], dp["value"]
        value_at = {
            np.datetime64(ts, "ms"): num_or_none(v) for ts, v in zip(ts_arr, val_arr, strict=False)
        }

        end_ms = _ms(end)
        det_rows = internal.load_detections(metric, None, start, to_exclusive)
        det_rows = [r for r in det_rows if _ms(r["timestamp"]) <= end_ms]
        records = [record_from_row(r) for r in det_rows]

        loading_delay = resolve_loading_delay_seconds(
            config.loading_delay, ctx.project_config.loading_delay
        )
        pairs = replay_alert_events(
            config,
            internal,
            records,
            value_at,
            start,
            end,
            ctx.project_config.name,
            loading_delay_seconds=loading_delay,
        )

    events: list[dict[str, Any]] = []
    for config_id, event in sorted(pairs, key=lambda pair: _ms(pair[1].timestamp)):
        ad = event.alert_data
        events.append(
            {
                "kind": event.kind,  # "anomaly" | "recovery" | "no_data"
                "timestamp": to_iso(event.timestamp),
                "direction": ad.direction or "none",
                "value": num_or_none(ad.value),
                "confidence_lower": num_or_none(ad.confidence_lower),
                "confidence_upper": num_or_none(ad.confidence_upper),
                "severity": float(ad.severity or 0.0),
                "consecutive_count": int(ad.consecutive_count or 0),
                "detector_name": ad.detector_name,
                "onset": to_iso(ad.onset_timestamp) if ad.onset_timestamp is not None else None,
                "streak_capped": bool(ad.streak_capped),
                "alert_config_id": config_id,
            }
        )
    return {
        "metric": metric,
        "period": {"start": to_iso(start), "end": to_iso(end)},
        "count": len(events),
        "events": events,
    }


# ---------------------------------------------------------------------------
# 8. get_autotune_history
# ---------------------------------------------------------------------------
def get_autotune_history(
    ctx: McpContext, metric: str, limit: int = 5, include_decision_log: bool = False
) -> dict[str, Any]:
    ctx.require_metric(metric)
    internal = ctx.require_internal()
    effective_limit = clamp_limit(
        limit, default=_AUTOTUNE_DEFAULT_LIMIT, hard_cap=_AUTOTUNE_HARD_CAP
    )

    with ctx.lock:
        rows = internal.get_autotune_runs(metric)  # newest first already

    runs: list[dict[str, Any]] = []
    for r in rows[:effective_limit]:
        entry: dict[str, Any] = {
            "run_id": r.get("run_id"),
            "created_at": to_iso(r.get("created_at")),
            "status": r.get("status"),
            "mode": r.get("mode"),
            "scoring_metric": r.get("scoring_metric"),
            "score": num_or_none(r.get("score")),
            "training_period_start": to_iso(r.get("training_period_start")),
            "training_period_end": to_iso(r.get("training_period_end")),
            "chosen_detector_type": r.get("chosen_detector_type"),
            "chosen_detector_params": _safe_json(r.get("chosen_detector_params_json")),
            "chosen_seasonality": _safe_json(r.get("chosen_seasonality_json")),
            "winning_detector_id": r.get("winning_detector_id"),
            "error_message": r.get("error_message"),
        }
        if include_decision_log:
            entry["decision_log"] = _safe_json(r.get("decision_log_json"))
        runs.append(entry)
    return {"metric": metric, "count": len(runs), "runs": runs}


# ---------------------------------------------------------------------------
# 9. get_incidents
# ---------------------------------------------------------------------------
def get_incidents(ctx: McpContext, metric: str) -> dict[str, Any]:
    config = ctx.require_metric(metric)[1]
    incidents_dir = ctx.project_root / "incidents" / metric
    labels_path = newest_labels_file(incidents_dir)
    if labels_path is None:
        return {"metric": metric, "labels_file": None, "count": 0, "incidents": []}

    interval_seconds = config.get_interval().seconds
    try:
        labels = parse_labels_file(
            labels_path, interval_seconds=interval_seconds, metric_name=metric
        )
    except Exception as exc:
        raise McpProjectError(f"Could not parse labels file {labels_path}: {exc}") from exc

    try:
        labels_rel = str(labels_path.relative_to(ctx.project_root))
    except ValueError:
        labels_rel = str(labels_path)

    display = incidents_to_display(labels)
    return {
        "metric": metric,
        "labels_file": labels_rel,
        "count": len(display),
        "incidents": display,
    }


# ---------------------------------------------------------------------------
# 10. get_server_info
# ---------------------------------------------------------------------------
def get_server_info(ctx: McpContext) -> dict[str, Any]:
    profile = ctx.profiles_config.get_profile(ctx.profile_name)
    return {
        "detectkit_version": __version__,
        "project_name": ctx.project_config.name,
        "project_root": str(ctx.project_root),
        "profile_name": ctx.profile_name or ctx.profiles_config.default_profile,
        "backend_type": profile.type,
        "selector": ctx.selector,
        "metric_count": len(ctx.metric_names),
        "tables_ready": ctx.tables_ready,
        "read_only": True,
    }
