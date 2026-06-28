# detectkit — auto-tuning (`dtk autotune`)

`dtk autotune` automatically configures a metric's detector from its data (and,
if you have them, labeled incidents). It is a separate pipeline from
`load → detect → alert`: it reads the metric's already-loaded `_dtk_datapoints`,
searches for the best configuration, and writes a **new, annotated** metric YAML
— it never edits the original and never sends alerts.

A tuned config is an ordinary detectkit config (one chosen detector reusing the
same windowed detectors and `detector_id` identity). The fastest path is the
**`dtk-autotune`** skill, which runs the whole flow conversationally.

> **Prefer to tune by hand?** `dtk tune --select <metric>` is the interactive,
> human-in-the-loop sibling: it opens a browser view of the real series, lets you
> turn the knobs and watch the band recompute live, and on **Apply** writes the
> config back into the metric YAML **in place** (archiving the previous version to
> `metrics/.history/<metric>/` first). Use `autotune` to search automatically and
> emit a new file; use `tune` to dial a detector in by eye and commit it. See
> `cli.md`.
>
> **You can also run this engine *inside* `dtk tune`** — its **Autotune** mode runs
> the same search **server-side** (using the incidents you've marked as ground
> truth), re-seeds the knobs with the winner, and lets you **Apply** in place. That's
> the same computation as this command, with two differences: it tunes on the
> **window currently shown** in the cockpit (the **Points shown** trim — the series
> you see and score) rather than the full capped history, and it edits the metric YAML
> in place (advisory — no run record / `__tuned_<id>.yml` / persisted detections)
> rather than emitting a new tuned file. Reach for `dtk autotune` when you want the
> audited run + tuned file + persisted winner detections.

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
   recency weighting (and its **half-life** when adopted), detrending and
   `window_size`, maximizing a cross-validated score, with a final `threshold`
   re-sweep at the chosen window. Fold scores aggregate as
   `mean − stability_lambda · downside_deviation` (downside-only, so a config that
   scores *better* on recent folds isn't penalized; lower `stability_lambda` for a
   regime-shift metric).
4. **History window** — on near-ties uses a trend-gated tie-break: a stationary
   series prefers the **larger** `window_size` ("more history is better"), a
   trending / regime-shifting one the **smaller**; sets `loading_start_time` to
   cover the lead-in (and pins the detector's `start_time` to it, so the first
   `dtk run` detects across all loaded history). The trend gate is a midpoint
   test, so it can miss a level shift that sits off-center or self-masks by
   inflating the global MAD; a backstop scan then logs a **`REGIME`** advisory in
   the decision log (and streams it) when the series reads stationary yet a large
   (≥3σ within-regime) level shift is present — it names a **concrete `--from
   <date>`** (the shift's timestamp); surface it to the user and suggest re-tuning
   with that date (or `autotune.max_history`) if the earlier regime is stale.
   Advisory only; it changes no chosen parameters,
   and it detects level shifts, not variance/shape changes (label incidents for
   those).
5. **Alert window** (supervised only) — sweeps `consecutive_anomalies` on the
   labeled incidents.

Cross-validation is automatic walk-forward (expanding-window) folds — no split
ratios to choose.

## Command

```bash
dtk autotune --select <sel> [--incidents FILE] [--scoring METRIC] \
             [--from DATE] [--to DATE] [--profile NAME] [--force] [--dry-run] [--report]
```

- `--incidents FILE|DIR` — a labels file (below) → **supervised** tuning. May be a
  **directory** (e.g. `incidents/<name>/`): interactive runs prompt to pick a
  version (default newest), non-interactive use the newest. **Omit it and `dtk
  autotune` auto-discovers the newest labels in `incidents/<metric>/`** (the store
  `dtk tune`'s **Save incidents** writes) — so after labeling in `dtk tune` you run
  `dtk autotune --select <metric>` with no flag. With no labels anywhere, an
  interactive terminal prompts to enter incidents inline; declining (or running
  non-interactively) tunes **unsupervised**.
- **To label incidents**, use `dtk tune --select <metric>`: switch to **Label**
  mode (drag spans, **Threshold capture** every span past a horizontal line,
  **Lasso** the anomaly cloud) or **Review** mode (confirm fired alerts as
  incidents), then **Save incidents**. That writes versioned files into
  `incidents/<metric>/` — the **same store this command reads** — so the labels feed
  the next supervised tune with no `--incidents` flag (see `cli.md`).
- `--scoring` — `mcc` (default), `f1`, `f_beta`, `balanced_accuracy`, `roc_auc`,
  `pr_auc`. MCC uses the whole confusion matrix and suits rare anomalies.
- `--dry-run` — run the search but persist nothing and write no config.
- `--report [PATH]` — after tuning, emit a self-contained **HTML report** for the
  winning config over the training window (values, confidence band, anomalies,
  replayed alerts; offline). Bare `--report` writes
  `reports/<name>__tuned_<id>.html`; pass a directory or a `.html` path to
  override. `dtk run --select <m> --report` produces the same report from the
  live config.
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

### Getting labels — label in `dtk tune` first

When labels would help, **offer to mark incidents in `dtk tune` before asking the
user to recall timestamps** — it is the easiest, most reliable path:

1. Run `dtk tune --select <name>`. It opens a localhost browser view of the real
   series (use `--no-open` on a remote box and share the printed 127.0.0.1 URL).
2. Mark the real incidents one of two ways:
   - **Label** mode — drag a span over each incident, or **Threshold capture**
     every span past a horizontal line in one gesture, or **Lasso anomalies** to
     loop a cloud of anomaly dots into per-streak incident spans.
   - **Review** mode — the fired alerts lead; click each alert marker to confirm it
     **valid** (which marks it as a ground-truth incident) or **false alarm**.
     **Confirm all unreviewed valid** does the lot — a clean metric whose alerts
     are all good is validated in a few clicks without hand-drawing spans.
3. Click **Save incidents**. It writes a versioned
   `incidents/<metric>/<…>.yml` automatically.
4. Run `dtk autotune --select <name>` with **no `--incidents` flag** — it
   auto-discovers the newest file in `incidents/<metric>/` and tunes supervised on
   it. (You can still pass `--incidents <file-or-dir>` to pick a specific set.)

Prefer this whenever the user can *recognise* incidents on a chart but doesn't
have exact times. If they already know the times (or you found them via a DB
MCP), write the labels file / inline `incidents:` directly instead. If there are
no known incidents, run unsupervised — the baseline below is good on its own.

With no labels (no `--incidents`, no config `labels_file`, none auto-discovered
in `incidents/<metric>/`, no interactive entry), tuning falls back to an
**unsupervised** objective that blends three
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
  stability_lambda: 0.5           # downside-dispersion penalty weight (0 disables)
  max_history: 50000              # cap training points
```

`force_seasonality` pins the seasonality grouping and **skips** the search
entirely — give a single column name (`force_seasonality: hour`), a flat list of
columns to try separately (`force_seasonality: [hour]`), or a nested list to
force a conjunctive group (`force_seasonality: [[day_of_week, hour]]`). It
differs from `seasonality_candidates`, which only narrows the *set of columns*
the search may consider but still runs the search and may choose none.

Label precedence (highest first): `--incidents` flag → `labels_file` → inline
`incidents` → auto-discovered `incidents/<metric>/` (the newest file, e.g. from
`dtk tune`'s **Save incidents**) → interactive prompt → none (unsupervised).
`labels_file` and `incidents` are mutually exclusive. `--scoring` likewise
overrides `scoring_metric`.

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

The quickest view is an **HTML report**: add `--report` to the tune (or run
`dtk run --select <m> --report` later) to get a self-contained file charting the
winning detector's values, confidence band, flagged anomalies and the alerts it
would fire, with a period selector — no BI/SQL setup, offline.

To query the raw rows instead, join recent datapoints with its detections
(`value` vs `confidence_lower/upper` vs `is_anomaly`) for the
`winning_detector_id` — see the per-backend query templates in the
**`dtk-autotune`** skill and in the visualizing-results guide.

> Generated by `dtk init-claude`. Re-run it after upgrading detectkit to refresh
> these instructions.
