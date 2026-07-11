# detectkit — Metric configuration (`metrics/*.yml`)

One YAML file per metric. Files may be nested under `metrics/`. The metric is
identified by its `name` field (unique across the project), not the filename —
keep them in sync. Detectors are covered in `detectors.md`, alerting in
`alerting.md`.

## Anatomy

```yaml
name: api_response_time        # required, unique across the project
description: API p95 latency   # optional, shown in alerts
profile: prod                  # optional, overrides project default_profile
enabled: true                  # optional, false → skipped by `dtk run`
tags: [critical, api]          # optional, used by `--select tag:<t>`
ai_context:                    # optional — OSI-compatible grounding (descriptive only)
  instructions: "p95 API latency, ms; user-facing"
  synonyms: ["api latency", "response time"]

interval: 5min                 # required — point spacing on the time grid

# --- data source: exactly one of query / query_file ---
query: |
  SELECT
    timestamp,
    AVG(response_time_ms) AS value
  FROM api_logs
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp <  '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp
# query_file: sql/api_response_time.sql   # alternative (path under sql_dir)

query_columns:                 # optional — map query columns to internal names
  timestamp: timestamp         # default: "timestamp"
  metric: value                # default: "value"
  seasonality: [hour_of_day]   # optional — query-provided seasonality columns

loading_start_time: "2024-01-01 00:00:00"   # optional — initial load start (UTC)
loading_batch_size: 2160       # optional — points per load batch
loading_delay: "10min"         # optional — data-maturity delay (see below)

seasonality_columns: [hour, day_of_week]    # optional — auto-extracted features

detectors:                     # required — see detectors.md
  - type: mad
    params:
      threshold: 3.0
      window_size: 288

alerting:                      # optional — see alerting.md
  enabled: true
  channels: [mattermost_ops]
  consecutive_anomalies: 3
  alert_cooldown: "30min"
  dashboard_url: https://grafana.ops/d/api-errors   # optional; clickable in every alert

tables:                        # optional — per-metric internal table overrides
  datapoints: _dtk_datapoints_api
  detections: _dtk_detections_api

false_alert_budget: 0.3        # optional — `dtk tune` target false-alert rate (0,1]; overrides project
```

`false_alert_budget` is a per-metric **target false-alert rate** (a fraction in
`(0, 1]`) the `dtk tune` cockpit gently flags when exceeded. It overrides the
project-wide default; unset → project, then a built-in `0.5`. Tuning-only — it never
affects the load/detect/alert pipeline.

`ai_context` is **OSI-compatible grounding** you can add to any metric with **no
OSI model needed** — the metric's business meaning (`instructions`), alternative
names (`synonyms`) and example values (`examples`), mirroring the
[Open Semantic Interchange](https://github.com/open-semantic-interchange/OSI)
`ai_context` shape so a metric's meaning is portable to/from an OSI semantic model.
Accepts a bare string (→ `instructions`) or the full mapping. It is **purely
descriptive**: it never affects load/detect/alert or the detector id, and it does
**not** change any default-rendered alert. The `synonyms` are exposed to alert
templates as the **opt-in** `{synonyms}` / `{synonyms_line}` variables (a custom
`template` can add an "Also known as: …" line), and the whole block is carried in
the `dtk tune` cockpit payload as read-only grounding. Omit it and everything
renders as before.

## `interval` (required)

Point spacing. String (`"30s"`, `"1min"`, `"5min"`, `"10min"`, `"1hour"`,
`"2hours"`, `"1day"`, `"7days"`) or integer seconds (`60`, `600`, `3600`). The
load step gap-fills this grid; the alert step's "consecutive" logic uses it for
grid adjacency.

## Query and template variables

Provide **either** `query` (inline) **or** `query_file` (path under `sql_dir`),
never both. detectkit renders these Jinja2 variables per load batch:

- `{{ dtk_start_time }}` — batch start, inclusive, `'YYYY-MM-DD HH:MM:SS'`.
- `{{ dtk_end_time }}` — batch end, exclusive, same format.
- `{{ interval_seconds }}` — the interval in seconds.

**The query MUST constrain its time range** with
`timestamp >= '{{ dtk_start_time }}' AND timestamp < '{{ dtk_end_time }}'` —
otherwise incremental and batched loading break. The rendered values are plain
datetime strings, so quote them in SQL.

The query must return a **timestamp** column and a numeric **value** column
(default names `timestamp` / `value`; remap via `query_columns`). It may also
return seasonality columns (declare them in `query_columns.seasonality`).

## Seasonality features

Two ways to provide seasonality keys that detectors group by:

1. **Auto-extracted** from the timestamp via `seasonality_columns`. Allowed
   built-in names: `hour` (0–23), `day_of_week` (0=Mon…6=Sun), `day_of_month`
   (1–31), `month` (1–12), `is_weekend`, `is_holiday` (always false — no
   calendar yet).
2. **Query-provided** custom columns (e.g. `hour_of_day`), declared in
   `query_columns.seasonality`. These take precedence over `seasonality_columns`.

A detector references these names in `seasonality_components` (see
`detectors.md`). Built-in `seasonality_columns` only accepts the names above;
custom names must come from the query. `dtk autotune` searches subsets of these
columns and bakes the best grouping into the tuned config (see `autotune.md`).

## Initial load and batching

- `loading_start_time` (UTC `"YYYY-MM-DD HH:MM:SS"`) sets where the **first**
  load begins, used only when the metric has no datapoints yet. If it is unset
  **and** no `--from` is passed, the initial load errors — detectkit will not
  guess where your data starts. Once data exists, runs resume from the last
  saved timestamp and this is ignored.
- `loading_batch_size` is the number of points loaded per batch (rule of thumb:
  7–30 days of points). E.g. 10-min interval → `2160` ≈ 15 days.
- `loading_delay` (duration string or seconds) withholds the newest interval
  until `now >= interval_end + loading_delay`, so a source that finishes
  writing *after* the interval closes (a dbt model, say) never gets a
  partial bucket persisted forever (load only resumes forward). The no-data
  alert expectation shifts back in lockstep. Resolves **metric → project →
  0** (`project.md`); `loading_delay: 0` on the metric opts out of a
  project-wide default. Only affects the implicit "now" bound — an explicit
  `--to` bypasses it. Trade-off: every second of delay adds the same to
  real-outage detection time, and it reduces but doesn't eliminate the race
  (repair a bucket that slipped through with `dtk run --from <date>`).

## Editing a metric that already has data

- **Changing the `query`** changes what's loaded but not the stored history;
  use `dtk run --select <m> --full-refresh` to reload.
- **Changing a detector parameter** (or `seasonality_components`) creates a new
  `detector_id` and recomputes that detector's detections; the old rows are
  orphaned in `_dtk_detections`. **Changing/removing an alerting block** orphans
  its `_dtk_alert_states` row. Prune both with `dtk clean --select <m>`
  (preview, then `--execute`) — or, from `dtk ui`, the metric's detail view's
  **Clean stale** button.
- **Renaming/deleting a metric** orphans all its rows under the old name; purge
  with `dtk clean --orphaned-metrics`.
- Datapoints are keyed only by `(metric, timestamp)` — a parameter edit never
  orphans them.

## Per-metric table overrides

`tables.datapoints` / `tables.detections` can point a metric at dedicated tables
(e.g. to isolate a critical metric or apply different retention). The `tasks`
table is shared and cannot be overridden.

## Minimal valid example

```yaml
name: api_errors
interval: 1min
query: |
  SELECT timestamp, error_count AS value
  FROM logs
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp <  '{{ dtk_end_time }}'
  ORDER BY timestamp
detectors:
  - type: manual_bounds
    params:
      upper_bound: 10
alerting:
  enabled: true
  channels: [slack_critical]
  consecutive_anomalies: 1
```
