# Auto-tune Reference

Reference for `dtk autotune` — the automatic detector-configuration command —
its flags, the labels-file format, the `autotune:` config block, the scoring
metrics it can optimize, and the `_dtk_autotune_runs` audit table.

For the task-oriented walkthrough, see the
[Auto-tuning a Detector](../guides/autotuning.md) guide.

## Overview

`dtk autotune` reads a metric's already-loaded `_dtk_datapoints`, searches
detector type × hyperparameters × seasonality grouping × history window (× alert
window, when supervised), cross-validates each candidate with walk-forward folds,
and writes a new, annotated metric YAML. It is a separate pipeline from
`load → detect → alert`: it **never edits the original config and never sends
alerts**.

```bash
dtk autotune --select <selector> [OPTIONS]
```

## Options

### `--select`, `-s` (required)

Metric selector — same semantics as [`dtk run`](cli.md#dtk-run) (metric name,
path pattern, or `tag:<name>`). Tuning reads loaded datapoints; if a metric has
none yet, load it first:

```bash
dtk run --select my_metric --steps load   # optionally --from <date> for more history
```

### `--incidents` (optional)

Path to a [labels file](#labels-file-format) of known incidents → **supervised**
tuning. Without it (and without an `autotune.labels_file` in the config), an
**interactive** terminal first prompts whether to enter incidents inline
(`No incident labels provided. Enter them now?`); decline — or run
non-interactively (cron/CI/piped input, no prompt) — and tuning falls back to the
**unsupervised** objective (low false-positive rate + stable cross-fold
separation). Supervised mode engages only if labeled timestamps land on **loaded**
grid points; labels entirely outside the loaded series mark nothing and the run
proceeds unsupervised.

```bash
dtk autotune --select api_error_rate --incidents incidents/api_error_rate.yml
```

### `--label` (flag)

Write a self-contained HTML chart of the metric's series to
`metrics/<metric>__labeler.html` so you can mark incidents visually. Open it in a
browser, click-drag across the chart to mark each incident, and use its
**Export** button to download a labels file in the [format below](#labels-file-format)
— then re-run with `--incidents`. **Generate-and-exit** — the command itself
writes no rows to the database and runs no search.

```bash
dtk autotune --select api_error_rate --label
```

### `--scoring` (optional, default: `mcc`)

The metric the search maximizes across folds. One of `mcc`, `f1`, `f_beta`,
`balanced_accuracy`, `roc_auc`, `pr_auc` — see [Scoring metrics](#scoring-metrics).

```bash
dtk autotune --select api_error_rate --incidents incidents/api_error_rate.yml --scoring f_beta
```

### `--from` (optional)

Lower bound of the training window (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`, UTC).
Restricts the datapoints autotune considers.

### `--to` (optional)

Upper bound of the training window (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`, UTC).

### `--profile` (optional)

Override the default profile from the project config — same as
[`dtk run --profile`](cli.md#-profile-optional).

### `--force` (flag)

Ignore an existing task lock and run anyway (same lock semantics as
[`dtk run --force`](cli.md#-force-flag)).

### `--dry-run` (flag)

Run the full search but **persist nothing** — write no config, no detections, and
no `_dtk_autotune_runs` row. Useful to preview what autotune would choose.

## What It Produces

On success (without `--dry-run`), one run:

- writes `metrics/<name>__tuned_<id>.yml` — a normal, ready-to-run config led by
  the [annotated decision header](#the-annotated-config) (the `<id>` is a
  deterministic hash of the run);
- records one row in [`_dtk_autotune_runs`](#_dtk_autotune_runs-table) (the audit
  trail);
- persists the winning detector's detections to `_dtk_detections`;
- prunes the superseded winners from prior autotune runs of the same metric.

It never touches the original metric YAML.

## Labels File Format

YAML or JSON. **All times are UTC.** Each incident is either an **interval**
(`{start, end}`, `end` inclusive of the grid points it covers) for a sustained
incident, or a **point** (`{at}`) for a single spike — never both keys on one
incident.

```yaml
metric: api_error_rate          # optional; if set, must match the tuned metric's name
timezone: UTC                   # optional; interprets the naive times below
incidents:
  - start: "2026-05-02 14:00:00"   # interval incident
    end:   "2026-05-02 16:30:00"
    label: payment-gateway outage  # optional, free text
  - at: "2026-05-11 09:05:00"      # point incident
    label: deploy spike
```

The same structure as JSON:

```json
{
  "metric": "api_error_rate",
  "timezone": "UTC",
  "incidents": [
    { "start": "2026-05-02 14:00:00", "end": "2026-05-02 16:30:00", "label": "payment-gateway outage" },
    { "at": "2026-05-11 09:05:00", "label": "deploy spike" }
  ]
}
```

| Field | Scope | Required | Meaning |
|---|---|---|---|
| `metric` | top-level | No | Metric name these labels belong to; if present, must match the metric being tuned |
| `timezone` | top-level | No | Timezone used to interpret the naive timestamps below (default UTC) |
| `incidents` | top-level | Yes | List of incident entries |
| `start` / `end` | incident | One of `{start,end}` or `at` | Interval incident; `end` is inclusive of the grid points it covers |
| `at` | incident | One of `{start,end}` or `at` | Point incident (a single anomalous timestamp) |
| `label` | incident | No | Free-text note describing the incident |

A commented file is in
[autotune-incidents-example.yml](../examples/autotune-incidents-example.yml).

## `autotune:` Config Block

An optional block on a metric YAML that constrains the search. Fully optional —
its absence means "tune everything automatically". Command-line flags take
precedence (`--scoring` over `scoring_metric`, `--incidents` over `labels_file`).

```yaml
autotune:
  enabled: true
  detector_types: [mad, zscore]
  scoring_metric: mcc
  beta: 1.0
  labels_file: incidents/orders.yml
  seasonality_candidates: [hour, day_of_week]
  fixed_params: {window_size: 4320}
  folds: 5
  max_history: 50000
```

| Field | Type | Meaning |
|---|---|---|
| `enabled` | bool | Whether autotune is enabled for this metric |
| `detector_types` | list | Restrict candidate detectors to a subset of `mad` / `zscore` / `iqr` |
| `scoring_metric` | string | Default optimization target (see [Scoring metrics](#scoring-metrics)); overridden by `--scoring` |
| `beta` | float | The β for `scoring_metric: f_beta` (β > 1 favors recall, β < 1 favors precision) |
| `labels_file` | string | Path to a default [labels file](#labels-file-format); overridden by `--incidents` |
| `seasonality_candidates` | list | Restrict the seasonality dimensions the search may group on — a subset of `hour` / `day_of_week` / `day_of_month` / `month` / `is_weekend` (plus any query-declared columns). `is_holiday` is accepted but never used (the holiday calendar is unimplemented — always `false`) |
| `fixed_params` | map | Pin specific hyperparameters (they are excluded from the search) |
| `folds` | int | Number of walk-forward (expanding-window) cross-validation folds |
| `max_history` | int | Cap on the number of training points used |

A worked block is in
[autotuned-metric-example.yml](../examples/autotuned-metric-example.yml).

## Scoring Metrics

The search maximizes one scoring metric across the walk-forward folds. The
default, `mcc`, suits rare anomalies because it uses the whole confusion matrix.

| Metric | Definition |
|---|---|
| `mcc` (default) | Matthews correlation coefficient — a balanced score over the full confusion matrix; robust when anomalies are rare |
| `f1` | Harmonic mean of precision and recall (equal weight) |
| `f_beta` | Weighted F-score; the `beta` field tilts toward recall (β > 1) or precision (β < 1) |
| `balanced_accuracy` | Mean of the true-positive and true-negative rates — class-imbalance-aware accuracy |
| `roc_auc` | Area under the ROC curve — ranking/separability across thresholds |
| `pr_auc` | Area under the precision–recall curve — emphasizes the positive (anomaly) class on imbalanced data |

The recall-vs-precision trade-off is the usual knob: tilt toward recall when
missing an incident is the expensive outcome, toward precision when false pages
are.

## The Annotated Config

The emitted `metrics/<name>__tuned_<id>.yml` leads with a `#` comment block that
walks every decision before the real config: the **training period**, the
**labels** used, the **seasonality** rationale, the **detector votes**, the
**grid-search winner** with its **CV score** and **per-fold scores**, and the
**window choice**. Below the header is an ordinary metric config — a single
chosen detector with the chosen seasonality, copying over the metric's
query/alerting.

**Hand-editing the detector below the header changes its `detector_id`**, so its
old detections orphan. After editing, recompute and prune:

```bash
dtk run --select <name>__tuned_<id> --steps detect --full-refresh
dtk clean --select <name>__tuned_<id> --execute
```

See [Detector Identity and
Recomputation](../guides/detectors.md#detector-identity-and-recomputation).

## `_dtk_autotune_runs` Table

One row per autotune run — an **audit trail**. It is never read by the
`load → detect → alert` pipeline, and is **not** pruned by
`dtk clean --orphaned-metrics`. It lives in the profile's `internal_database` /
`internal_schema`, alongside the other [`_dtk_*` tables](../guides/visualizing-results.md#whats-in-the-tables).
Primary key: `(metric_name, run_id)`.

| Column | Type | Meaning |
|---|---|---|
| `metric_name` | String | Metric identifier |
| `run_id` | String | Deterministic id of this run (matches the `<id>` in the generated filename; `failed` for a failed run) |
| `created_at` | DateTime64(3, UTC) | When the run completed |
| `training_period_start` | Nullable(DateTime64(3, UTC)) | Start of the data window the search used (null on a failed run) |
| `training_period_end` | Nullable(DateTime64(3, UTC)) | End of the data window the search used (null on a failed run) |
| `interval_seconds` | Int32 | The metric's grid step, in seconds |
| `labels_json` | String (JSON) | The resolved incident labels (supervised runs) |
| `mode` | String | `supervised` or `unsupervised` |
| `scoring_metric` | String | The metric that was maximized |
| `score` | Nullable(Float64) | The winning cross-validated score (null on a failed run) |
| `chosen_seasonality_json` | String (JSON) | The chosen `seasonality_components` grouping |
| `chosen_detector_type` | Nullable(String) | The chosen detector type (`mad` / `zscore` / `iqr`; null on a failed run) |
| `chosen_detector_params_json` | String (JSON) | The chosen detector parameters |
| `winning_detector_id` | Nullable(String) | The `detector_id` of the chosen detector (null on a failed run) |
| `candidate_detector_ids_json` | String (JSON) | The detector ids evaluated during the search |
| `decision_log_json` | String (JSON) | The structured decision log behind the annotated header |
| `generated_config_path` | Nullable(String) | Path of the written tuned config (null on a failed run) |
| `generated_config_text` | String | Full text of the written tuned config |
| `status` | String | Run status — `success` or `failed` |
| `error_message` | Nullable(String) | Failure detail when `status` is `failed` (null otherwise) |

Inspect the latest runs for a metric:

```sql
SELECT run_id, created_at, mode, scoring_metric, score,
       chosen_detector_type, winning_detector_id
FROM <internal>._dtk_autotune_runs           -- add FINAL on ClickHouse
WHERE metric_name = 'api_error_rate'
ORDER BY created_at DESC
LIMIT 5
```

To then see the chosen detector at work, chart `_dtk_detections` for the
`winning_detector_id` — see
[Reading the tuned detector's results](../guides/autotuning.md#see-how-it-behaves)
and the [Visualizing Results](../guides/visualizing-results.md) guide.

## See Also

- [Auto-tuning a Detector](../guides/autotuning.md) — the task-oriented guide
- [CLI Reference](cli.md) — the rest of the `dtk` commands
- [Detectors Guide](../guides/detectors.md) — the detectors and shared parameters
  the search ranges over
- [Visualizing Results](../guides/visualizing-results.md) — chart the tuned
  detector in any BI tool
