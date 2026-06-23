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

## How the Search Works

The search runs as a sequence of stages, each recorded in the
[annotated header](#the-annotated-config) and the
[decision log](#_dtk_autotune_runs-table):

1. **Seasonality selection** — greedily builds the best seasonality grouping
   (single columns or conjunctive groups like `[day_of_week, hour]`). It is
   scored by a leak-free, walk-forward **held-out residual reduction** probe: for
   each candidate grouping it measures how much conditioning on that seasonal key
   tightens the per-group center/scale the detector actually applies, using a
   band-width-aware Gaussian negative-log-likelihood evaluated on held-out CV
   folds. The no-seasonality baseline scores exactly `0`; a grouping is accepted
   only if it improves by a margin **and** improves in the majority of folds.
   Over-fragmented groupings fall back to the global statistics and so cannot win
   mechanically. (This replaces the old flag-rate detection objective, which was
   biased against seasonality and often chose "none" even on genuinely seasonal
   metrics.) `force_seasonality` pins the grouping and skips this stage;
   `seasonality_candidates` restricts which columns it may use.
2. **Detector ordering** — a distribution-suitability vote orders the candidate
   detector types most-promising-first. The vote is **advisory only**: it never
   excludes a type. The grid search evaluates **all** windowed statistical
   detectors (`mad` / `zscore` / `iqr`) and cross-validation picks the winner, so
   a heuristic can no longer drop the detector that would have scored best.
3. **Grid search** — a bounded coordinate sweep per detector type
   (threshold → recency weighting → detrend, gated by a trend test → window size),
   followed by a **final threshold re-sweep at the chosen window** that fixes the
   threshold↔window coupling (the optimal threshold depends on window size, but
   threshold is chosen first against a seed window). The threshold grid includes
   high "near-suppress" rungs — sigma `2.5 / 3 / 3.5 / 4 / 5 / 6` (mad / zscore)
   and Tukey `1.5 / 2 / 3 / 4 / 6` (iqr) — so a heavy-tailed metric can widen its
   band under the flag-rate budget instead of being trapped flagging its
   legitimate tail.
4. **Window selection** — sweeps window sizes in natural seasonal units; on a
   near-tie the choice is **trend-gated**. A stationary series prefers the
   **larger** window ("more history is better"); under a detected trend / regime
   shift it prefers the **smaller** window (a fresher baseline that tracks the
   current level instead of averaging in stale history). Supervised runs also
   sweep `consecutive_anomalies` for the alert window.

Cross-validation is walk-forward (expanding-window) throughout; because the
windowed detector is causal, `detect()` runs once per candidate and each fold is
scored by slicing the results (no leakage, no per-fold recompute).

### Unsupervised tuning (no labels)

Without labels the search cannot optimize a labelled metric (MCC etc.), so it
maximizes a **band-fit** objective composed of three bounded terms (weights sum
to 1):

```
objective = 0.4·budget + 0.3·sharpness + 0.3·separation
```

- **budget** (`0.4`) — smooth flag-rate control toward the target rate. There is
  no hard cliff, so there is always gradient back toward fewer flags, and it is
  **one-sided**: a genuinely clean metric is never pushed to manufacture
  anomalies.
- **sharpness** (`0.3`) — rewards a **tight, well-calibrated** confidence
  interval, where normal points sit near the band edge rather than bunched at the
  center. This is the term the old objective lacked (it was blind to band width).
- **separation** (`0.3`) — flagged points sit clearly outside the band relative
  to normal points (a clean partition).

The all-suppress detector (a huge band that flags nothing) is no longer a strong
baseline — it scores only the `budget` term, so a tight band that isolates real
extremes strictly beats doing nothing. (The previous objective was
`0.6·fpr_term + 0.4·separation`, which was scale-invariant and so scored a snug
band and a hugely slack one identically.)

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
**unsupervised** objective (a tight, well-calibrated band — see
[Unsupervised tuning](#unsupervised-tuning-no-labels)). Supervised mode engages
only if labeled timestamps land on **loaded**
grid points; labels entirely outside the loaded series mark nothing and the run
proceeds unsupervised.

```bash
dtk autotune --select api_error_rate --incidents incidents/api_error_rate.yml
```

### `--label` (flag)

The easiest way to produce labels — mark incidents **visually on the chart**
instead of dictating timestamps. It writes a self-contained HTML chart of the
metric's series to `metrics/<metric>__labeler.html` and exits. **Generate-and-exit**:
the command writes no rows to the database and runs no search.

```bash
dtk autotune --select api_error_rate --label
```

Then:

1. Open `metrics/api_error_rate__labeler.html` in any browser — just double-click
   it. The file is fully self-contained (the series and the chart are inlined; no
   server, no internet).
2. **Click-drag across the chart** over each real incident. Each span shows as a
   red band and a row in the list below; *remove* / *Clear all* fix mistakes.
3. Click **Export incidents-<metric>.yml** — your browser downloads a labels file
   in the [canonical format](#labels-file-format).
4. Re-run supervised with that file:
   `dtk autotune --select api_error_rate --incidents incidents-api_error_rate.yml`.

The labeler looks like this (a live copy of the real output — try dragging on it):

<iframe src="/examples/autotune-labeler.html" title="Interactive incident labeler — live example" style="width:100%;height:440px;border:1px solid var(--sl-color-gray-5);border-radius:8px;background:#211e1a"></iframe>

> Open it directly: [examples/autotune-labeler.html](../examples/autotune-labeler.html).

Each exported span/point uses the canonical schema, e.g.:

```yaml
metric: api_error_rate
timezone: UTC
incidents:
  - {start: "2026-05-07 06:00:00", end: "2026-05-07 13:00:00"}
```

### `--scoring` (optional, default: `mcc`)

The metric the search maximizes across folds. One of `mcc`, `f1`, `f_beta`,
`balanced_accuracy`, `roc_auc`, `pr_auc` — see [Scoring metrics](#scoring-metrics).
It applies only to **supervised** runs; without labels the search maximizes the
no-label [band-fit objective](#unsupervised-tuning-no-labels) instead.

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
  labels_file: incidents/orders.yml   # external labels file, OR inline (below)
  # incidents:                        # inline labels — mutually exclusive with labels_file
  #   - {start: "2026-05-02 14:00:00", end: "2026-05-02 16:30:00", label: outage}
  #   - {at: "2026-05-11 09:05:00", label: deploy spike}
  # incidents_timezone: UTC           # interprets the naive times above (default UTC)
  seasonality_candidates: [hour, day_of_week]   # RESTRICT which columns the search may group on
  # force_seasonality: [hour]                    # OR pin the grouping and skip the search
  # force_seasonality: [[day_of_week, hour]]     #    (a nested list is one conjunctive group)
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
| `labels_file` | string | Path to a default [labels file](#labels-file-format); overridden by `--incidents`. Mutually exclusive with `incidents` |
| `incidents` | list | Inline labels — the same `{start, end}` / `{at}` entries as a [labels file](#labels-file-format), declared directly in the metric config. Mutually exclusive with `labels_file`; overridden by `--incidents` |
| `incidents_timezone` | string | Timezone interpreting the naive times in `incidents` (default `UTC`). Only valid alongside `incidents` |
| `seasonality_candidates` | list | **Restrict** the seasonality dimensions the search may group on — a subset of `hour` / `day_of_week` / `day_of_month` / `month` / `is_weekend` (plus any query-declared columns). It narrows the search space; it does not pin a grouping. `is_holiday` is accepted but never used (the holiday calendar is unimplemented — always `false`) |
| `force_seasonality` | list | **Pin** the seasonality grouping and **skip** the search. Each entry is a column name, or a list of columns for one conjunctive group — `[hour]` groups by `hour`; `[[day_of_week, hour]]` groups by the `day_of_week`×`hour` combination; `[day_of_week, hour]` is two separate components. Complements `seasonality_candidates` (which only restricts the search). If a forced column is absent from the data, the search runs normally instead |
| `fixed_params` | map | Pin specific hyperparameters (they are excluded from the search) |
| `folds` | int | Number of walk-forward (expanding-window) cross-validation folds |
| `max_history` | int | Cap on the number of training points used |

**Label resolution precedence** (highest first): the `--incidents` flag → the
config's `labels_file` → the config's inline `incidents` → an interactive prompt
(only on a TTY) → none (unsupervised).

A worked block is in
[autotuned-metric-example.yml](../examples/autotuned-metric-example.yml).

## Scoring Metrics

In a **supervised** run the search maximizes one scoring metric across the
walk-forward folds. The default, `mcc`, suits rare anomalies because it uses the
whole confusion matrix. (An unsupervised run has no labels and instead maximizes
the [band-fit objective](#unsupervised-tuning-no-labels).)

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

The objective line is mode-aware. A **supervised** run reports the labelled
metric it maximized (`Scoring metric : mcc = …`); an **unsupervised** run never
computes a labelled metric, so it reports the no-label objective instead —
`Objective : unsupervised (band-fit + flag-budget) = …`. The seasonality line
lists the per-candidate held-out residual reduction so a rejection is never
opaque, e.g. `hour:5.70, day_of_week:-0.00`.

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
- [Internal Tables](internal-tables.md) — the `_dtk_autotune_runs` table and the
  rest of the `_dtk_*` schema
