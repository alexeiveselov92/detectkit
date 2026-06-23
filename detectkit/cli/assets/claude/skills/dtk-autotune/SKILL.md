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

## Step 2 — Gather incident history → write the labels file

Supervised tuning needs known incidents. The labels file is the contract; you
fill it from the user's plain-language description. (If you have read access to
the database — e.g. a database MCP — query the metric's series yourself to spot
candidate incidents and propose them for confirmation, rather than relying only
on memory.) Resolve each incident to **UTC** and classify it as an interval
(`{start, end}`) for a sustained incident or a point (`{at}`) for a spike. Read
the resolved times back to confirm, then write `incidents/<metric>.yml` (the
`dtk init` scaffold already created `incidents/` beside `metrics/`):

```yaml
# incidents/<metric>.yml — known anomalies for supervised autotuning.
# All times are UTC. Use an interval for a sustained incident or a point for a
# single spike. `end` is inclusive of the grid points it covers.
metric: api_error_rate          # must match the metric `name` it labels
timezone: UTC                   # optional; interprets the naive times below
incidents:
  - start: "2026-05-02 14:00:00"
    end:   "2026-05-02 16:30:00"
    label: payment-gateway outage   # optional, free text
  - at: "2026-05-11 09:05:00"       # a single anomalous point
    label: deploy spike
```

The same schema works as JSON. **Inline alternative:** for just one or two
incidents, declare the same entries directly under the metric's `autotune:` block
(`incidents:` + optional `incidents_timezone:`) instead of a separate file —
mutually exclusive with `labels_file`, and `--incidents` still overrides it:

```yaml
autotune:
  incidents:
    - {start: "2026-05-02 14:00:00", end: "2026-05-02 16:30:00", label: outage}
    - {at: "2026-05-11 09:05:00", label: deploy spike}
  incidents_timezone: UTC   # optional; default UTC
```

If the user can't enumerate incidents, say so and go to Step 3 unsupervised — or
offer `dtk autotune --select <name> --label`, which writes a clickable HTML chart
to `metrics/<name>__labeler.html`; they mark incidents in a browser and its
Export button downloads a labels file in this exact format to feed back via
`--incidents`.

## Step 3 — Run autotune

```bash
# Supervised (recommended when you have incidents):
dtk autotune --select <name> --incidents incidents/<name>.yml

# Unsupervised (no labels — tunes on data statistics):
dtk autotune --select <name>
```

`dtk autotune` reads the metric's **already-loaded** datapoints. If there are
none yet, load first: `dtk run --select <name> --steps load` (optionally
`--from <date>` to backfill history — more history tunes better). The default
scoring metric is **MCC** (robust to rare anomalies). Override only with reason:
`--scoring recall` when a miss is worse than a false page, `--scoring f1`, etc.
Run `dtk autotune --help` to confirm the live flags. Use `--dry-run` to search
without writing anything.

## Step 4 — Study and present the result

Read the emitted `metrics/<name>__tuned_<id>.yml` (do not re-run the search).
The `#` comment header walks the whole decision; summarize for the user:

- which **detector** won and why (the distribution votes),
- the chosen **seasonality** grouping and `seasonality_columns`,
- key params (`threshold`, `window_size`, `min_samples`, weighting/detrend) and
  the alert `consecutive_anomalies`,
- the **CV score** + metric, and the per-fold spread.

Offer alternatives: a re-run with a different `--scoring` (e.g. precision vs
recall trade-off) or a nudged parameter. See `autotune.md` for the
`_dtk_autotune_runs` audit table.

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
