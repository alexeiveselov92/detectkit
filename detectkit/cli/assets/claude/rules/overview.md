# detectkit — Overview

detectkit is a Python library and CLI (`dtk`) for monitoring time-series
metrics with automatic anomaly detection and multi-channel alerting. It is
**dbt-like**: metrics live as YAML + SQL in a project directory, and you run
them with one command. Core logic is pure numpy (no pandas). **ClickHouse,
PostgreSQL and MySQL are all fully supported** — only the connection and the SQL
dialect of your metric queries differ between them.

## The pipeline: load → detect → alert

Every `dtk run` executes up to three steps per metric:

1. **load** — runs the metric's SQL query against the source database, fills
   gaps on the metric's time grid (missing intervals become `NaN`, never `0`),
   and stores the points in the `_dtk_datapoints` table.
2. **detect** — runs each configured detector over a trailing window, producing
   per-point detection rows (value, confidence interval, `is_anomaly`,
   severity, metadata) into `_dtk_detections`.
3. **alert** — evaluates the alerting rule over the most recent detections and
   sends notifications through the configured channels; alert state
   (cooldown/recovery) lives in `_dtk_alert_states`.

Run a subset with `--steps` (e.g. `--steps load,detect`).

## Idempotency

The pipeline is **resumable and idempotent**. Both load and detect resume from
the last saved timestamp (not from a task table), so re-running never
duplicates work or data. A normal cron loop just keeps calling
`dtk run --select "*"`; each run processes only what is new. Use
`--full-refresh` or `--from DATE` to deliberately reprocess history.

## Project layout

```
my_project/
├── detectkit_project.yml   # project config (paths, default profile, tables, error alerting)
├── profiles.yml            # database connections + alert channels
├── metrics/                # one YAML per metric (metrics/*.yml, may be nested)
│   └── api_errors.yml
├── sql/                    # optional external SQL files (query_file:)
└── templates/              # optional custom alert message templates (.j2)
```

A directory is a detectkit project when it has a `detectkit_project.yml`. A
single working folder can hold several projects side by side.

## Internal tables (`_dtk_*`)

Created automatically on first run (no manual migration). Names are
configurable per project/metric.

| Table | Holds |
|---|---|
| `_dtk_datapoints` | Loaded metric points (keyed by `metric_name`, `timestamp`) |
| `_dtk_detections` | Per-point detection results (keyed also by `detector_id`) |
| `_dtk_alert_states` | Cooldown/recovery state (keyed by metric + alert config block) |
| `_dtk_tasks` | Pipeline run/lock bookkeeping |

Profiles place these in a dedicated `internal_database` / `internal_schema`,
separate from the `data_database` your queries read from.

## Detectors at a glance

- `mad` — median absolute deviation; robust default; threshold is σ-equivalent
  (MAD is scaled by 1.4826).
- `zscore` — mean/std; for clean, normally distributed data.
- `iqr` — interquartile range; for skewed distributions / percentile metrics.
- `manual_bounds` — fixed upper/lower thresholds (SLAs); no window, instant.
- `autoreg` — prediction-based AR(p) on a trailing window; for fast-moving,
  non-seasonal metrics and shape anomalies; stabilization on by default.

`mad`, `zscore`, `iqr` share one windowed implementation, so they accept an
identical parameter set (window, seasonality grouping, preprocessing, recency
weighting, detrending). See `detectors.md`.

## Alerting model (alert-centric)

An **alert** is the primary entity; a detector anomaly is secondary evidence
that a rule interprets. The rule is a per-point **quorum** (`min_detectors`
detectors agreeing under a `direction` policy) that must hold for
`consecutive_anomalies` grid-adjacent points — or, optionally, for a share of
a trailing window (`anomaly_window` + `min_anomaly_share`, OR-ed with the
consecutive rule). Notifications lead with the alert
and the rule it fired on, with the anomaly shown as evidence. See
`alerting.md`.

## Seeing results — HTML reports

Beyond alerts, `dtk run --select <m> --report` (and `dtk autotune --report`)
writes a **self-contained HTML report**: the metric's values, each detector's
confidence band, flagged anomalies, and the alerts/recoveries/no-data it fired,
over a selectable period — so you can see how a metric behaved without standing
up BI or a SQL dashboard. Offline, nothing leaves the browser. Bare `--report`
writes `reports/<metric>.html`; pass a directory or a `.html` path to override.
See `cli.md`.

The report is read-only. To **change** the detector — turn its knobs on the real
series, watch the band recompute live, then write the config back into the metric
— use `dtk tune --select <m>`, the interactive sibling of `dtk autotune`
(`cli.md`).

For a **live**, project-wide view instead of a one-off file, run `dtk ui`: the
same reports in a browser overlay plus an overview table (alert frequency,
freshness — netting out any configured `loading_delay` so a deliberately
delayed metric doesn't read as stale — quality when incidents are labeled), a
panel that drives `dtk run` / `dtk autotune` / `dtk unlock`, and an in-browser
editor to create, edit and delete metric YAML files — a structured **Builder**
form (with OSI import and a post-create load-then-tune flow) next to a raw
**YAML** tab. See `cli.md`.

## Glossary

- **metric** — a named time series (SQL + interval) you monitor.
- **interval** — the spacing of points on the metric's time grid (`"10min"`,
  `3600`, …).
- **detector** — an algorithm that flags points as anomalous; identified by a
  hash of its parameters (`detector_id`).
- **window** — the trailing points a windowed detector uses to compute its
  expected range for the current point (current point excluded).
- **seasonality components** — grouping keys (e.g. `hour`) so statistics are
  computed within comparable time-of-day/day-of-week buckets.
- **quorum / consecutive / direction** — the alerting rule (see `alerting.md`).
- **cooldown / recovery / no-data** — alert-rate controls and special alert
  kinds (see `alerting.md`).

## Authoritative sources

The detectkit docs at <https://dtk.pipelab.dev> and the project changelog are authoritative for
behavior. These rule files summarize them for the installed version.
