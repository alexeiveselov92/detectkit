# Visualizing Results

detectkit writes everything it computes into a handful of internal `_dtk_*`
tables in your database. There are two ways to see it:

- **HTML reports** — the quickest look. `dtk run --report` (or
  `dtk autotune --report`) writes a single self-contained HTML file per metric
  that you open in a browser — values, the detector's confidence band, anomalies,
  and the alerts that fired, with a built-in period selector. No BI tool, no SQL.
  See [HTML reports](#html-reports) below.
- **Your own BI / dashboarding tool** — for shared dashboards and custom panels,
  point **any** BI tool at the `_dtk_*` tables and chart them with plain SQL
  (Grafana, Apache Superset, Metabase, Tableau, Redash, Looker, …, or SQL
  notebooks and a psql/clickhouse-client session).

The BI recipes below are **tool-agnostic** copy-pasteable SQL for the charts
people most often want: the metric over time, the detector's confidence band,
anomaly markers, anomaly counts, the latest value vs its expected range, and
detector comparisons.

> **Want to change the detector, not just look at it?** The HTML report is
> read-only (it replays what already ran). To turn the detector's knobs on the
> real series and watch the band recompute live — then write the config back into
> the metric — use [`dtk tune`](tuning.md), the interactive sibling of
> `dtk autotune`.

> **Database note.** The examples use ClickHouse SQL, but detectkit runs on
> ClickHouse, PostgreSQL and MySQL — the `_dtk_*` tables exist on all three. The
> *shape* of every query is portable; only a few things are dialect-specific
> (date/time bucketing, interval literals, JSON extraction, and dedup: ClickHouse
> needs `FINAL` to collapse `ReplacingMergeTree` versions, while PostgreSQL/MySQL
> enforce the primary key so a plain `SELECT` is already deduplicated). Those
> spots are called out inline with a portable alternative.

## What's in the tables

Results live in the **`internal_database`** (or `internal_schema`) configured in
your profile — the same place the pipeline writes to, separate from the
`data_database` your metric queries read from. See the
[Profiles configuration](configuration-profiles.md) for where these live.

detectkit writes everything into the `_dtk_*` tables. The full column / primary
key / engine schema of all six lives in the
[Internal Tables reference](../reference/internal-tables.md); at a glance:

| Table | Holds |
|---|---|
| `_dtk_datapoints` | the loaded metric series — one row per point on the time grid |
| `_dtk_detections` | per-point detection results — one row per (metric, detector, timestamp) |
| `_dtk_tasks` | pipeline locks & resume cursors |
| `_dtk_alert_states` | per-alert-block cooldown / recovery bookkeeping |
| `_dtk_metrics` | a config mirror for dashboards (informational) |
| `_dtk_autotune_runs` | [`dtk autotune`](../reference/cli.md#dtk-autotune) audit trail |

The two you chart most are **`_dtk_datapoints`** (the series) and
**`_dtk_detections`** (the confidence band + anomaly flags) — the recipes below
use them. Always filter or group `_dtk_detections` by `detector_id`, since a
metric with two detectors writes two rows per timestamp (see
[Avoid mixing detectors](#joining-tables-and-avoiding-mixed-detectors)). The
`detection_metadata` JSON carries the per-point `severity` / `direction` /
`reason` detail — see
[Internal Tables → detection_metadata](../reference/internal-tables.md#the-detection_metadata-json)
and [Shared Detector Parameters](../reference/detectors/shared-parameters.md#debugging-preprocessed-detections).

## HTML reports

For a fast, no-setup look at how a metric actually behaved, generate a
**self-contained HTML report**. Pass `--report` to a run:

```bash
# After a normal run, write a report for the metric
dtk run --select cpu_usage --report

# A report for the detector dtk autotune just chose
dtk autotune --select cpu_usage --report
```

Each writes one HTML file you open in a browser. It shows, over a selectable
period:

- the **metric value** over time, with each detector's **confidence band**;
- the **anomalies** that were flagged;
- the **alerts** that fired — anomaly, recovery, and no-data — each listed with
  the rule that fired it, its severity, and how long it lasted;
- a short **summary** of the period.

Use the built-in **period selector** (24h / 7d / 30d / All, with zoom and pan) to
move around the history, and the **y = 0** toggle to draw a reference line at zero
and scale the chart to include it — handy for a real-valued metric best read
relative to zero. The report is **offline and self-contained**: the chart
and data are inlined into the single file, so nothing is fetched and nothing
leaves the page — you can email it or commit it as a snapshot.

The report is built from the data already in the `_dtk_*` tables, so even a
load-only run (`dtk run --select cpu_usage --steps load --report`) produces one
from whatever is stored.

**Where it lands.** `--report` is dual-mode:

| You pass | The report is written to |
|---|---|
| `--report` (bare) | `reports/<metric>.html` (autotune: `reports/<metric>__tuned_<id>.html`) |
| `--report <dir>` | `<dir>/<metric>.html` |
| `--report report.html` | that exact file |

For the precise flag behavior — and a note on how the report **reconstructs**
alerts from stored detections — see the
[CLI reference](../reference/cli.md#-report-optional-dual-mode).

## Connecting a BI tool

1. Add a database connection pointing at your **`internal_database`** (the
   ClickHouse database where the `_dtk_*` tables live).
2. Use a fully qualified table name if your tool's connection isn't already
   scoped to that database (e.g. `analytics._dtk_detections`).
3. Parameterize the metric (and detector, where relevant). Every recipe below
   uses a `:metric_name` placeholder — substitute your tool's variable syntax
   (Grafana `$metric_name`, Superset/Metabase template parameters, a Tableau
   parameter, or just a string literal).

### Time-range filtering is tool-specific

Each tool injects the dashboard's time range its own way. The recipes use a
neutral placeholder:

```sql
WHERE timestamp >= :from AND timestamp < :to
```

Substitute it with whatever your tool provides:

| Tool | Replace `timestamp >= :from AND timestamp < :to` with |
|---|---|
| Grafana | `$__timeFilter(timestamp)` |
| Superset | the native time-range control (or a `{{ from_dttm }}` / `{{ to_dttm }}` Jinja pair) |
| Metabase | a `{{created}}`-style Field Filter on `timestamp`, or a date range parameter |
| Redash / notebooks | a literal range, e.g. `timestamp >= now() - INTERVAL 24 HOUR` |

> **Dialect note.** `now() - INTERVAL 24 HOUR` is ClickHouse syntax. PostgreSQL
> uses `now() - INTERVAL '24 hours'`; standard SQL uses
> `CURRENT_TIMESTAMP - INTERVAL '24' HOUR`. Prefer the tool's time control so
> you don't hardcode this at all.

### Bucketing time

Several recipes aggregate into time buckets. ClickHouse has helpers like
`toStartOfMinute(timestamp)`, `toStartOfFiveMinutes(timestamp)`,
`toStartOfHour(timestamp)`, `toStartOfDay(timestamp)`. Portable equivalents:

- PostgreSQL: `date_trunc('hour', timestamp)`
- BigQuery: `TIMESTAMP_TRUNC(timestamp, HOUR)`
- Generic: `date_trunc('hour', timestamp)`

The recipes write `<time_bucket>(timestamp)` where you should drop in the bucket
function that matches your dialect and the resolution you want.

## Chart recipes

All recipes are parameterized by `:metric_name`, and by `:detector_id` where a
single detector must be isolated.

### 1. Metric value over time (line)

The raw metric, straight from `_dtk_datapoints`. `NULL` values are gaps — most
chart libraries render them as breaks in the line.

```sql
SELECT
  timestamp AS time,
  value
FROM _dtk_datapoints
WHERE metric_name = :metric_name
  AND timestamp >= :from AND timestamp < :to
ORDER BY timestamp
```

**Chart type:** time-series line. Map `time` to the X axis, `value` to Y.

### 2. Value with the detector's confidence band (line + band)

Everything needed for the "metric vs expected range" view comes from a single
detector's rows in `_dtk_detections`. Filter by `:detector_id` so you draw one
band, not an overlap of several.

```sql
SELECT
  timestamp AS time,
  value           AS "Value",
  confidence_lower AS "Lower bound",
  confidence_upper AS "Upper bound"
FROM _dtk_detections
WHERE metric_name = :metric_name
  AND detector_id = :detector_id
  AND timestamp >= :from AND timestamp < :to
ORDER BY timestamp
```

**Chart type:** time-series line. Render `Value` as a solid line and
`Lower bound` / `Upper bound` as a shaded band (fill between the two series).
The band widens/narrows with seasonality and recency weighting.

> Don't have a `detector_id` handy? List them per metric:
> ```sql
> SELECT detector_id, detector_name, count() AS rows, max(timestamp) AS last_seen
> FROM _dtk_detections
> WHERE metric_name = :metric_name
> GROUP BY detector_id, detector_name
> ORDER BY last_seen DESC
> ```
> Each distinct `detector_id` is one detector configuration; changing a
> detector's parameters creates a new id (see
> [Detector Identity](detectors.md#detector-identity-and-recomputation)).

### 3. Anomalies overlaid as markers

Plot only the anomalous points as a separate series on top of the value line.
Combine with recipe 2 in the same panel.

```sql
SELECT
  timestamp AS time,
  value     AS "Anomaly"
FROM _dtk_detections
WHERE metric_name = :metric_name
  AND detector_id = :detector_id
  AND is_anomaly = 1            -- 'true' is also accepted in ClickHouse
  AND timestamp >= :from AND timestamp < :to
ORDER BY timestamp
```

**Chart type:** points/markers (no line) layered over recipes 1 or 2. Color them
prominently (e.g. red, larger point size).

> `is_anomaly = 1` works in ClickHouse and most engines; if your dialect is
> strict about booleans, use `is_anomaly = true`.

### 4. Anomaly count over time (bar)

How many anomalies fired per time bucket. Drop the technical `reason` rows so
the count reflects real detections only.

```sql
SELECT
  <time_bucket>(timestamp) AS time,
  countIf(is_anomaly) AS anomalies     -- portable: SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END)
FROM _dtk_detections
WHERE metric_name = :metric_name
  AND detector_id = :detector_id
  AND timestamp >= :from AND timestamp < :to
  AND JSONExtractString(detection_metadata, 'reason') = ''   -- exclude missing/insufficient
GROUP BY time
ORDER BY time
```

**Chart type:** bar / histogram over time.

> **Dialect notes.**
> `countIf(cond)` is ClickHouse; the portable form is
> `SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END)`.
> `JSONExtractString(col, 'key')` is ClickHouse JSON extraction; PostgreSQL uses
> `detection_metadata::jsonb ->> 'reason'`, and other engines have their own
> JSON operators. When a key is absent, ClickHouse's `JSONExtractString` returns
> an empty string, which is exactly the "real, scored point" case we want to
> keep.

### 5. Latest value vs expected range (stat / gauge)

The most recent scored point for a detector: its value and current expected
band. Good for a single-number/stat panel with a colored threshold.

```sql
SELECT
  timestamp,
  value,
  confidence_lower,
  confidence_upper,
  is_anomaly,
  JSONExtractFloat(detection_metadata, 'severity') AS severity
FROM _dtk_detections
WHERE metric_name = :metric_name
  AND detector_id = :detector_id
ORDER BY timestamp DESC
LIMIT 1
```

**Chart type:** stat / single value (show `value`), optionally a gauge bounded
by `confidence_lower` / `confidence_upper`, colored by `is_anomaly` or
`severity`.

> On ClickHouse `ReplacingMergeTree`, add `FINAL` (`FROM _dtk_detections FINAL`)
> if a re-run could leave duplicate versions and you want the deduplicated row.

### 6. Comparing multiple detectors for one metric

When several detectors score the same metric, group by `detector_id` /
`detector_name` to see who flags what.

```sql
SELECT
  detector_name,
  detector_id,
  count()             AS scored_points,
  countIf(is_anomaly) AS anomalies,                                  -- portable: SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END)
  round(countIf(is_anomaly) / count() * 100, 2) AS anomaly_rate_pct
FROM _dtk_detections
WHERE metric_name = :metric_name
  AND timestamp >= :from AND timestamp < :to
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY detector_name, detector_id
ORDER BY anomaly_rate_pct DESC
```

**Chart type:** table (one row per detector), or a grouped bar chart of
`anomaly_rate_pct`. A noisy detector shows a high anomaly rate; a quiet one a
low rate — handy when tuning. For an overlaid timeline of *when* each detector
fired, bucket and group:

```sql
SELECT
  <time_bucket>(timestamp) AS time,
  detector_name,
  countIf(is_anomaly)      AS anomalies
FROM _dtk_detections
WHERE metric_name = :metric_name
  AND timestamp >= :from AND timestamp < :to
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY time, detector_name
ORDER BY time
```

**Chart type:** stacked bars or multi-series line, one series per
`detector_name`.

### 7. Severity breakdown

The mix of anomaly intensities for a metric — how many were mild vs severe.
`severity` lives in `detection_metadata` (σ-equivalents for MAD/Z-Score,
IQR-units for IQR).

```sql
SELECT
  round(JSONExtractFloat(detection_metadata, 'severity'), 0) AS severity_bucket,
  count() AS anomalies
FROM _dtk_detections
WHERE metric_name = :metric_name
  AND detector_id = :detector_id
  AND is_anomaly = 1
  AND timestamp >= :from AND timestamp < :to
GROUP BY severity_bucket
ORDER BY severity_bucket
```

**Chart type:** bar / histogram (X = severity bucket, Y = count).

To split anomalies by direction (spikes vs drops) instead:

```sql
SELECT
  JSONExtractString(detection_metadata, 'direction') AS direction,  -- 'above' / 'below'
  count() AS anomalies
FROM _dtk_detections
WHERE metric_name = :metric_name
  AND detector_id = :detector_id
  AND is_anomaly = 1
  AND timestamp >= :from AND timestamp < :to
GROUP BY direction
```

**Chart type:** pie / bar.

## Joining tables and avoiding mixed detectors

`_dtk_datapoints` and `_dtk_detections` share `metric_name` and `timestamp`, so
you can join them on that pair — for example to chart raw points alongside a
detector's band when you prefer the value to come from `_dtk_datapoints`:

```sql
SELECT
  dp.timestamp AS time,
  dp.value     AS "Value",
  det.confidence_lower AS "Lower bound",
  det.confidence_upper AS "Upper bound"
FROM _dtk_datapoints dp
LEFT JOIN _dtk_detections det
  ON  dp.metric_name = det.metric_name
  AND dp.timestamp   = det.timestamp
  AND det.detector_id = :detector_id   -- keep the join to ONE detector
WHERE dp.metric_name = :metric_name
  AND dp.timestamp >= :from AND dp.timestamp < :to
ORDER BY dp.timestamp
```

In practice you rarely need the join: `_dtk_detections` already carries the
original `value` (matching `_dtk_datapoints.value`), so recipes 2 and 3 read
from one table.

**The key rule:** `_dtk_detections` is keyed by `detector_id` as well as
`(metric_name, timestamp)`. A metric with two detectors has **two rows per
timestamp**. Always either:

- filter `detector_id = :detector_id` (single-detector charts), or
- `GROUP BY detector_id` / `detector_name` (comparison charts).

Forgetting this double-counts points, draws overlapping confidence bands, and
inflates anomaly counts. Pick the detector you want from the listing query in
[recipe 2](#2-value-with-the-detectors-confidence-band-line--band).

## Tips

- **Drop technical rows.** When counting or rating anomalies, add
  `JSONExtractString(detection_metadata, 'reason') = ''` so points that couldn't
  be scored (`missing_data`, `insufficient_data`) don't skew the numbers.
- **Gaps are `NULL`, not `0`.** Missing intervals in `_dtk_datapoints.value`
  render as line breaks; don't `coalesce(value, 0)` unless you really mean it.
- **Deduplicate on ClickHouse.** The internal tables use `ReplacingMergeTree`;
  add `FINAL` to a read if a recent re-run might have left duplicate versions.
- **Everything is UTC.** Timestamps are stored UTC (`DateTime64(3, 'UTC')`).
  Convert in the BI tool's display timezone rather than in SQL.
- **One panel per metric, parameterized.** A `:metric_name` (and optional
  `:detector_id`) variable lets a single dashboard serve every metric.

## See Also

- [Detectors guide](detectors.md) — what each detector computes and the full
  `detection_metadata` contract
- [Detector references](../reference/detectors/mad.md) —
  [MAD](../reference/detectors/mad.md),
  [Z-Score](../reference/detectors/zscore.md),
  [IQR](../reference/detectors/iqr.md),
  [Manual Bounds](../reference/detectors/manual_bounds.md)
- [Alerting guide](alerting.md) — the alert rule that interprets these detections
- [Auto-tuning guide](autotuning.md) — inspecting the detector `dtk autotune`
  chose (uses these same recipes with the run's `winning_detector_id`)
- [Profiles configuration](configuration-profiles.md) — where the
  `internal_database` lives
- [CLI reference](../reference/cli.md) — running the pipeline that fills these
  tables
