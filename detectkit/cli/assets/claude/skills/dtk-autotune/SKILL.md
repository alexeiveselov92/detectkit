---
name: dtk-autotune
description: >-
  Automatically tune and optimize a detectkit metric's anomaly detector: pick
  the best detector type and hyperparameters, auto-configure seasonality, and
  build a working alert from a monitoring request and tune it on real data. Use
  when the user wants to tune/optimize a metric's detector, pick the best anomaly
  detector, reduce false positives/negatives by tuning, choose detector
  parameters automatically, or stand up an alert from scratch and tune it.
  Gathers extra seasonality and incident history, writes a labels file, runs
  `dtk autotune`, then explains the chosen config and shows how it behaves
  against the database. Produces a tuned, annotated metric YAML ready to run.
---

# Auto-tune a detectkit metric

`dtk autotune` searches detector type × hyperparameters × seasonality grouping ×
history window, cross-validates each choice (against labeled incidents if you
have them, otherwise an unsupervised objective), and writes a ready-to-run
config named `<metric>__tuned_<id>` whose comment header explains every
decision. Each run is recorded in the `_dtk_autotune_runs` table.

Work the steps in order. Do not invent SQL, incident times, or channel names —
gather them. This skill is the procedure; for field detail read the matching
file under `.claude/rules/detectkit/` (`autotune.md`, `detectors.md`,
`metrics.md`, `alerting.md`).

## Step 0 — Confirm the metric exists (or scaffold it)

A project root contains `detectkit_project.yml`. If `profiles.yml` is still the
`dtk init` placeholder, the DB connection comes first — use **`dtk-setup-project`**.

- **Metric already exists** (`metrics/<name>.yml`): use it.
- **No metric yet** — this is the "build an alert from a request" path: hand off
  to the **`dtk-new-metric`** skill to design the query + a starter config, then
  return here to tune it. Keep one owner for query design (that skill), so you
  never fabricate SQL here.

## Step 1 — Seasonality interview

detectkit extracts these built-in seasonality features from the timestamp for
free: `hour`, `day_of_week`, `day_of_month`, `month`, `is_weekend`
(`is_holiday` is a placeholder — always false, ignored by autotune).

Ask whether the metric has **business-cycle signals beyond these**, e.g.: league
/ match day, release or deploy day, marketing-campaign windows, paydays,
promo flights, school terms, or market-specific holidays. If yes:

- Tell the user to add each as a **column in the metric query** (snake_case),
  declare them in `query_columns.seasonality: [...]`, and list them in the
  metric's `seasonality_columns`. autotune will then consider them as candidate
  seasonality dimensions. You name the columns; the user provides the SQL.
- Query-provided columns take precedence over a built-in of the same name.

If there are no extra signals, the built-ins are enough — continue.

**How autotune picks seasonality.** The search no longer judges a seasonal key
by its flag rate (which was biased against seasonality and often landed on
"none"). It now uses a leak-free, walk-forward, **band-width-aware held-out
residual-reduction probe** (Gaussian NLL): a key is accepted only if conditioning
on it actually tightens the per-group band on *held-out* folds — baseline is 0,
and a key wins only on a margin **and** a majority-of-folds improvement. So if a
real seasonal cycle exists, it now gets chosen on its merits; a key that doesn't
generalize is rejected.

**To steer it** via the metric's `autotune:` block (these complement each other):

- `seasonality_candidates: [hour, day_of_week]` — **restrict** the column set the
  search may group on (still searches within that subset).
- `force_seasonality:` — **pin** a grouping and skip the search entirely. Give a
  single column (`force_seasonality: hour`), a flat list of columns to use as
  separate components (`force_seasonality: [hour, day_of_week]`), or a nested list
  for a conjunctive group (`force_seasonality: [[day_of_week, hour]]`, i.e. group
  by the day_of_week×hour combination). If a forced column is absent from the
  data, the search runs normally instead.

## Step 2 — Get incident labels (optional, but it improves tuning)

Labels turn tuning from a good unsupervised default into a config optimised
against *your* real incidents (it then optimises MCC and also tunes the alert
window `consecutive_anomalies`). **The easiest, most reliable way to produce them
is to mark incidents in `dtk tune` — offer this first**, before asking the user to
recall timestamps:

```bash
dtk tune --select <name>
```

This opens a localhost browser view of the metric's **real** series; on a remote
machine add `--no-open` and share the printed URL. Walk the user through it:

1. Navigate a long/dense series: **scroll to zoom**, double-click to reset, drag
   the **navigator strip** to move the view.
2. Mark the real incidents in one of two modes:
   - **Label** mode — **drag a span** over each incident (edges to resize, middle
     to move, ✕/Delete to remove). When many outliers are obvious, **Threshold
     capture** grabs every span past a horizontal line in one gesture (set the
     line, pick the side, optionally bridge gaps); **Lasso anomalies** loops a
     freeform cloud of anomaly dots into one incident span per grid-adjacent run.
   - **Review** mode — the fired alerts lead; **click each alert marker** to cycle
     its verdict un-reviewed → **valid** (green) → **false alarm** (slate).
     **Confirming an alert valid marks it as a ground-truth incident**, and
     **Confirm all unreviewed valid** does the lot — so a clean metric whose alerts
     are all good is validated in a few clicks without hand-drawing spans.
3. Click **Save incidents**. It writes `incidents/<metric>/<…>.yml` automatically
   (versioned — saving never overwrites). Saving doesn't end the session, so you
   can keep tuning; you can also click **Apply** to write the detector config back.

**Then run autotune with no `--incidents` flag** — `dtk autotune --select <name>`
**auto-discovers the newest file in `incidents/<metric>/`** (the same store
`dtk tune` saves to) and tunes supervised on it. To re-tune on a specific set,
pass `--incidents <file-or-dir>` (point it at `incidents/<name>/` and interactive
runs let the user pick a version). Labeling grows across sessions — reopen
`dtk tune`, mark a few more, **Save incidents** again, re-run autotune.

Prefer this whenever the user can *recognise* incidents on a chart but doesn't
have exact timestamps — it is far easier than dictating times, and they label
against the same series the detector sees. Tell the user plainly that you're
giving them an interactive chart to mark incidents on.

**If the user already knows the exact incident times** (or you found them via a
database MCP), you can write the labels directly instead of using the chart.
Resolve each to **UTC**; an interval `{start, end}` is a sustained incident, a
point `{at}` is a single spike. Either as a file `incidents/<metric>.yml` (the
`dtk init` scaffold already created `incidents/` beside `metrics/`):

```yaml
# incidents/<metric>.yml — known anomalies for supervised autotuning.
metric: api_error_rate          # must match the metric `name` it labels
timezone: UTC                   # optional; interprets the naive times below
incidents:
  - start: "2026-05-02 14:00:00"
    end:   "2026-05-02 16:30:00"
    label: payment-gateway outage   # optional, free text
  - at: "2026-05-11 09:05:00"       # a single anomalous point
    label: deploy spike
```

…or, for one or two incidents, inline under the metric's `autotune:` block
(`incidents:` + optional `incidents_timezone:`; mutually exclusive with
`labels_file`, and `--incidents` overrides it):

```yaml
autotune:
  incidents:
    - {start: "2026-05-02 14:00:00", end: "2026-05-02 16:30:00", label: outage}
  incidents_timezone: UTC   # optional; default UTC
```

**If there are no known incidents**, skip to Step 3 — the unsupervised baseline
is good on its own; it just can't learn *which* spikes you specifically care about.

## Step 3 — Run autotune

```bash
# Supervised — labeled in `dtk tune`: just run it, autotune auto-discovers
# the newest file in incidents/<name>/ (no --incidents flag needed):
dtk autotune --select <name>

# Supervised — point at a specific labels file or set explicitly:
dtk autotune --select <name> --incidents incidents/<name>.yml

# Unsupervised (no labels anywhere — tunes on data statistics):
dtk autotune --select <name>
```

`dtk autotune` reads the metric's **already-loaded** datapoints. If there are
none yet, load first: `dtk run --select <name> --steps load` (optionally
`--from <date>` to backfill history — more history tunes better). The default
**supervised** scoring metric is **MCC** (robust to rare anomalies). Override
only with reason: `--scoring f_beta` (with a higher `beta:` in the `autotune:`
block) when a miss is worse than a false page, `--scoring f1` for a balanced
trade-off, etc. The valid values are `mcc`, `f1`, `f_beta`, `balanced_accuracy`,
`roc_auc`, `pr_auc`. Run `dtk autotune --help` to confirm the live flags. Use
`--dry-run` to search without writing anything.

**Unsupervised runs** (no labels) do **not** optimize MCC or any labeled metric —
`--scoring` is ignored. They optimize a no-label objective
`0.4·budget + 0.3·sharpness + 0.3·separation`: it rewards a **tight, well-calibrated
confidence band** (sharpness) under a controlled flag rate (budget) plus clean
separation of the flagged extremes. Practically this means the unsupervised tuner
now prefers a snug band that isolates real extremes rather than the old timid
"flag almost nothing" default. With no labels it cannot learn *which* spikes
matter, so confirm the result against real history (Step 5) and add incidents
later for a sharper tune.

## Step 4 — Study and present the result

For a visual the user can open, re-run the tune with `--report` (or run
`dtk run --select <name>__tuned_<id> --report`): it writes a self-contained
`reports/<name>__tuned_<id>.html` charting values, the confidence band, anomalies
and the alerts that would fire — no SQL needed. The raw-row queries below remain
the fallback for inline inspection.

Read the emitted `metrics/<name>__tuned_<id>.yml` (do not re-run the search).
The `#` comment header walks the whole decision; summarize for the user:

- which **detector** won. All statistical detectors (mad / zscore / iqr) are
  grid-searched and **cross-validation picks the winner** — the distribution
  suitability vote only *orders* which is tried first, it never excludes one. So
  describe the winner as "highest CV score", and mention the vote only as the
  ordering hint it is.
- the chosen **seasonality** grouping and `seasonality_columns` (or "none" — a
  legitimate result when no key tightened the held-out band; see Step 1).
- key params (`threshold`, `window_size`, `min_samples`, weighting/detrend) and
  the alert `consecutive_anomalies`.
- the score line. For a **supervised** run the header reads
  `Scoring metric : <metric> = …`; for an **unsupervised** run it reads
  `Objective : unsupervised (band-fit + flag-budget) = …` (it never claims an
  `mcc =` score it didn't compute). Read off the value + the per-fold CV spread.

Offer alternatives: a re-run with a different `--scoring` (e.g. `f_beta` with a
higher `beta` to favor recall, or `f1` for balance) or a nudged parameter. See
`autotune.md` for the `_dtk_autotune_runs` audit table.

## Step 5 — Show how the monitoring behaves (DB inspection query)

Generate a query so the user can *see* the tuned detector at work. Get the
winning `detector_id` from the `_dtk_autotune_runs` row or by running
`dtk run --select <name>__tuned_<id> --steps detect` once. Pick the template by
the profile's `type:` in `profiles.yml` (never guess the backend). `<internal>`
is the profile's internal database/schema.

**ClickHouse**

```sql
SELECT timestamp, value, confidence_lower, confidence_upper, is_anomaly,
       JSONExtractFloat(detection_metadata, 'severity') AS severity
FROM <internal>._dtk_detections FINAL
WHERE metric_name = '<metric>'
  AND detector_id = '<detector_id>'
  AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY timestamp
```

**PostgreSQL**

```sql
SELECT timestamp, value, confidence_lower, confidence_upper, is_anomaly,
       (detection_metadata::jsonb ->> 'severity')::float AS severity
FROM <internal>._dtk_detections
WHERE metric_name = '<metric>'
  AND detector_id = '<detector_id>'
  AND timestamp >= now() - INTERVAL '7 days'
ORDER BY timestamp
```

**MySQL (8.0+)**

```sql
SELECT timestamp, value, confidence_lower, confidence_upper, is_anomaly,
       JSON_EXTRACT(detection_metadata, '$.severity') AS severity
FROM <internal>._dtk_detections
WHERE metric_name = '<metric>'
  AND detector_id = '<detector_id>'
  AND timestamp >= NOW() - INTERVAL 7 DAY
ORDER BY timestamp;
```

To list a metric's detector ids (ClickHouse `FINAL`/`count()` are ClickHouse-only):

```sql
SELECT detector_id, detector_name, count(*) AS rows, max(timestamp) AS last_seen
FROM <internal>._dtk_detections
WHERE metric_name = '<metric>'
GROUP BY detector_id, detector_name
ORDER BY last_seen DESC
```

## Step 6 — Run the tuned config

The tuned config is a normal metric. After any manual edit to its detector
params (which changes the `detector_id`), recompute and prune:

```bash
dtk run --select <name>__tuned_<id>                 # load → detect → alert
dtk test-alert <name>__tuned_<id>                   # if alerting is configured
# if you hand-edit the detector afterwards:
dtk run --select <name>__tuned_<id> --steps detect --full-refresh
dtk clean --select <name>__tuned_<id> --execute     # prune orphaned old detector rows
```

## Final checklist — verify before declaring done

- [ ] Metric exists; `name` unique; query filters on `{{ dtk_start_time }}` and
      `{{ dtk_end_time }}`.
- [ ] Any extra seasonality is a real, declared query column.
- [ ] Labels file (if supervised) is valid UTC, each incident is interval-XOR-point,
      and `metric` matches the metric name.
- [ ] `dtk autotune` ran and wrote `metrics/<name>__tuned_<id>.yml`.
- [ ] You read the decision header and presented the detector / seasonality /
      params / CV score, plus a DB inspection query for the winning `detector_id`.
