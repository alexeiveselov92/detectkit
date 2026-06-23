# detectkit — auto-tuning (`dtk autotune`)

`dtk autotune` automatically configures a metric's detector from its data (and,
if you have them, labeled incidents). It is a separate pipeline from
`load → detect → alert`: it reads the metric's already-loaded `_dtk_datapoints`,
searches for the best configuration, and writes a **new, annotated** metric YAML
— it never edits the original and never sends alerts.

A tuned config is an ordinary detectkit config (one chosen detector reusing the
same windowed detectors and `detector_id` identity). The fastest path is the
**`dtk-autotune`** skill, which runs the whole flow conversationally.

## What it searches

1. **Seasonality** — greedily builds the best `seasonality_components` grouping
   from the metric's seasonality columns (built-ins + any query columns).
2. **Detector type** — a distribution decision tree votes per seasonality group
   (Gaussian/light-tailed → `zscore`; heavy tails/outliers → `mad`; skewed →
   `iqr`); the winners are shortlisted.
3. **Hyperparameters** — a bounded coordinate grid search over `threshold`,
   recency weighting, detrending and `window_size`, maximizing a
   cross-validated score.
4. **History window** — prefers a larger `window_size` on near-ties ("more
   history is better"); sets `loading_start_time` to cover the lead-in.
5. **Alert window** (supervised only) — sweeps `consecutive_anomalies` on the
   labeled incidents.

Cross-validation is automatic walk-forward (expanding-window) folds — no split
ratios to choose.

## Command

```bash
dtk autotune --select <sel> [--incidents FILE] [--label] [--scoring METRIC] \
             [--from DATE] [--to DATE] [--profile NAME] [--force] [--dry-run]
```

- `--incidents FILE` — a labels file (below) → **supervised** tuning. With no
  labels file, an interactive terminal prompts to enter incidents inline;
  declining (or running non-interactively) tunes **unsupervised**.
- `--label` — write a self-contained HTML chart of the series to
  `metrics/<name>__labeler.html`; the user marks incidents in a browser and its
  **Export** button downloads a labels file. Generate-and-exit (no DB writes).
- `--scoring` — `mcc` (default), `f1`, `f_beta`, `balanced_accuracy`, `roc_auc`,
  `pr_auc`. MCC uses the whole confusion matrix and suits rare anomalies.
- `--dry-run` — run the search but persist nothing and write no config.
- Selectors match `dtk run`. Tuning reads loaded datapoints — if empty, run
  `dtk run --select <m> --steps load` (optionally `--from`) first.

On success it writes `metrics/<name>__tuned_<id>.yml` (the `<id>` is a
deterministic hash of the run), records a row in `_dtk_autotune_runs`, persists
the winning detector's detections, and prunes superseded winners from prior
runs.

## Labels file

YAML or JSON. All times UTC; each incident is an interval **or** a point.

```yaml
metric: api_error_rate          # optional; must match the metric being tuned
timezone: UTC                   # optional; interprets the naive times below
incidents:
  - {start: "2026-05-02 14:00:00", end: "2026-05-02 16:30:00"}   # interval
  - {at: "2026-05-11 09:05:00"}                                  # point
```

With no labels (no `--incidents`, no config `labels_file`, no interactive
entry), tuning falls back to an **unsupervised** objective that rewards a low
false-positive rate and stable, clean separation across folds.

## `autotune:` config block (optional, for experts)

Add to a metric YAML to constrain the search. Fully optional — absent means
"tune everything automatically".

```yaml
autotune:
  enabled: true
  detector_types: [mad, zscore]   # restrict candidates (subset of mad/zscore/iqr)
  scoring_metric: mcc             # default optimization target
  beta: 1.0                       # only for scoring_metric: f_beta
  labels_file: incidents/orders.yml   # external labels file, OR inline (below)
  # incidents:                    # inline labels — mutually exclusive with labels_file
  #   - {start: "2026-05-02 14:00:00", end: "2026-05-02 16:30:00", label: outage}
  #   - {at: "2026-05-11 09:05:00", label: deploy spike}
  # incidents_timezone: UTC       # interprets the naive times above (default UTC)
  seasonality_candidates: [hour, day_of_week]
  fixed_params: {window_size: 4320}  # pin hyperparameters (excluded from search)
  folds: 5
  max_history: 50000              # cap training points
```

Label precedence (highest first): `--incidents` flag → `labels_file` → inline
`incidents` → interactive prompt → none. `labels_file` and `incidents` are
mutually exclusive. `--scoring` likewise overrides `scoring_metric`.

## The annotated config

The emitted YAML leads with a `#` comment block walking every decision —
training period, labels, seasonality rationale, detector votes, grid-search
winner + CV score + per-fold scores, and the window choice — then the real
config (single detector + chosen seasonality, copied query/alerting). Read this
header to understand and present *why* the configuration looks the way it does.

**Hand-editing the detector below the header changes its `detector_id`**, so its
old detections orphan. After editing, recompute and prune:
`dtk run --select <tuned> --steps detect --full-refresh` then
`dtk clean --select <tuned> --execute`.

## `_dtk_autotune_runs` table

One row per run (an audit trail, never read by the pipeline; not pruned by
`dtk clean --orphaned-metrics`). Columns include `metric_name`, `run_id`,
`created_at`, `training_period_start/end`, `labels_json`, `mode`,
`scoring_metric`, `score`, `chosen_seasonality_json`, `chosen_detector_type`,
`chosen_detector_params_json`, `winning_detector_id`,
`candidate_detector_ids_json`, `decision_log_json`, `generated_config_text`,
`status`. Inspect the latest run:

```sql
SELECT run_id, created_at, mode, scoring_metric, score,
       chosen_detector_type, winning_detector_id
FROM <internal>._dtk_autotune_runs           -- add FINAL on ClickHouse
WHERE metric_name = '<metric>'
ORDER BY created_at DESC
LIMIT 5
```

## Reading the tuned detector's results

To see the winning detector at work, join recent datapoints with its detections
(`value` vs `confidence_lower/upper` vs `is_anomaly`) for the
`winning_detector_id` — see the per-backend query templates in the
**`dtk-autotune`** skill and in the visualizing-results guide.

> Generated by `dtk init-claude`. Re-run it after upgrading detectkit to refresh
> these instructions.
