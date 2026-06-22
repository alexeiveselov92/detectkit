# Auto-tuning a Detector

`dtk autotune` automatically configures a metric's detector from its data — and,
if you can supply them, from labeled incidents. Instead of hand-picking a
detector type, threshold, window, seasonality and alert window, you point
autotune at a metric and it searches for the best configuration, then writes a
**new, annotated** metric YAML you can review and run.

It is a separate pipeline from `load → detect → alert`: it reads the metric's
already-loaded `_dtk_datapoints`, runs a cross-validated search, and emits
`metrics/<name>__tuned_<id>.yml`. **It never edits your original config and never
sends alerts.**

> **Fastest path:** let Claude Code drive the whole flow. Run
> [`dtk init-claude`](../reference/cli.md#dtk-init-claude), then use the
> **`dtk-autotune`** skill — it runs the seasonality interview, writes the
> incidents file, runs `dtk autotune`, and explains the chosen config and how it
> behaves against your database, conversationally.

## What It Searches

Autotune searches four (or five, when supervised) dimensions and cross-validates
every choice:

1. **Seasonality** — greedily builds the best `seasonality_components` grouping
   from the metric's available seasonality columns (the built-ins plus any
   columns your query declares).
2. **Detector type** — a distribution decision tree votes per seasonality group:
   Gaussian / light-tailed → `zscore`; heavy tails or outliers → `mad`; skewed →
   `iqr`. The winners are shortlisted.
3. **Hyperparameters** — a bounded coordinate grid search over `threshold`,
   recency weighting, detrending and `window_size`, maximizing a cross-validated
   score.
4. **History window** — prefers a larger `window_size` on near-ties ("more
   history is better"), and sets `loading_start_time` to cover the lead-in.
5. **Alert window** (supervised only) — sweeps `consecutive_anomalies` against
   the labeled incidents.

Cross-validation is automatic **walk-forward** (expanding-window) folds — there
are no split ratios to choose.

A tuned config is an ordinary detectkit config: one chosen detector reusing the
same windowed detectors and the same [`detector_id`
identity](detectors.md#detector-identity-and-recomputation) as everything else.

## Before You Tune: Load the Data

Autotune reads the metric's **already-loaded** datapoints from
`_dtk_datapoints`. If a metric has never run, load it first — and load enough
history, since more history tunes better:

```bash
# Load the metric (optionally backfill more history with --from)
dtk run --select api_error_rate --steps load --from "2026-01-01"
```

Then tune.

## The Supervised Path (Recommended)

When you can tell autotune *which* points were real incidents, it optimizes
directly against them — picking the detector, threshold and alert window that
catch your incidents while keeping false positives down.

### 1. Write an incidents file

The incidents (labels) file is the contract. It is YAML or JSON; **all times are
UTC**, and each incident is either an **interval** (`{start, end}`) for a
sustained problem or a **point** (`{at}`) for a single spike:

```yaml
# incidents/api_error_rate.yml
metric: api_error_rate          # optional; must match the metric being tuned
timezone: UTC                   # optional; interprets the naive times below
incidents:
  - start: "2026-05-02 14:00:00"
    end:   "2026-05-02 16:30:00"
    label: payment-gateway outage   # optional, free text
  - at: "2026-05-11 09:05:00"        # a single anomalous point
    label: deploy spike
```

See [autotune-incidents-example.yml](../examples/autotune-incidents-example.yml)
for a fully commented file, and the [reference](../reference/autotune.md#labels-file-format)
for the complete schema.

> Can't enumerate the incidents from memory? Run
> `dtk autotune --select api_error_rate --label` to get a self-contained HTML
> chart of the series; mark the incidents visually and it exports a labels file
> in exactly this format (it generates and exits, writing nothing to the DB).

### 2. Run it

```bash
dtk autotune --select api_error_rate --incidents incidents/api_error_rate.yml
```

Autotune searches, cross-validates against your incidents, and writes
`metrics/api_error_rate__tuned_<id>.yml`.

## The Unsupervised Fallback

If you pass no labels — no `--incidents`, no `labels_file` in the config — tuning
falls back to an **unsupervised** objective that rewards a low false-positive
rate and stable, clean separation across folds:

```bash
dtk autotune --select api_error_rate
```

This still picks a detector, hyperparameters, seasonality and window; it just
cannot optimize for *your* notion of an incident. Use it to get a sane starting
configuration, then refine with labels later.

## Choosing the Scoring Metric

Autotune maximizes a single scoring metric across the walk-forward folds. The
default is **MCC** (Matthews correlation coefficient), which uses the whole
confusion matrix and is well-suited to rare anomalies. Override it with
`--scoring`:

```bash
# Favor catching every incident (recall) over avoiding false pages
dtk autotune --select api_error_rate \
  --incidents incidents/api_error_rate.yml \
  --scoring f_beta
```

| Scoring metric | Use when |
|---|---|
| `mcc` (default) | Balanced, robust to rare anomalies — a safe default |
| `f1` | You weight precision and recall equally |
| `f_beta` | You want to tilt toward recall (a miss is worse than a false page) or precision |
| `balanced_accuracy` | Class balance matters and you want both rates weighted equally |
| `roc_auc` | You care about ranking/separability across thresholds |
| `pr_auc` | Heavily imbalanced data — emphasizes the positive (anomaly) class |

See the [scoring-metrics catalog](../reference/autotune.md#scoring-metrics) for
one-line definitions of each. The recall-vs-precision trade-off is the usual
knob: optimize for recall (`f_beta` tilted toward recall) when missing an
incident is the expensive outcome; optimize for precision when false pages are.

## Reading the Annotated Config + CV Score

The emitted YAML leads with a `#` comment block that walks **every** decision
before the real config begins:

- the **training period** and the labels used,
- the **seasonality** rationale (why those `seasonality_components`),
- the **detector votes** (which distribution the data looked like, per group),
- the **grid-search winner** with its **CV score** and **per-fold scores**,
- and the **window choice**.

Read this header to understand *why* the configuration looks the way it does
before trusting it. Below the header is an ordinary metric config — a single
chosen detector with the chosen seasonality, and your query/alerting carried
over.

Each run is also recorded as one row in the `_dtk_autotune_runs` audit table
(see [Inspecting the search](#see-how-it-behaves) and the
[reference](../reference/autotune.md#_dtk_autotune_runs-table)).

## Applying the Tuned Config

The tuned config is a normal metric YAML — run it like any other:

```bash
dtk run --select api_error_rate__tuned_<id>          # load → detect → alert
dtk test-alert api_error_rate__tuned_<id>            # if alerting is configured
```

**If you hand-edit the detector** below the comment header, you change its
parameters — and a detector's identity is a hash of its parameters, so the old
detections orphan under the previous `detector_id`. Recompute under the new id
and prune the orphans:

```bash
# Recompute detections under the edited detector
dtk run --select api_error_rate__tuned_<id> --steps detect --full-refresh

# Prune the now-orphaned detections from the old detector_id
dtk clean --select api_error_rate__tuned_<id> --execute
```

See [Detector Identity and
Recomputation](detectors.md#detector-identity-and-recomputation) for why this is
needed.

## The `autotune:` Block (for Experts)

You can pin or constrain the search by adding an `autotune:` block to a metric
YAML. It is fully optional — absent means "tune everything automatically":

```yaml
autotune:
  enabled: true
  detector_types: [mad, zscore]      # restrict candidates (subset of mad/zscore/iqr)
  scoring_metric: mcc                # default optimization target
  beta: 1.0                          # only used for scoring_metric: f_beta
  labels_file: incidents/orders.yml  # default labels (supervised)
  seasonality_candidates: [hour, day_of_week]
  fixed_params: {window_size: 4320}  # pin hyperparameters (excluded from the search)
  folds: 5                           # number of walk-forward folds
  max_history: 50000                 # cap training points
```

Command-line flags win: `--scoring` and `--incidents` override the block's
`scoring_metric` / `labels_file`. See
[autotuned-metric-example.yml](../examples/autotuned-metric-example.yml) for a
worked block, and the [reference](../reference/autotune.md#autotune-config-block)
for every field.

## See How It Behaves

To *see* the tuned detector at work, join recent datapoints with its detections
— `value` vs `confidence_lower` / `confidence_upper` vs `is_anomaly` vs
`severity` — for the run's **winning `detector_id`**. Get that id from the latest
`_dtk_autotune_runs` row:

```sql
SELECT run_id, created_at, mode, scoring_metric, score,
       chosen_detector_type, winning_detector_id
FROM <internal>._dtk_autotune_runs           -- add FINAL on ClickHouse
WHERE metric_name = 'api_error_rate'
ORDER BY created_at DESC
LIMIT 5
```

Then chart the winning detector. The query is the same shape on every backend;
only JSON extraction and dedup differ:

**ClickHouse**

```sql
SELECT timestamp, value, confidence_lower, confidence_upper, is_anomaly,
       JSONExtractFloat(detection_metadata, 'severity') AS severity
FROM <internal>._dtk_detections FINAL
WHERE metric_name = 'api_error_rate'
  AND detector_id = '<winning_detector_id>'
  AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY timestamp
```

**PostgreSQL**

```sql
SELECT timestamp, value, confidence_lower, confidence_upper, is_anomaly,
       (detection_metadata::jsonb ->> 'severity')::float AS severity
FROM <internal>._dtk_detections
WHERE metric_name = 'api_error_rate'
  AND detector_id = '<winning_detector_id>'
  AND timestamp >= now() - INTERVAL '7 days'
ORDER BY timestamp
```

**MySQL (8.0+)**

```sql
SELECT timestamp, value, confidence_lower, confidence_upper, is_anomaly,
       JSON_EXTRACT(detection_metadata, '$.severity') AS severity
FROM <internal>._dtk_detections
WHERE metric_name = 'api_error_rate'
  AND detector_id = '<winning_detector_id>'
  AND timestamp >= NOW() - INTERVAL 7 DAY
ORDER BY timestamp;
```

For full charting recipes (the value with its confidence band, anomaly markers,
severity breakdowns) point any BI tool at these tables — see
[Visualizing Results](visualizing-results.md).

## See Also

- [`dtk autotune` reference](../reference/autotune.md) — every flag, the labels
  schema, the `autotune:` block, the scoring catalog, and the
  `_dtk_autotune_runs` columns
- [Detectors Guide](detectors.md) — what each detector computes and the shared
  parameters autotune searches over
- [Visualizing Results](visualizing-results.md) — chart the tuned detector in any
  BI tool
- [CLI Reference](../reference/cli.md) — the rest of the `dtk` commands
- [autotune-incidents-example.yml](../examples/autotune-incidents-example.yml) —
  a commented labels file
- [autotuned-metric-example.yml](../examples/autotuned-metric-example.yml) — a
  metric with an `autotune:` block
