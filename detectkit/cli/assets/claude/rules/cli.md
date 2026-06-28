# detectkit — CLI (`dtk`)

Run all commands from a project directory (the one containing
`detectkit_project.yml`). `dtk --help` and `dtk <command> --help` always work.

## Commands

| Command | Purpose |
|---|---|
| `dtk init <name>` | Scaffold a new project directory |
| `dtk init-claude` | (Re)generate this Claude context (CLAUDE.md + `.claude/rules/detectkit/` + skills) |
| `dtk run --select <sel>` | Run the load → detect → alert pipeline |
| `dtk autotune --select <sel>` | Auto-configure a metric's detector (see `autotune.md`) |
| `dtk tune --select <sel>` | Interactively tune a detector on real data, write it back in place |
| `dtk test-alert <metric>` | Send a mock alert to the metric's channels |
| `dtk unlock --select <sel>` | Clear a stuck pipeline lock |
| `dtk clean --select <sel>` | Prune internal data that no longer matches the config |
| `dtk --version` | Show installed detectkit version |

## Selectors (`--select` / `-s`)

Used by `run`, `unlock`, and `clean` (drift mode). Three forms:

- **Metric name** — `--select cpu_usage`. Resolves to `metrics/cpu_usage.yml` at
  the root, then falls back to a recursive search by the YAML `name:` field in any
  subdirectory. Do **not** add `.yml` (it is appended). This matches the metric by
  **name**, and every operation is keyed by that `name` inside the YAML.
- **Path / glob** — `--select "metrics/critical/*.yml"`, `--select "api_*"`,
  `--select "metrics/**/*.yml"`. Searches recursively via glob; keep `.yml`.
- **Tag** — `--select tag:critical`. Searches recursively for metrics whose
  `tags:` list contains that tag.

`--select "*"` selects everything. `--exclude / -e` (on `dtk run`) removes matches
(`--select "*" --exclude "metrics/staging/*"`). Metric names must be unique
across the project; duplicates raise an error listing the conflicting files.

## `dtk run`

```bash
dtk run --select <sel> [--steps load,detect,alert] [--from DATE] [--to DATE] \
        [--full-refresh] [--force] [--profile NAME] [--report [PATH]]
```

- `--steps` — which of `load`, `detect`, `alert` to run (default all); they always
  execute in `load → detect → alert` order. Examples: `--steps load` (verify the
  query), `--steps detect` (rerun detection only), `--steps detect,alert` (skip load).
- `--from DATE` / `--to DATE` — `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`, UTC.
  Affects only the `load` step. `--from` overrides the metric's
  `loading_start_time`; `--to` defaults to now.
- `--full-refresh` — **destructive**: deletes the metric's datapoints and
  detections, then reloads from `loading_start_time`/`--from`. Use after
  changing the query or to recompute detections over history.
- `--force` — ignore a held lock and run anyway (also releases it on exit).
  Risky with concurrent runs; usually `dtk unlock` is the better recovery.
- `--profile` — override the project's default profile (e.g. run against staging).
- `--report [PATH]` — after the run, write a **self-contained HTML report** per
  metric (values + per-detector confidence bands + flagged anomalies + the alerts
  that fired + a summary, with client-side period selection). It is offline — open
  it in a browser, nothing leaves the page. The report reads the persisted `_dtk_*`
  tables, so even a `--steps load` run can produce one. Dual-mode: bare `--report`
  → `reports/<metric>.html`; `--report <dir>` → `<dir>/<metric>.html`;
  `--report file.html` → that file.

## `dtk autotune --select <sel>`

Automatically chooses a metric's seasonality, detector type, hyperparameters and
history window, then writes an annotated `metrics/<name>__tuned_<id>.yml`. Reads
the metric's loaded datapoints (run `dtk run --steps load` first if empty), never
edits the original, never alerts. `--incidents FILE` enables supervised tuning
against labeled incidents; omit it and autotune **auto-discovers** the newest
labels in `incidents/<metric>/` (the store `dtk tune`'s **Save incidents** writes
— label there in Label/Review mode, then just run `dtk autotune`); with no labels
anywhere, an unsupervised objective is used. `--dry-run` searches without writing.
`--report [PATH]` writes the same
self-contained HTML report as `dtk run` for the tuned winner (default
`reports/<metric>__tuned_<id>.html`; `<dir>` or a `.html` file also accepted).
Full reference: `autotune.md`.

## `dtk tune --select <sel>`

The **manual, interactive** sibling of `dtk autotune`. Opens a localhost browser
view of the metric's **real** persisted series and lets you turn the detector's
knobs (type — including **Manual bounds** with lower/upper sliders — threshold,
window, recency weighting + half-life, detrend, smoothing, **seasonality groups**,
**direction** (both/up/down), alert `consecutive_anomalies`) while the confidence
band and flagged anomalies **recompute live**. The whole screen is a **chart-first
cockpit**: ONE chart (the windshield) fills the view, the live metrics ride
**pinned in a HUD over the chart** (the speedometer), and every control lives in an
**always-visible, mode-aware side rail** beside the chart (Tune shows the detector
knobs + effective config + Apply, Review the verdict actions, Label the capture
tools + incident list + Save, Autotune the search button + winning config), while
the controls that aren't detector-specific —
the **Points shown** data window, the alert rule (**direction** + **consecutive
anomalies**) and the **y = 0** toggle — stay visible in every mode. The chart is
**zoomable** (scroll/drag + navigator strip) with a **"Points shown"** trim slider.
Clicking **Apply** writes the chosen
config back into the metric YAML **in place** (autotune, by contrast, writes a new
`__tuned_<id>.yml` and never edits the original). Reads the metric's loaded
datapoints (run `dtk run --steps load` first if empty); the selector must resolve
to a single metric.

**Modes + alert review + live quality.** A **mode switch** picks which layers lead
and which interactions are armed on the one chart: **Tune** (band leads; incidents
recede to read-only context; hover a point for its window), **Review** (the fired
alerts lead, band ghosts — click an alert marker to cycle its verdict un-reviewed →
**valid** (green) → **false alarm** (slate); **Confirm all unreviewed valid** does
the lot), **Label** (band hides; **mark the real incidents** by drag, **Lasso
anomalies** — loop a cloud of anomaly dots, each consecutive run, gaps bridged up to
`consecutive_anomalies`, becomes one span — or **Threshold capture** every span past
a horizontal line, each widened to a full interval so the alert lands inside; the
painted window saves as `capture_windows`), and **Autotune** (**Run autotune**
launches the **real** `dtk autotune` engine **server-side** over the metric's full
history, using your marked incidents as ground truth, then **re-seeds every knob**
with the winner and shows the score + decision log; the band leads like Tune). The
Autotune mode is **advisory** — it computes + re-seeds only and persists nothing (no
run record / `__tuned_<id>.yml` / detections, so `dtk tune` stays lock-free); review
the band and **Apply** to write it back. It honours the metric's `autotune:` block,
is supervised when incidents are marked (also picks `consecutive_anomalies`) else
unsupervised, and needs the live server (unavailable under `--no-serve`).
**Confirming an alert valid IS marking an
incident**: the confirmed streak becomes a first-class **ground-truth incident** that
shows in the Marked-incidents list (a read-only "✓ confirmed alert" row; its ✕
un-confirms the alert), counts toward recall + correct, and is written on Save — so a
clean metric whose alerts are all good is validated in a few clicks **without
hand-drawing spans**. The list, the live metrics and Save share **one** ground-truth
set (hand-marked spans **plus** confirmed-valid alerts, deduped by overlap).
As you tune, a metrics bar shows **incident catch rate (recall)** — how many
ground-truth incidents (marked + confirmed) your config catches (an incident is
caught when an alert's anomaly **streak overlaps** it, not just the fire instant) —
**false-alert rate** (what share of alerts fall outside any incident and aren't
confirmed valid; "≈1 in N false", a decimal so a mostly-false rate doesn't round to
a misleading "1 in 1") — and **reviewed N/M**; only incidents within the loaded
window are scored. An optional **false-alert budget** (`false_alert_budget`, a
fraction in `(0, 1]`, on the **metric** then **project**, default `0.5`) gently flags
the false-alert chip when the rate exceeds it (tuning-only; labeling stays optional).
**Save incidents** writes a
versioned `incidents/<metric>/*.yml` — the same store `dtk autotune` reads, so the
same labels feed the next supervised tune (it seeds from the newest file on open,
**anchoring the budget-sized loaded window on the seeded incidents** — ending just
past the latest one rather than at the last datapoint — so they render/count
without an old outlier pulling the whole history in; per-alert verdicts persist as
an `alert_reviews:` metadata block and re-seed on reopen, re-bound to the moved
alerts by streak overlap). Saving incidents does not end the session; only **Apply**
does. A **y = 0 line** toggle (shared with `dtk run --report`) shows the metric
relative to zero.

Safe write-back: the config is validated before anything is written, the previous
YAML is archived under `metrics/.history/<metric>/`, and only then is the metric
overwritten. Takes **no pipeline lock** (it only edits a config file); re-run
`dtk run` afterward to recompute detections under the new config.
`--no-serve` writes a static read-only preview HTML instead (no write-back —
**Save incidents** downloads the labels file); `--from` / `--to` bound the window;
`--no-open` prints the URL without opening a browser.

## `dtk test-alert <metric>`

Sends a mock alert (fake value/CI/severity) through the metric's configured
channels, using that alert config's own rule (`min_detectors` / `direction` /
`consecutive_anomalies`) and the project-name `[name]` prefix, so the preview
matches a real firing. Use it to verify webhook URLs, channel permissions, and
custom templates.

## `dtk unlock --select <sel>`

Every run records a `running` lock in `_dtk_tasks` and clears it on exit. If a
run is killed mid-flight (commonly the **DB restarting mid-run**), the lock is
left behind and later non-`--force` runs fail with
`Failed to acquire lock … Use --force`. `dtk unlock` clears it immediately
without running the pipeline. (Stuck locks also auto-expire after ~1 hour, so
the next normal run recovers on its own.)

## `dtk clean`

Editing metrics over time leaves stale rows in the internal tables. `dtk clean`
removes that drift. **Both modes dry-run by default** — pass `--execute` to
actually delete.

- **Drift mode** — `dtk clean --select <sel>`: for each still-existing metric,
  deletes `_dtk_detections` rows for `detector_id`s the config no longer
  produces (you changed a detector param / `seasonality_components`, or removed
  a detector), and `_dtk_alert_states` rows for alert blocks the config no
  longer produces. Datapoints are never touched (keyed only by timestamp).
- **GC mode** — `dtk clean --orphaned-metrics`: deletes all internal rows for
  metric names present in the DB but no longer defined by any YAML (renamed or
  deleted metrics). Ignores `--select`; asks for confirmation on `--execute`
  unless `-y/--yes`; refuses to run if the project defines no metrics or configs
  fail to parse (so a wrong directory can't wipe valid data).

## Common workflows

```bash
# First run of a metric
dtk run --select my_metric

# Cron loop (every interval)
dtk run --select "*"
dtk run --select "tag:critical"

# Backfill history
dtk run --select my_metric --from "2024-01-01"
dtk run --select my_metric --from "2024-01-01" --to "2024-02-01"

# Reprocess after config changes
dtk run --select my_metric --full-refresh                 # query changed → reload
dtk run --select my_metric --steps detect --full-refresh  # detector changed → recompute detections
dtk clean --select my_metric                              # then prune orphaned old detector/alert rows
dtk clean --select my_metric --execute

# Debug
dtk run --select my_metric --steps load     # does the query return data?
dtk run --select my_metric --steps detect    # does the detector fire?
dtk test-alert my_metric                      # do the channels work?

# Recover a stuck lock
dtk unlock --select my_metric
```

## Scheduling

detectkit has no built-in scheduler — drive `dtk run` from cron / systemd
timers / Windows Task Scheduler. Always `cd` into the project first:

```cron
*/10 * * * * cd /path/to/project && dtk run --select "*" >> /var/log/detectkit.log 2>&1
```

Pair scheduling with `error_alerting` (in `detectkit_project.yml`) so in-process
failures page someone; cron monitoring covers `dtk run` not running at all.

## Troubleshooting

- **"Metric not found"** — selector doesn't match. Use the bare name
  (`cpu_usage`, not `cpu_usage.yml`) for root metrics; check `ls metrics/`.
- **"Failed to acquire lock"** — a crashed run left a lock. `dtk unlock --select <m>`
  (or wait ~1h for auto-expiry).
- **"Connection refused"** — check `profiles.yml` and DB connectivity.
- **"No data loaded"** — run the query manually with sample dates; verify the
  `{{ dtk_start_time }}` / `{{ dtk_end_time }}` filter.
- **All points "insufficient_data"** — not enough history before `min_samples`;
  lower `min_samples`, or backfill more history with `--from`.
