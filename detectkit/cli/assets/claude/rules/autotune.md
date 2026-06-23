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
   from the metric's seasonality columns (built-ins + any query columns). It is
   scored on its own merits — by how much conditioning on a seasonal key tightens
   the per-group center/scale the detector applies, measured on held-out
   walk-forward CV folds (a band-width-aware "held-out residual reduction", with
   the global no-seasonality baseline = 0). A grouping wins only if it beats the
   baseline by a margin **and** improves on a majority of folds; over-fragmented
   groupings fall back to global, so a flat metric keeps `seasonality_components`
   empty while a genuinely seasonal one gets the key it deserves.
2. **Detector type** — a quick distribution vote orders the candidates
   (Gaussian/light-tailed → `zscore`; heavy tails/outliers → `mad`; skewed →
   `iqr`), but it is advisory only: the grid search evaluates **all** statistical
   detectors (`mad`/`zscore`/`iqr`) and cross-validation picks the winner — no
   type is excluded by heuristic.
3. **Hyperparameters** — a bounded coordinate grid search over `threshold`,
   recency weighting, detrending and `window_size`, maximizing a
   cross-validated score, with a final `threshold` re-sweep at the chosen window.
4. **History window** — on near-ties uses a trend-gated tie-break: a stationary
   series prefers the **larger** `window_size` ("more history is better"), a
   trending / regime-shifting one the **smaller**; sets `loading_start_time` to
   cover the lead-in.
5. **Alert window** (supervised only) — sweeps `consecutive_anomalies` on the
   labeled incidents.

Cross-validation is automatic walk-forward (expanding-window) folds — no split
ratios to choose.

## Command

```bash
dtk autotune --select <sel> [--incidents FILE] [--label] [--scoring METRIC] \
             [--from DATE] [--to DATE] [--profile NAME] [--force] [--dry-run]
```

- `--incidents FILE|DIR` — a labels file (below) → **supervised** tuning. May be a
  **directory** (e.g. `incidents/<name>/`) — the newest versioned file in it is
  used. With nothing given, an interactive terminal prompts to enter incidents
  inline; declining (or running non-interactively) tunes **unsupervised**.
- `--label` — write a self-contained, zoomable/pannable HTML chart of the series
  to `metrics/<name>__labeler.html`; the user marks incidents in a browser (with
  optional per-incident descriptions) and **Export** downloads a *versioned*
  labels file `<name>-<UTC>.yml`. Generate-and-exit (no DB writes).
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

### Getting labels — offer the interactive labeler first

When labels would help, **offer the interactive HTML labeler before asking the
user to recall timestamps** — it is the easiest, most reliable path:

1. Run `dtk autotune --select <name> --label` (offline; writes no DB rows). It
   renders the series to a self-contained `metrics/<name>__labeler.html`.
2. Tell the user to open it in a browser and mark incidents on the chart: scroll
   to zoom, drag the navigator strip to move, **click-drag** to mark each span
   (add an optional description), then **Export**.
3. Persist with versioning: a browser can't write into the project, so Export
   downloads a versioned `<name>-<UTC>.yml`. **Move it into `incidents/<name>/`**
   — re-labeling adds a new file, never overwrites, so every round is kept. You
   (the assistant, with filesystem access) do this move.
4. Tune on the latest: point `--incidents` at the folder so the newest version is
   used — `dtk autotune --select <name> --incidents incidents/<name>/`.

Prefer this whenever the user can *recognise* incidents on a chart but doesn't
have exact times. If they already know the times (or you found them via a DB
MCP), write the labels file / inline `incidents:` directly instead. If there are
no known incidents, run unsupervised — the baseline below is good on its own.

With no labels (no `--incidents`, no config `labels_file`, no interactive
entry), tuning falls back to an **unsupervised** objective that blends three
band-fit / flag-budget terms — `0.4·budget + 0.3·sharpness + 0.3·separation`: a
smooth one-sided flag-rate budget (no hard cliff), sharpness (a tight,
well-calibrated confidence interval), and separation (flagged points sitting
clearly outside the normal band). Suppressing every point is no longer a strong
baseline, so the objective won't collapse to "flag nothing".

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
  seasonality_candidates: [hour, day_of_week]   # restrict the search's column set
  force_seasonality: [hour]       # pin the grouping, skip the search (see below)
  fixed_params: {window_size: 4320}  # pin hyperparameters (excluded from search)
  folds: 5
  max_history: 50000              # cap training points
```

`force_seasonality` pins the seasonality grouping and **skips** the search
entirely — give a single column name (`force_seasonality: hour`), a flat list of
columns to try separately (`force_seasonality: [hour]`), or a nested list to
force a conjunctive group (`force_seasonality: [[day_of_week, hour]]`). It
differs from `seasonality_candidates`, which only narrows the *set of columns*
the search may consider but still runs the search and may choose none.

Label precedence (highest first): `--incidents` flag → `labels_file` → inline
`incidents` → interactive prompt → none. `labels_file` and `incidents` are
mutually exclusive. `--scoring` likewise overrides `scoring_metric`.

## The annotated config

The emitted YAML leads with a `#` comment block walking every decision —
training period, labels, seasonality rationale (with the per-candidate held-out
residual reduction it measured), detector votes, grid-search winner + CV score +
per-fold scores, and the window choice — then the real config (single detector +
chosen seasonality, copied query/alerting). Read this header to understand and
present *why* the configuration looks the way it does. On a supervised run the
header reports `Scoring metric : <metric> = <score>`; on an unsupervised run it
instead reads `Objective : unsupervised (band-fit + flag-budget) = <score>`.

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
