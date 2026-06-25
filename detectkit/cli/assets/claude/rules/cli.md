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
against labeled incidents; without it, an unsupervised objective is used.
`--dry-run` searches without writing. `--report [PATH]` writes the same
self-contained HTML report as `dtk run` for the tuned winner (default
`reports/<metric>__tuned_<id>.html`; `<dir>` or a `.html` file also accepted).
Full reference: `autotune.md`.

## `dtk tune --select <sel>`

The **manual, interactive** sibling of `dtk autotune`. Opens a localhost browser
view of the metric's **real** persisted series and lets you turn the detector's
knobs (type — including **Manual bounds** with lower/upper sliders — threshold,
window, recency weighting + half-life, detrend, smoothing, **seasonality groups**,
**direction** (both/up/down), alert `consecutive_anomalies`) while the confidence
band and flagged anomalies **recompute live**. The chart is **zoomable** (scroll/drag +
a navigator strip) and a **"Points shown"** slider trims the active sample to speed
up recompute on a long metric. Clicking **Apply** writes the chosen
config back into the metric YAML **in place** (autotune, by contrast, writes a new
`__tuned_<id>.yml` and never edits the original). Reads the metric's loaded
datapoints (run `dtk run --steps load` first if empty); the selector must resolve
to a single metric.

**Mark incidents + see alert quality live.** A second, **synced** chart beneath
the detector view lets you **mark the real incidents** (drag to create a span,
drag its edges/middle to adjust, ✕ or Delete to remove). As you tune, a metrics
bar shows two operator numbers: **incident catch rate (recall)** — how many marked
incidents your config catches — and **false-alert rate** — what share of alerts
fall outside any real incident ("≈1 in N false"). **Save incidents** writes a
versioned `incidents/<metric>/*.yml` — the same store `dtk autotune` reads, so the
same labels feed the next supervised tune (it seeds from the newest file on open).
Saving incidents does not end the session; only **Apply** does. A **y = 0 line**
toggle (shared with `dtk run --report`) shows the metric relative to zero.

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
