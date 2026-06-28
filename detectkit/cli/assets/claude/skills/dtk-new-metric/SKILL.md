---
name: dtk-new-metric
description: >-
  Scaffold a new detectkit metric as a validated YAML file under metrics/. Use
  when the user wants to add or create a detectkit metric, monitor a new query
  or table, or set up anomaly detection / alerting on a time series. Produces a
  metrics/<name>.yml that passes config validation and is ready to run with dtk.
---

# Create a new detectkit metric

Scaffold one metric YAML that **validates and is ready to run**. Work through
the steps in order. Do not invent SQL or channel names — gather them. When you
need detail on any field, read the matching file under
`.claude/rules/detectkit/` (`metrics.md`, `detectors.md`, `alerting.md`,
`project.md`); this skill is the procedure, those are the reference.

## Step 0 — Confirm you're in a detectkit project

A project root contains `detectkit_project.yml`. Verify it exists in the target
directory (or find the nearest ancestor that has it). If there is none, stop and
tell the user to run `dtk init <name>` first, or ask which project directory to
use. Note the `paths.metrics_dir` (default `metrics/`) — that's where the file
goes.

If the project exists but `profiles.yml` hasn't been configured yet (still the
`dtk init` placeholder, or a run fails with `internal_database must be set`),
the database connection comes first — use the **`dtk-setup-project`** skill, then
come back here.

## Step 1 — Name and file path

- Ask for / confirm the metric `name`: lowercase snake_case, descriptive
  (`api_p95_latency_ms`, not `metric1`).
- The file is `<metrics_dir>/<name>.yml`. Keep filename == `name`.
- **Uniqueness is mandatory**: `name` must not collide with any existing metric
  in the project (it is the database key). Grep the metrics dir for
  `name: <name>` and abort on a clash, suggesting a more specific name.

## Step 2 — Data source (the query)

Never fabricate SQL. Get from the user the table, the value expression, and the
timestamp column (or a full query). Then assemble a query that:

- returns a `timestamp` column and a numeric `value` column (or set
  `query_columns` to map other names);
- **always** filters the time range with
  `WHERE timestamp >= '{{ dtk_start_time }}' AND timestamp < '{{ dtk_end_time }}'`
  (this is required for incremental loading — quote the rendered datetimes);
- is `ORDER BY timestamp`.

Use `{{ interval_seconds }}` if you need to bucket
(`toStartOfInterval(ts, INTERVAL {{ interval_seconds }} SECOND)` on ClickHouse).
For long/complex SQL, offer to put it in `sql/<name>.sql` and use `query_file:`
instead of inline `query:`.

## Step 3 — Interval

Ask for the point spacing and set `interval` (`"1min"`, `"5min"`, `"10min"`,
`"1hour"`, `"1day"`, or integer seconds). This must match how the query buckets
time.

## Step 4 — Detector(s)

Pick with the user (see `detectors.md` for the decision table):

- **Known hard bound / SLA** → `manual_bounds` (`upper_bound` and/or
  `lower_bound`). Instant, no history needed.
- **Seasonal** (hour-of-day / day-of-week patterns) → `mad` with
  `seasonality_components` and a window covering several cycles; add
  `seasonality_columns` to the metric for the features.
- **Clean & normally distributed** → `zscore`. **Skewed / percentiles** → `iqr`.
- **Unsure** → `mad` (robust default), `threshold: 3.0`.

If you don't yet know the right detector or parameters, scaffold a robust starter
(`mad`, `threshold: 3.0`) — treat it as a **sandbox** the user will refine on the
real series after this metric loads. Two complementary ways to refine it (Step 7):
the **`dtk-tune`** skill opens an interactive browser cockpit where they turn the
knobs by hand and watch the band recompute live (with autotune built in), or the
**`dtk-autotune`** skill searches for the best detector/params automatically. You
don't need the perfect detector now — a sound starter is enough to open the cockpit.

Set `window_size` to fit the data cadence (non-seasonal 100–500 points; seasonal
several full cycles) and `min_samples` ≈ 10–30% of it. For a metric with a
gradual trend, add `window_weights: exponential` + `half_life` (and optionally
`detrend: linear`) to avoid trend-induced false alerts. Combine a hard
`manual_bounds` cap with a statistical detector when both matter.

## Step 5 — Alerting

If the user wants notifications:

- Set `channels:` to names that **exist in `profiles.yml`** under
  `alert_channels`. Check them; if none exist, scaffold the alerting block but
  warn that a channel must be added (point to `project.md`).
- Set `direction` by meaning (`"up"` for high-is-bad like errors/CPU, `"down"`
  for low-is-bad like uptime, `"any"` for single-detector, `"same"` for
  multi-detector consensus).
- Set `consecutive_anomalies` (1 critical / 3 balanced / 5+ noisy) and
  `min_detectors` (1, or N to require agreement).
- **Always set `alert_cooldown`** (e.g. `"30min"`) — the default `null`
  re-alerts on every run. Consider `notify_on_recovery: true` for important
  metrics and `no_data_alert: true` for cron-fed metrics where absence is a
  failure.
- Add `dashboard_url:` (and optional `links:`) if there's a dashboard/runbook —
  it becomes a first-class "Open dashboard" action on every channel.

If the user doesn't want alerts yet, omit the `alerting` block (the metric still
loads and detects).

## Step 6 — Write the file

Write `<metrics_dir>/<name>.yml` with the assembled config. Keep comments
explaining any non-obvious choice. A typical result:

```yaml
name: api_error_rate
description: API 5xx error rate (%)
interval: "5min"

query: |
  SELECT
    toStartOfInterval(timestamp, INTERVAL {{ interval_seconds }} SECOND) AS timestamp,
    countIf(status_code >= 500) / count() * 100 AS value
  FROM http_requests
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp <  '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 2016        # 7 days of 5-min points
      window_weights: exponential
      half_life: "1d"

alerting:
  enabled: true
  channels: [mattermost_ops]
  direction: "up"
  consecutive_anomalies: 3
  alert_cooldown: "30min"
  dashboard_url: https://grafana.ops/d/api-errors   # optional "Open dashboard" action
```

## Step 7 — Validate before declaring done

Re-check every item; fix any failure before finishing:

- [ ] `name` is unique across the project and matches the filename.
- [ ] Exactly one of `query` / `query_file` is set.
- [ ] The query filters on `{{ dtk_start_time }}` **and** `{{ dtk_end_time }}`,
      and returns `timestamp` + numeric `value` (or `query_columns` maps them).
- [ ] `interval` is set and matches the query bucketing.
- [ ] At least one detector with valid params; any `seasonality_components`
      reference features the metric actually provides.
- [ ] If `alerting` is present: every channel exists in `profiles.yml`,
      `direction` matches intent, and `alert_cooldown` is set.

Then offer to verify against the real database (non-destructive):

```bash
dtk run --select <name> --steps load     # confirm the query returns data
dtk run --select <name> --steps detect    # confirm the detector runs
dtk test-alert <name>                      # confirm channels work (if alerting)
```

Report the created file path and the commands to run it for real. Then offer to
**refine the starter on the real series** — the metric so far is a sandbox, and
this is where most of the value is. Pick the path with the user:

- **Hands-on / "let me see and turn the knobs"** → the **`dtk-tune`** skill: it
  loads some history and opens an interactive browser cockpit where they adjust
  the detector live and **Apply** the result back. Its **Autotune** mode runs the
  automatic search *in place* too, so this one path covers both styles — prefer it
  whenever the user wants to be in the loop.
- **Fully automatic / "just pick one for me"** → the **`dtk-autotune`** skill: a
  cross-validated command-line search that writes an annotated tuned config
  (optionally against incidents you label first).

If they're happy with the robust starter for now, they can just run it and tune later.
