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
| `dtk ui` | Project-wide live overview + browser pipeline control panel + create/edit/delete metric YAMLs + per-metric Clean stale |
| `dtk test-alert <metric>` | Send a mock alert to the metric's channels |
| `dtk unlock --select <sel>` | Clear a stuck pipeline lock |
| `dtk clean --select <sel>` | Prune internal data that no longer matches the config |
| `dtk osi import <model>` | Scaffold a native metric from an OSI semantic-model metric (see "OSI interop") |
| `dtk osi export` | Publish metrics into an OSI fragment (config in `custom_extensions[detectkit]`) |
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
  `loading_start_time`; `--to` defaults to now. An explicit `--to` bypasses a
  configured `loading_delay` (trusted verbatim); to fix a bucket already
  loaded before `loading_delay` was set, `dtk run --from <date before it>`
  reloads and overwrites it.
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
knobs (type — including **Manual bounds** with lower/upper sliders and
**Autoreg** with a **Lags** knob (windowed-only knobs hide for it) — threshold,
window, recency weighting + half-life, detrend, stabilization, smoothing, **seasonality groups**,
**direction** (both/up/down), alert `consecutive_anomalies` plus the
**anomaly_window** / **min_anomaly_share** fraction pair) while the confidence
band and flagged anomalies **recompute live**. The whole screen is a **chart-first
cockpit**: ONE chart (the windshield) fills the view, the live metrics ride
**pinned in a HUD over the chart** (the speedometer), and every control lives in an
**always-visible, mode-aware side rail** beside the chart (Tune shows the detector
knobs + effective config + Apply, Review the verdict actions, Label the capture
tools + incident list + Save, Autotune the search button + winning config), while
the controls that aren't detector-specific —
the **Points shown** data window, the alert rule (**direction** + **consecutive
anomalies** + the **anomaly_window**/**min_anomaly_share** pair) and the
**y = 0** toggle — stay visible in every mode. The chart is
**zoomable** (scroll/drag + navigator strip) with a **"Points shown"** trim slider.
Trim it below what the detector needs to warm up (stabilization roughly doubles
it — Autoreg needs `2·window_size + lags`) and the chart dims completely with an
explanation plus an inline warning naming the shortfall and the fixes (raise
Points shown / lower window size / disable stabilization).
Clicking **Apply** writes the chosen
config back into the metric YAML **in place** (autotune, by contrast, writes a new
`__tuned_<id>.yml` and never edits the original). Apply **merges** — it rewrites
only the detector(s) you tuned and keeps every **other** detector unchanged, so a
`manual_bounds` floor alongside a `mad` detector (and a `min_detectors: 2` alert)
survives a retune. If a metric configures **more than one detector**, a **Tuning
detector** picker in the Tune rail lets you choose which one to tune (the cockpit
shows one band at a time); switching re-seeds every knob from that detector, and
non-tunable detectors (`prophet`/`timesfm`) plus the ones you didn't
touch are listed as "preserved on Apply". Reads the metric's loaded
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
launches the **real** `dtk autotune` engine **server-side** over the **window
currently shown** (the **Points shown** trim — the same series you see and score, not
the full history), using your marked incidents as ground truth, then **re-seeds every
knob** with the winner and shows the score + decision log; the band leads like Tune;
each run also streams a structured `LABELS → … → RESULT` log to the terminal, like
`dtk run`). The Autotune mode is **advisory** — it computes + re-seeds only and persists nothing (no
run record / `__tuned_<id>.yml` / detections, so `dtk tune` stays lock-free); review
the band and **Apply** to write it back. It honours the metric's `autotune:` block,
is supervised when incidents are marked (also sweeps the alert window —
`consecutive_anomalies` then the 2-D `anomaly_window` × `min_anomaly_share`
pair) else unsupervised, and needs the live server (unavailable under
`--no-serve`).
**Confirming an alert valid IS marking an
incident**: the confirmed streak becomes a first-class **ground-truth incident** that
shows in the Marked-incidents list (a read-only "✓ confirmed alert" row; its ✕
un-confirms the alert), counts toward recall + correct, and is written on Save — so a
clean metric whose alerts are all good is validated in a few clicks **without
hand-drawing spans**. The list, the live metrics and Save share **one** ground-truth
set (hand-marked spans **plus** confirmed-valid alerts, deduped by overlap).
**Deleting** an incident (the chart's ✕ / Delete key **or** the list's ✕) also
**retracts** any confirmed-valid alert verdict it overlapped, so it's fully removed
instead of reappearing as a "✓ confirmed alert" row — the chart-✕ and list-✕ behave
identically (a `false`-alarm verdict, and a confirmed alert that doesn't overlap the
deleted span, are left alone).
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
overwritten (the merge keeps your other detectors verbatim; the re-emitted header
names what was updated vs preserved). The `.history/` archive is **not** discovered
as a live metric, so a tuned metric never collides with its own snapshots as a
"duplicate metric name". Takes **no pipeline lock** (it only edits a config file);
re-run `dtk run` afterward to recompute detections under the new config.
`--no-serve` writes a static read-only preview HTML instead (no write-back —
**Save incidents** downloads the labels file); `--from` / `--to` bound the window;
`--no-open` prints the URL without opening a browser.

## `dtk ui`

A **project-wide** localhost cockpit over every selected metric's alerting
behavior — the live counterpart to a one-off `--report` file. Opens an
**overview** table (grouped by `metrics/` subfolder, filterable by tag) with,
per metric: alerts in the selected window + per-day rate + last alert,
no-data events, anomaly rate, data freshness, and a sparkline — all
**replayed** from stored detections through the same seam `dtk run --report`
uses, so the counts match what the pipeline would actually have alerted.
When `incidents/<metric>/` labels exist (from `dtk tune`'s Label/Review +
Save incidents), the row also shows recall / false-alert rate / reviewed,
matched the same way the `dtk tune` cockpit's metrics bar does; without
labels the row still shows frequency stats to eyeball.

```bash
dtk ui [-s/--select "*"] [--window 24h|7d|30d|90d|all] [--profile NAME] [--no-open]
```

- `--select` — same selector syntax as `dtk run`; scopes which metrics the
  overview and pipeline panel cover (default `*`, everything).
- `--window` — the preset selected when the page opens (default `30d`);
  switch freely in the browser afterward.
- `--profile` — forwarded to the DB connection **and** to every subprocess
  the pipeline panel spawns.
- `--no-open` — print the URL instead of opening a browser tab.

Clicking a metric's **Open** shows the existing self-contained HTML report
(the same one `--report` writes) in an overlay, whose header also has a
**Clean stale** button next to **Tune**: it previews a `dtk clean --select
<metric>` dry-run (superseded detector generations + row counts, stale
alert-state ids), and — if anything is stale — an amber confirm strip offers
**Delete stale data**, which spawns the real `dtk clean --select <metric>
--execute` as a job (`clean` kind) sharing the run/autotune/unlock gate below;
on success the report reloads and the overview's stale chip clears. This is
the drift-mode `dtk clean --select` from inside the UI; `--orphaned-metrics`
(renamed/deleted metrics) stays CLI-only. A **pipeline panel** drives
the real CLI as subprocesses — `dtk run` (select/steps/from/to/force/
full-refresh), `dtk autotune`, `dtk unlock` — streaming their terminal
output live; **only one `run`/`autotune`/`unlock`/`clean` job runs at a
time** (they'd contend for the same pipeline lock anyway). **Tune** launches `dtk tune --select
<metric>` for a metric and opens its cockpit in a new tab — unlike
run/autotune/unlock/clean, **multiple tune jobs run concurrently**, since each is
its own isolated, lock-free session. The `dtk ui` server itself takes **no
pipeline lock** and never mutates anything — every spawned command behaves
exactly as if typed into a terminal.

### Managing metrics from the UI

The cockpit header has a **New metric** button, and every metric row an
**Edit** action; both open an editor overlay with **two tabs sharing one
draft**: **Builder** — a structured form over the whole config (basics,
schedule/loading, seasonality, minimal detector rows with type + 1-2 key
params — fine-tuning belongs in `dtk tune` —, alerting with a channel
multi-select seeded from `profiles.yml` channel names, `ai_context`; SQL in
a syntax-highlighted pane, `query_file` paths read-only; a **From OSI**
sub-tab compiles a pasted OSI semantic-model metric through the same code
path as `dtk osi import`) — and **YAML**, the raw text, kept for whole-config
pastes. The last-edited tab wins, never silently: leaving an edited YAML tab
validates server-side first and blocks the switch on error; leaving an
edited Builder re-emits the YAML. A debounced live-validation chip re-checks
the draft while typing — showing the Builder's friendly checks while the
YAML tab still mirrors the form, and a one-line `field — reason` summary of
server errors otherwise. Keys the form doesn't model (`autotune:`, custom
templates, unknown detector types/params, a multi-entry alerting list)
round-trip verbatim, listed under "Preserved fields". Create writes
`metrics/[<folder>/]<name>.yml`; after a create, a **next-steps strip**
offers **Load & detect** (`dtk run --steps load,detect` for just that metric
— no alert step, so an untuned config can't spam a channel) and then **Open
tune** on the loaded series. **Save** validates
server-side **before any write**: YAML syntax → full `MetricConfig` → a deep
detector-params check (each factory-known detector is actually constructed) —
an invalid config lands in the editor's error pane with nothing written. A
successful save **archives the previous file verbatim** to
`metrics/.history/<metric>/` (the same archive `dtk tune`'s Apply writes,
excluded from metric discovery) and only then overwrites in place. A
YAML-tab save writes the text typed, comments intact (normalized only to end
with a newline); a Builder save **re-emits the YAML deterministically,
dropping hand-written comments** (the archive keeps the previous file; edit
comment-heavy files from the YAML tab). A save is refused when the file
changed on disk after the editor was opened (a `dtk tune` Apply or another
session saved first) — reopen the metric rather than overwrite it. A file
that doesn't parse opens YAML-only, with the parse error on the disabled
Builder tab. Renaming via `name:`
is allowed — uniqueness is enforced project-wide — and rows under the old name
stay in the `_dtk_*` tables until `dtk clean`. **Delete** lives in the edit
overlay behind an explicit confirmation step, and the server additionally
requires the request to echo the metric name back; it archives the file
(`…-deleted.yml`) before removing it, so a delete is reversible by hand, and
its `_dtk_*` rows likewise remain until `dtk clean`. While a `dtk tune` session
for that metric is running, Save and Delete are refused (its Apply would race
the edit). Like the rest of `dtk ui`, metric management takes no pipeline lock
and never touches the database — it only manages metric YAML files.

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
actually delete. Drift mode is also one click away, per metric, from `dtk
ui`'s detail overlay (**Clean stale**, next to Tune); `--orphaned-metrics`
stays CLI-only.

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

## OSI interop (`dtk osi`)

`dtk osi` converts between [Open Semantic Interchange](https://github.com/open-semantic-interchange/OSI)
(OSI) semantic models and native detectkit metrics. It's a **separate, additive**
layer: it never runs the pipeline, takes no lock, and the converter package
(`detectkit/semantic/`) is not imported by load/detect/alert — so it can't affect
a running project. OSI is treated as an *interchange* format (define the KPI once,
consume in BI + AI), not an execution engine. OSI adoption is still early, so the
broadly-useful piece today is `ai_context` (see the metrics rule) — the converters
are a forward bridge for teams that already run a governed semantic layer.

- `dtk osi import <model.osi.yml> --metric <name> --interval <grain>` — the
  "enhanced init": resolve one OSI metric and **scaffold a normal native metric**
  (SQL `query`, interval, a starter detector, the metric's `ai_context`). Review
  it, then commit like any hand-written metric. Targets:
  - `--target clickhouse` (default) — a direct `toStartOfInterval(...) GROUP BY`
    query from the dataset's physical `source` (ANSI→ClickHouse via **sqlglot**,
    the optional `[osi]` extra: `pip install 'detectkit[osi]'`).
  - `--target cube --cube <name> --time-field <dim>` — a Cube **SQL-API**
    `MEASURE(...)` query, so the metric runs through Cube and the alert matches a
    Cube dashboard's number by construction. Point its `profile` at a Postgres
    connection on Cube's SQL port.
- Only provably per-bucket-additive measures compile (`SUM`/`COUNT`/`COUNT(DISTINCT)`/
  `AVG`/`MIN`/`MAX` + ratios like `SUM(x)/NULLIF(COUNT(DISTINCT y),0)`). Window
  functions / non-aggregates / unknown aggregates are **refused** with a message
  to use `query_file:` — never a plausible-but-wrong series.
- `dtk osi compile <model> --metric <name> --interval <g>` prints just the SQL
  (for review). `dtk osi export [--select <sel>]` writes an OSI fragment carrying
  a lossless snapshot of the config in `custom_extensions[detectkit]` + the
  `ai_context` — a **one-way carrier** (`import` does not reconstruct from it; the
  metric YAML stays the source of truth).

```bash
dtk osi compile model.osi.yml -m total_sales -i 1h          # preview the SQL
dtk osi import model.osi.yml -m total_sales -i 1h -o metrics/  # scaffold a metric
dtk osi export -o semantic/detectkit.osi.yml                  # publish back to OSI
```

The `dtk ui` metric Builder's **From OSI** sub-tab does the import
interactively (paste a model, pick a metric/target, Compile) through the
same code path — see "Managing metrics from the UI" above.

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
