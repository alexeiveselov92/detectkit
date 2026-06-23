# Internal Tables

detectkit writes everything it computes into a handful of internal `_dtk_*`
tables in your database. This page is the **schema reference** for those tables —
their columns, primary keys, and storage engines. For copy-pasteable SQL that
charts them, see [Visualizing Results](../guides/visualizing-results.md).

Results live in the **`internal_database`** (or `internal_schema`) configured in
your profile — separate from the `data_database` your metric queries read from.
See the [Profiles configuration](../guides/configuration-profiles.md) for where
these live. All tables are auto-created on first run (`ensure_tables()`, idempotent).

> **Database note.** Column types below are shown ClickHouse-flavored, but
> detectkit runs on ClickHouse, PostgreSQL and MySQL — all six tables exist on
> all three backends with portable-equivalent types. The primary keys are
> enforced on every backend; the storage **engines** (`ReplacingMergeTree` /
> `MergeTree`) are ClickHouse-specific. On ClickHouse, reads of a
> `ReplacingMergeTree` table need `FINAL` to collapse superseded versions, while
> PostgreSQL/MySQL enforce the primary key so a plain `SELECT` is already
> deduplicated.

Every table is keyed by `metric_name`, so deleting a metric's YAML leaves orphan
rows that [`dtk clean`](cli.md#dtk-clean) prunes (except `_dtk_autotune_runs`,
which is a deliberate audit trail).

## `_dtk_datapoints` — the loaded metric points

One row per metric per timestamp on the metric's time grid (gaps are filled with
`NULL`, never `0`).

| Column | Type | Meaning |
|---|---|---|
| `metric_name` | String | Metric identifier |
| `timestamp` | DateTime64(3, UTC) | Point on the metric's time grid |
| `value` | Nullable(Float64) | Metric value (`NULL` = missing / gap-filled) |
| `seasonality_data` | String (JSON) | Extracted seasonality features for the point |
| `interval_seconds` | Int32 | The metric's grid step, in seconds |
| `seasonality_columns` | String | Comma-separated names of the seasonality features |
| `created_at` | DateTime64(3, UTC) | When the row was written |

**Primary key:** `(metric_name, timestamp)` · **Engine:** `ReplacingMergeTree(created_at)`

## `_dtk_detections` — per-point detection results

One row per **(metric, detector, timestamp)**. A metric with two detectors
produces two rows per timestamp, so always filter or group by `detector_id`.

| Column | Type | Meaning |
|---|---|---|
| `metric_name` | String | Metric identifier |
| `detector_id` | String | Detector identity (hash of its parameters) |
| `detector_name` | String | Detector class name (`MADDetector`, `ZScoreDetector`, `IQRDetector`, `ManualBoundsDetector`) |
| `timestamp` | DateTime64(3, UTC) | The point that was scored |
| `is_anomaly` | Bool | `true`/`1` if flagged anomalous |
| `confidence_lower` | Nullable(Float64) | Lower edge of the expected range |
| `confidence_upper` | Nullable(Float64) | Upper edge of the expected range |
| `value` | Nullable(Float64) | Original metric value (matches `_dtk_datapoints.value`) |
| `processed_value` | Nullable(Float64) | What the detector actually analyzed (after smoothing / `input_type`) |
| `detector_params` | String (JSON) | The detector's non-default parameters |
| `detection_metadata` | String (JSON) | Per-point detail: `severity`, `direction`, `distance`, `reason`, … |
| `created_at` | DateTime64(3, UTC) | When the detection was written |

**Primary key:** `(metric_name, detector_id, timestamp)` · **Engine:** `ReplacingMergeTree(created_at)`

### The `detection_metadata` JSON

The `detection_metadata` JSON commonly carries:

- `reason` — set only when a point could **not** be scored: `"missing_data"`
  (value was `NULL`) or `"insufficient_data"` (fewer than `min_samples` points
  in the window). For real, scored points this key is absent. Filter it out to
  drop these "technical" rows.
- `direction` — `"above"` / `"below"` (present only on anomalies).
- `severity` — distance past the breached bound in units of spread
  (σ-equivalents for MAD/Z-Score, IQR-units for IQR); `0` = exactly on the
  bound. Comparable across MAD and Z-Score.
- `distance` — raw distance from the value to the breached bound.
- Optional: `ess` (effective sample size, when window weighting is on),
  `trend_slope_per_point` (when `detrend: linear` is on), `preprocessing`,
  `window_size`, and `global_*` / `adjusted_*` window statistics.

See [Shared Detector Parameters](detectors/shared-parameters.md#debugging-preprocessed-detections)
for the full metadata contract.

## `_dtk_tasks` — pipeline locks & resume state

One row per **(metric, detector, process_type)**. This is the pipeline's bookkeeping
table: it holds the run lock (only one process per key at a time), the resume
cursor (`last_processed_timestamp`), and timeout/error state. A `running` row older
than its `timeout_seconds` is treated as stale and overridden, so a killed run never
blocks future ones.

| Column | Type | Meaning |
|---|---|---|
| `metric_name` | String | Metric identifier |
| `detector_id` | String | Detector identity, or `load` for the loading task |
| `process_type` | String | `load` or `detect` |
| `status` | String | `running` / `completed` / `failed` |
| `started_at` | DateTime64(3, UTC) | When the task started |
| `updated_at` | DateTime64(3, UTC) | Last update |
| `last_processed_timestamp` | Nullable(DateTime64(3, UTC)) | Resume cursor — last successfully processed point |
| `error_message` | Nullable(String) | Error detail when `failed` |
| `timeout_seconds` | Int32 | Stale-lock threshold |
| `last_alert_sent` | Nullable(DateTime64(3, UTC)) | Legacy cooldown column (authoritative alert state is in `_dtk_alert_states`) |
| `alert_count` | UInt32 | Legacy alert counter |
| `last_recovery_sent` | Nullable(DateTime64(3, UTC)) | Legacy recovery-sent column |

**Primary key:** `(metric_name, detector_id, process_type)` · **Engine:** `MergeTree` (rows replaced via DELETE + INSERT)

## `_dtk_alert_states` — alert bookkeeping

One row per **(metric, alert config block)**, identified by a hash of the alert
config. Tracks cooldown / recovery state — useful for an "alert activity" panel.

| Column | Type | Meaning |
|---|---|---|
| `metric_name` | String | Metric identifier |
| `alert_config_id` | String | Hash of the alerting config (channels, conditions, …) |
| `last_alert_sent` | Nullable(DateTime64(3, UTC)) | When the last alert fired |
| `last_recovery_sent` | Nullable(DateTime64(3, UTC)) | When the last recovery notification fired |
| `alert_count` | UInt32 | Total alerts sent for this config |
| `updated_at` | DateTime64(3, UTC) | Last update |

**Primary key:** `(metric_name, alert_config_id)` · **Engine:** `ReplacingMergeTree(updated_at)`

## `_dtk_metrics` — config mirror (informational)

A mirror of each metric's config for dashboards. It is **informational only** —
the `load → detect → alert` pipeline never reads it — and is rewritten on every
`dtk run` via DELETE + INSERT.

| Column | Type | Meaning |
|---|---|---|
| `metric_name` | String | Metric identifier |
| `description` | Nullable(String) | Optional metric description |
| `path` | String | Path to the `.yml` config file |
| `interval` | String | Interval string (`10min`, `1h`, …) |
| `loading_start_time` | Nullable(DateTime64(3, UTC)) | Initial-load start time |
| `loading_batch_size` | UInt32 | Loading batch size |
| `is_alert_enabled` | UInt8 | Whether alerting is enabled (0/1) |
| `timezone` | Nullable(String) | Timezone for alerts |
| `direction` | Nullable(String) | Required anomaly direction (`same`/`any`/`up`/`down`) |
| `consecutive_anomalies` | UInt32 | Consecutive anomalies to trigger an alert |
| `no_data_alert` | UInt8 | Alert on missing data (0/1) |
| `min_detectors` | UInt32 | Minimum detectors that must agree |
| `tags` | String (JSON) | JSON array of tags |
| `enabled` | UInt8 | Whether the metric is enabled (0/1) |
| `created_at` | DateTime64(3, UTC) | First time the config was saved |
| `updated_at` | DateTime64(3, UTC) | Last config update |

**Primary key:** `(metric_name)` · **Engine:** `MergeTree` (DELETE + INSERT)

## `_dtk_autotune_runs` — auto-tune audit trail

One row per [`dtk autotune`](cli.md#dtk-autotune) run, keyed by `metric_name` +
`run_id`. It is an **audit trail only**: the pipeline never reads it and
`dtk clean --orphaned-metrics` never prunes it. The full column list (training
period, labels, scoring metric, chosen seasonality/detector/params, CV score,
decision log, generated config) is documented in the
[Auto-tune reference](autotune.md#_dtk_autotune_runs-table).

**Primary key:** `(metric_name, run_id)` · **Engine:** `ReplacingMergeTree(created_at)`

## Deduplication & idempotency

Dedup is by **primary key + `INSERT IGNORE` semantics**. For the append tables
(`_dtk_datapoints`, `_dtk_detections`, `_dtk_alert_states`, `_dtk_autotune_runs`)
this is reinforced by `ReplacingMergeTree`, which collapses duplicate keys by the
version column (`created_at` / `updated_at`). On ClickHouse you must read with
`FINAL` to see the collapsed result; PostgreSQL/MySQL enforce the key directly.
Every pipeline stage also resumes from the last persisted timestamp, so re-running
`dtk run` never reprocesses or double-writes.

## See also

- [Visualizing Results](../guides/visualizing-results.md) — SQL recipes that chart these tables.
- [Shared Detector Parameters](detectors/shared-parameters.md#debugging-preprocessed-detections) — the full `detection_metadata` contract.
- [Profiles configuration](../guides/configuration-profiles.md) — where `internal_database` / `internal_schema` is set.
- [Auto-tune reference](autotune.md#_dtk_autotune_runs-table) — the full `_dtk_autotune_runs` schema.
- For the internals (DDL in `tables.py`, dedup mechanics, maintenance) see the [Architecture](../../.claude/rules/architecture.md) reference.
