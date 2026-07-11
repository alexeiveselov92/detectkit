# CLI Reference

Complete reference for the `dtk` command-line tool.

## Overview

The `dtk` CLI provides dbt-like commands for managing metric monitoring:

```bash
dtk init <project>              # Initialize new project
dtk init-claude                 # Set up Claude Code context for this folder
dtk run --select <selector>     # Run metric pipeline
dtk autotune --select <sel>     # Auto-configure a metric's detector from data
dtk tune --select <sel>         # Interactively tune a detector, write it back
dtk ui [--select <sel>]         # Project-wide monitoring cockpit in the browser
dtk osi import|export|compile   # OSI semantic-model interop
dtk test-alert <metric>         # Test alert channels
dtk unlock --select <selector>  # Clear a stuck pipeline lock
dtk clean --select <selector>   # Prune data that no longer matches configs
dtk --version                   # Show version
dtk --help                      # Show help
```

## Global Options

### `--version`

Show the installed detectkit package version:

```bash
dtk --version
```

Output:
```
detectkit, version x.y.z
```

### `--help`

Show help for any command:

```bash
dtk --help
dtk run --help
dtk init --help
```

## Commands

### `dtk init`

Initialize a new detectkit project.

#### Syntax

```bash
dtk init <project_name> [OPTIONS]
```

#### Arguments

**`project_name`** (required)
Name of the project to create.

#### Options

**`--target-dir`, `-d`** (default: `.`)
Directory to create project in.

#### Examples

Create project in current directory:
```bash
dtk init my_monitoring
```

Create project in specific directory:
```bash
dtk init analytics --target-dir /opt/projects
```

#### Created Structure

```
my_monitoring/
├── detectkit_project.yml      # Project configuration
├── profiles.yml               # Database connections & alert channels
├── README.md                  # Getting-started notes for the project
├── metrics/                   # Metric definitions
│   ├── .gitkeep
│   └── example_cpu_usage.yml  # Example metric to copy/edit
├── incidents/                 # Labeled incidents for supervised `dtk autotune`
│   └── example_cpu_usage.yml  # Example labels file to copy/edit
└── sql/                       # SQL query files
    └── .gitkeep
```

---

### `dtk init-claude`

Set up [Claude Code](https://claude.com/claude-code) context for working with
detectkit. Run it in the folder that holds your detectkit project(s) — it gives
an AI assistant the context and tools to help you create metrics, tune
detectors, configure alerts and run the pipeline natively.

#### Syntax

```bash
dtk init-claude [OPTIONS]
```

#### Options

**`--target-dir`, `-d`** (default: `.`)
Folder holding your detectkit project(s) to set up.

#### Created / updated files

```
<target>/
├── CLAUDE.md                       # created, or a managed detectkit block is
│                                   #   injected/refreshed (your content is kept)
└── .claude/
    ├── rules/detectkit/            # reference docs the assistant reads on demand
    │   ├── alerting.md
    │   ├── autotune.md
    │   ├── cli.md
    │   ├── detectors.md
    │   ├── metrics.md
    │   ├── overview.md
    │   └── project.md
    └── skills/
        ├── dtk-autotune/           # skill: automatic detector/param search
        │   └── SKILL.md
        ├── dtk-feedback/           # skill: file a redacted bug/feature/feedback
        │   └── SKILL.md            #        issue upstream (with your confirmation)
        ├── dtk-new-metric/         # skill: scaffold a validated metric YAML
        │   └── SKILL.md
        ├── dtk-setup-project/      # skill: configure profiles.yml (DB + channels)
        │   └── SKILL.md
        └── dtk-tune/               # skill: hands-on interactive tuning cockpit
            └── SKILL.md            #        (autotune built in) + write-back
```

#### Behavior

- **Idempotent.** The detectkit block in `CLAUDE.md` lives between
  `<!-- BEGIN detectkit … -->` / `<!-- END detectkit -->` markers; re-running
  refreshes only that block and the managed files. Anything you write outside
  the markers is preserved. A re-run with no upstream change reports everything
  `unchanged`.
- **Versioned.** The content ships with detectkit and tracks the installed
  version, so **re-run `dtk init-claude` after upgrading** to refresh the
  guidance to match the new release.
- Works whether the folder holds one project or several side by side.

#### Examples

```bash
# Set up the current folder
dtk init-claude

# Set up a specific monitoring root
dtk init-claude --target-dir /opt/monitoring
```

After running, open the folder in Claude Code and ask it about your metrics,
alerts or configs. Five skills come with it: **`dtk-setup-project`** (configure
`profiles.yml` — the database connection and a first alert channel — so runs
work end to end), **`dtk-new-metric`** (scaffold a validated metric YAML),
**`dtk-tune`** (dial in a detector by hand in the interactive
[`dtk tune`](#dtk-tune) browser cockpit — with autotune built in — and write it
back), **`dtk-autotune`** (search for the best detector, seasonality and
parameters automatically), and **`dtk-feedback`** (file a bug report, feature
request, or feedback as a GitHub issue on the upstream repo — it collects the
diagnostic context, redacts every secret, and asks you to confirm before
submitting).

---

### `dtk run`

Run the metric processing pipeline.

#### Syntax

```bash
dtk run --select <selector> [OPTIONS]
```

#### Options

##### `--select`, `-s` (required)

Selector for metrics to run. Three selector types are supported:

**1. Metric name** (searches only root `metrics/` directory):
```bash
dtk run --select cpu_usage          # Finds metrics/cpu_usage.yml
dtk run --select api_latency        # Finds metrics/api_latency.yml
```

Note: When using metric name (without path separators), **do not** include `.yml` extension. The extension is added automatically.

**2. Path pattern** (glob - supports subdirectories):
```bash
# Select specific file with full path
dtk run --select "metrics/critical/cpu.yml"

# Select all metrics in a folder
dtk run --select "metrics/critical/*"

# Select all metrics recursively
dtk run --select "metrics/**/*.yml"

# Pattern matching
dtk run --select "api_*"            # All metrics starting with "api_"
```

**3. Tag selector** (searches recursively):
```bash
# Select all metrics with "critical" tag
dtk run --select tag:critical

# Select metrics tagged as "api"
dtk run --select tag:api

# Select metrics tagged as "10min"
dtk run --select tag:10min
```

Tags must be configured in metric YAML files:
```yaml
name: api_latency
tags: ["critical", "api", "10min"]
# ... rest of config
```

**Uniqueness validation**: All selected metrics are validated to ensure no duplicate metric names exist. If duplicates are found, an error is raised listing the conflicting files.

##### `--exclude`, `-e` (optional)

Selector for metrics to exclude.

```bash
dtk run --select "*" --exclude "metrics/staging/*"
```

##### `--steps` (default: `load,detect,alert`)

Pipeline steps to execute.

**Available steps**:
- `load` - Load data from database
- `detect` - Run anomaly detection
- `alert` - Send alerts

**Examples**:
```bash
# All steps (default)
dtk run --select cpu_usage

# Load only
dtk run --select cpu_usage --steps load

# Detect and alert (skip load)
dtk run --select cpu_usage --steps detect,alert

# Detect only (no load, no alert)
dtk run --select cpu_usage --steps detect
```

##### `--from` (optional)

Start date for data loading.

**Format**: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`

```bash
# Load from January 1, 2024
dtk run --select cpu_usage --from "2024-01-01"

# Load from specific timestamp
dtk run --select cpu_usage --from "2024-01-01 12:00:00"
```

**Behavior**:
- Overrides metric's `loading_start_time` config
- Only affects `load` step
- Timestamps are in UTC

##### `--to` (optional)

End date for data loading.

**Format**: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`

```bash
# Load up to February 1, 2024
dtk run --select cpu_usage --from "2024-01-01" --to "2024-02-01"
```

**Behavior**:
- Defaults to current time if not specified
- Only affects `load` step
- Timestamps are in UTC
- An explicit `--to` is trusted verbatim — it bypasses a configured
  [`loading_delay`](../guides/configuration-metrics.md#loading_delay-string-or-int-optional)
  (which only shifts the implicit "now" bound). If a bucket was already
  persisted before `loading_delay` was configured, `dtk run --from <date
  before that bucket>` reloads and overwrites it.

##### `--full-refresh` (flag)

Delete existing data and reload from scratch.

```bash
dtk run --select cpu_usage --full-refresh
```

**Behavior** (delete/reload is **range-scoped** to `--from`/`--to`):
1. Deletes `_dtk_datapoints` and `_dtk_detections` rows in the `[--from, --to)`
   window — and **all** history only when neither `--from` nor `--to` is given
   (detect uses `--to` or now as the upper bound when `--to` is omitted)
2. Reloads data from `--from` (or `loading_start_time` when no `--from`) up to
   `--to` (or now)

**Use cases**:
- Fixing corrupted data
- Changing data loading logic
- Reprocessing with new detector configuration

**Warning**: This is a destructive operation. Use with caution.

##### `--force` (flag)

Ignore an existing task lock and run anyway.

```bash
dtk run --select cpu_usage --force
```

**Behavior**:
- Skips the held-lock check (runs even if another lock is marked `running`)
- Still takes ownership of the lock for the duration of the run **and releases
  it on exit** — so a `--force` run also clears a previously stuck lock
- Allows concurrent runs (not recommended)

**Warning**: Can cause data corruption if multiple processes run simultaneously.

> **Note:** You usually don't need `--force` to recover from a crash. A
> `running` lock left behind by a dead process (e.g. the database restarted
> mid-run) auto-expires after its timeout (1 hour) and is overridden by the
> next normal run. To clear a stuck lock immediately, use
> [`dtk unlock`](#dtk-unlock) instead of `--force`.

##### `--profile` (optional)

Override the default profile from project config.

```bash
dtk run --select cpu_usage --profile staging
```

**Use cases**:
- Testing with different database
- Running against multiple environments

##### `--report` (optional, dual-mode)

After the run, write a **self-contained HTML report** per selected metric —
values, each detector's confidence band, the flagged anomalies, the alerts that
fired (anomaly / recovery / no-data) and a summary, with a client-side period
selector (24h / 7d / 30d / All + zoom/pan). The report is offline: the chart and
data are inlined into one file, so nothing is fetched and nothing leaves the
page.

```bash
# Default path: reports/<metric>.html
dtk run --select cpu_usage --report

# Into a directory: <dir>/<metric>.html
dtk run --select cpu_usage --report reports/

# Into a specific file
dtk run --select cpu_usage --report cpu.html
```

**Behavior**:
- Bare `--report` → `reports/<metric>.html`; a **directory** → `<dir>/<metric>.html`;
  a `.html` path → that exact file.
- Reads the persisted `_dtk_datapoints` / `_dtk_detections`, so it works even on a
  `--steps load` (or any partial) run, charting whatever is already stored.
- Best-effort: a report failure is reported and **does not** fail the run.

> **Advanced — alerts are reconstructed, not read from state.** `_dtk_alert_states`
> stores last-writer-wins cooldown/recovery bookkeeping, not an event log, so the
> report cannot read past alerts from it. Instead it **replays** the real decision
> logic (quorum, `consecutive_anomalies`, cooldown, recovery, no-data) over the
> stored detections to reconstruct the timeline. This is faithful to the rules,
> but because cooldown suppression depends on **when** the live pipeline ran
> (run cadence), the set of *suppressed* repeat alerts a live run dispatched can
> differ slightly from the replay, which evaluates every grid point causally.
> The anomalies, bands, and which incidents fired are unaffected.

#### Metric Selection Rules

Understanding how metric selection works is important to avoid confusion:

##### File Name vs Metric Name

**Two different identifiers**:
1. **File name** (e.g., `metrics/cpu.yml`) - where config is stored
2. **Metric name** (e.g., `name: cpu_usage` in YAML) - identifier used in database

**Important**: detectkit uses **metric name** (from config) for all operations:
- Database table rows are keyed by `metric_name`
- Task locking uses `metric_name`
- Display shows `metric_name` (not file name)

**Best practice**: Keep file names and metric names consistent:
```yaml
# File: metrics/cpu_usage.yml
name: cpu_usage    # Matches file name (recommended)
```

```yaml
# File: metrics/cpu.yml
name: server_cpu_usage    # Confusing - file name doesn't match
```

##### Uniqueness Requirements

**Metric names MUST be unique** across the entire project.

**Why uniqueness matters**:
- Database tables use `metric_name` as PRIMARY KEY component
- Duplicate names cause data to mix from different sources
- Task locking conflicts prevent metrics from running
- Anomaly detection becomes invalid (mixed data)

**Example of invalid configuration**:
```yaml
# metrics/api/cpu.yml
name: cpu_usage          # Duplicate name!
query: "SELECT * FROM api_metrics"

# metrics/system/cpu.yml
name: cpu_usage          # Same name causes data corruption!
query: "SELECT * FROM system_metrics"
```

**Validation**: detectkit automatically validates uniqueness when selecting metrics. If duplicates are found:
```
Error: Duplicate metric name 'cpu_usage' found:
  - metrics/api/cpu.yml
  - metrics/system/cpu.yml

Metric names must be unique across the project.
Please rename one of the metrics to avoid data corruption.
```

**Solution - use unique names**:
```yaml
# metrics/api/cpu.yml
name: api_cpu_usage      # Unique

# metrics/system/cpu.yml
name: system_cpu_usage   # Unique
```

##### Selector Behavior Summary

| Selector Type | Example | Searches | Extension |
|--------------|---------|----------|-----------|
| Metric name | `cpu_usage` | Root `metrics/` only | Auto-added |
| Path with `/` | `metrics/api/cpu.yml` | Glob pattern | Keep as-is |
| Pattern with `*` | `api_*` | Glob pattern | Keep as-is |
| Tag | `tag:critical` | Recursive search | N/A |

**Common mistakes**:
- `dtk run --select cpu_usage.yml` → Won't work (searches for `metrics/cpu_usage.yml.yml`)
- `dtk run --select cpu_usage` → Correct (searches for `metrics/cpu_usage.yml`)
- `dtk run --select "metrics/cpu_usage.yml"` → Also works (explicit path)

#### Examples

##### Basic Usage

Run single metric:
```bash
dtk run --select cpu_usage
```

Run all metrics:
```bash
dtk run --select "*"
```

Run metrics matching pattern:
```bash
dtk run --select "api_*"
```

##### Partial Pipeline

Load data only (skip detection):
```bash
dtk run --select cpu_usage --steps load
```

Run detection only (skip load and alert):
```bash
dtk run --select cpu_usage --steps detect
```

Run detection and alert (skip load):
```bash
dtk run --select cpu_usage --steps detect,alert
```

##### Historical Backfill

Load data from specific date:
```bash
dtk run --select cpu_usage --from "2024-01-01"
```

Load specific date range:
```bash
dtk run --select cpu_usage \
  --from "2024-01-01" \
  --to "2024-02-01"
```

##### Full Refresh

Delete and reload all data:
```bash
dtk run --select cpu_usage --full-refresh
```

Full refresh with custom start date:
```bash
dtk run --select cpu_usage \
  --full-refresh \
  --from "2024-01-01"
```

##### Multiple Metrics

Run multiple metrics by pattern:
```bash
dtk run --select "metrics/critical/*.yml"
```

Run all except staging:
```bash
dtk run --select "*" --exclude "metrics/staging/*"
```

##### Different Environment

Run against staging database:
```bash
dtk run --select cpu_usage --profile staging
```

##### Force Run (Emergency)

Force run if previous run crashed:
```bash
dtk run --select cpu_usage --force
```

#### Output

Each run renders as a load → detect → alert tree per metric:
```
Project root: /path/to/project
Found 1 metric(s) to process

Processing metric: cpu_usage
  Config file: metrics/cpu_usage.yml
  Steps: load, detect, alert

  ┌─ LOAD
  │ Resuming from last saved: 2024-03-15 09:50:00
  │ Loading from 2024-03-15 10:00:00 to 2024-03-15 10:00:00
  │ Total points: ~1,440 | Batch size: 2,160
  │ Loading in single batch...
  └─ Loaded 1,440 datapoints

✓ Pipeline completed successfully
```

On failure the tree ends with a red `✗ Failed: …` line instead of
`✓ Pipeline completed successfully`.

---

### `dtk autotune`

Automatically configure a metric's detector from its data — and, if you supply
them, from labeled incidents. Searches detector type × hyperparameters ×
seasonality grouping × history window (× alert window, when supervised),
cross-validates each candidate with walk-forward folds, and writes a **new,
annotated** metric YAML. It is a separate pipeline from `load → detect → alert`:
it never edits the original config and never sends alerts.

#### Syntax

```bash
dtk autotune --select <selector> [OPTIONS]
```

#### Options

##### `--select`, `-s` (required)

Metric selector — same semantics as [`dtk run`](#dtk-run) (metric name, path
pattern, or `tag:<name>`). Tuning reads the metric's **already-loaded**
`_dtk_datapoints`; if it has none yet, load it first (optionally backfill more
history, which tunes better):

```bash
dtk run --select api_error_rate --steps load --from "2026-01-01"
```

##### `--incidents` (optional)

Path to a labels file **or** the `incidents/<metric>/` directory of known
incidents → **supervised** tuning. You don't usually need it: `dtk autotune`
**auto-discovers** the newest labels in `incidents/<metric>/`, so after marking
incidents in [`dtk tune`](#dtk-tune) (Label / Review mode → **Save incidents**)
you just run `dtk autotune --select <metric>`. Resolution precedence is:
`--incidents` flag > config `labels_file` > inline config `incidents` >
auto-discovered `incidents/<metric>/` > interactive prompt > none
(unsupervised). When none of those resolve and the terminal is interactive, a
prompt first offers to enter incidents inline; declining — or running
non-interactively (cron/CI/piped input) — falls back to an **unsupervised**
objective (low false-positive rate + stable cross-fold separation). Supervised
mode engages only if labeled timestamps land on **loaded** grid points. The file
is YAML or JSON, all times UTC, each incident an interval (`{start, end}`) or a
point (`{at}`):

```yaml
metric: api_error_rate          # optional; must match the metric being tuned
timezone: UTC                   # optional; interprets the naive times below
incidents:
  - {start: "2026-05-02 14:00:00", end: "2026-05-02 16:30:00"}
  - {at: "2026-05-11 09:05:00"}
```

```bash
dtk autotune --select api_error_rate --incidents incidents/api_error_rate.yml
```

##### `--scoring` (default: `mcc`)

The metric the search maximizes across folds: `mcc` (default), `f1`, `f_beta`,
`balanced_accuracy`, `roc_auc`, `pr_auc`, `event_f1`. MCC uses the whole
confusion matrix and suits rare anomalies; `event_f1` is segment-aware — one
flagged point anywhere inside a labeled incident counts the whole incident
caught — see the [scoring-metrics catalog](autotune.md#scoring-metrics).

```bash
dtk autotune --select api_error_rate \
  --incidents incidents/api_error_rate.yml \
  --scoring f_beta
```

##### `--from` (optional)

Lower bound of the training window (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`, UTC).

##### `--to` (optional)

Upper bound of the training window (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`, UTC).

##### `--profile` (optional)

Override the default profile from the project config.

##### `--force` (flag)

Ignore an existing task lock and run anyway (same lock semantics as
[`dtk run --force`](#-force-flag)).

##### `--dry-run` (flag)

Run the search but **persist nothing** — no config, no detections, no
`_dtk_autotune_runs` row. Previews what autotune would choose.

##### `--report` (optional, dual-mode)

Write the same **self-contained HTML report** as
[`dtk run --report`](#-report-optional-dual-mode) for the **tuned winner** —
values, the chosen detector's confidence band, the
flagged anomalies, the alerts that would have fired, and a summary, with the
client-side period selector. It charts the winner's detections (persisted during
the run), so run without `--dry-run`.

```bash
# Default path: reports/<metric>__tuned_<id>.html
dtk autotune --select cpu_usage --report

# A directory, or a specific file
dtk autotune --select cpu_usage --report reports/
dtk autotune --select cpu_usage --report cpu_tuned.html
```

Bare `--report` → `reports/<metric>__tuned_<id>.html`; a directory →
`<dir>/<metric>.html`; a `.html` path → that file. The same **Advanced** note as
`dtk run --report` applies: alerts in the report are reconstructed by replaying
the decision logic over the stored detections.

#### Behavior

On success (without `--dry-run`), one run:

- writes `metrics/<name>__tuned_<id>.yml` — a normal, ready-to-run config led by
  a `#` comment header explaining every decision (training period, labels,
  seasonality rationale, detector votes, grid-search winner + CV score +
  per-fold scores, window choice). The `<id>` is a deterministic hash of the run.
- records one row in the `_dtk_autotune_runs` audit table;
- persists the winning detector's detections to `_dtk_detections`;
- prunes the superseded winners from prior autotune runs of the same metric.

The tuned config is an ordinary metric. **Hand-editing its detector changes the
`detector_id`**, orphaning the old detections — recompute and prune:

```bash
dtk run --select <name>__tuned_<id> --steps detect --full-refresh
dtk clean --select <name>__tuned_<id> --execute
```

See the [Auto-tuning guide](../guides/autotuning.md) and the
[Auto-tune reference](autotune.md) for the labels schema, the `autotune:` config
block, the scoring-metrics catalog, and the `_dtk_autotune_runs` columns.

---

### `dtk tune`

Interactively tune a metric's detector on its **real** data, then write the
chosen config back into the metric YAML. The manual, human-in-the-loop sibling of
[`dtk autotune`](#dtk-autotune): it opens a browser view of the metric's persisted
series, lets you turn the detector's knobs and watch the confidence band + flagged
anomalies + would-fire alerts **recompute live**, and — on a click — applies the
config. Where `autotune` searches automatically and writes a *new*
`__tuned_<id>.yml`, `tune` is manual and edits the metric **in place**.

Safe by construction: the new config is validated before anything is written, the
previous metric YAML is archived under `metrics/.history/<metric>/`, and only then
is the metric overwritten. It takes **no pipeline lock** (it only edits a config
file); re-run `dtk run` afterwards to recompute detections under the new config.

#### Syntax

```bash
dtk tune --select <selector> [OPTIONS]
```

#### Options

##### `--select`, `-s` (required)

Metric selector — same semantics as [`dtk run`](#dtk-run), but it must resolve to
a **single** metric (tuning is interactive and per-metric). Tuning reads the
metric's **already-loaded** `_dtk_datapoints`; if it has none yet, load it first:

```bash
dtk run --select api_error_rate --steps load --from "2026-01-01"
```

##### `--from`, `--to` (optional)

Restrict the window the tuner shows and recomputes over (`YYYY-MM-DD` or
`YYYY-MM-DD HH:MM:SS`, UTC). Defaults to the recent persisted window.

##### `--no-serve` (flag)

Write a static, read-only tuner HTML file (`metrics/<metric>__tuner.html`) and
exit instead of starting the local server. The sliders still recompute the band
live and you can still mark incidents, but there is **no Apply / write-back** —
**Save incidents** downloads the labels file instead of writing it.

##### `--no-open` (flag)

Don't auto-open the browser — just print the local `127.0.0.1` URL.

##### `--profile` (optional)

Profile override (default: from the project config).

#### What you can tune

Detector **type** (MAD / Z-Score / IQR / Manual bounds / Autoreg), **threshold**,
**window size**, recency **weighting** + **half-life**, **detrend**,
**stabilization**, **smoothing**, **seasonality conditioning** (per available
seasonality column, optionally conjoined into one group) — these windowed-only
knobs hide when Autoreg is selected, which instead exposes **lags** (AR order) —
**direction** (both/up/down) and the alert window: **`consecutive_anomalies`**
plus the fraction-window pair, **anomaly window (points)** and **min share in
window**. The "effective config" readout shows exactly what will be written. A
**y = 0 line** toggle shows the metric relative to zero.

#### Chart-first cockpit: modes, alert review & metrics

The whole screen is **one chart** (the windshield) with the live metrics pinned in
a HUD over it (the speedometer) and every control in an **always-visible side rail**
that is **mode-aware** — it shows only the current mode's panel (detector knobs +
effective-config readout + Apply in Tune, verdict actions in Review, capture tools +
Save in Label, the search button + winner in Autotune) and collapses to give the
chart the whole width. The controls that
aren't detector-specific — the **Points shown** data window, the alert rule
(**direction** + **consecutive anomalies** + the **anomaly-window/min-share**
pair) and the **y = 0** toggle — stay visible in every mode. A **mode switch**
picks the job and dims the layers that don't matter to it:

- **Tune** — steer the band (corridor leads; incidents are read-only context; hover
  a point for its window).
- **Review** — confirm the fired alerts: **click an alert marker** to cycle its
  verdict un-reviewed (red) → **valid** (green) → **false alarm** (slate); **Confirm
  all unreviewed valid** does the lot. **Confirming an alert valid IS marking an
  incident** — the confirmed streak becomes a first-class incident that shows in the
  **Marked incidents** list (a "✓ confirmed alert" row; remove it to un-confirm),
  counts toward recall + correct (so a clean metric is validated in a few clicks
  **without drawing spans**), and is written as an incident on Save. The list, the
  metrics and Save share one ground-truth set (marked spans + confirmed alerts).
- **Label** — mark real incidents: **drag** a span (edges/middle to adjust, ✕/Delete
  to remove — removing also un-confirms any overlapping confirmed-valid alert, so the
  incident is fully gone rather than reappearing as a "✓ confirmed alert" row, with
  the chart ✕ and list ✕ behaving identically), **Lasso anomalies** (loop a cloud of anomaly dots — each consecutive
  run, gaps bridged up to `consecutive_anomalies`, becomes one span sized to the
  run), or **Threshold capture** (grab every span past a horizontal line; set it by
  click or value, **above**/**below**, optional gap-bridge, optional painted time
  window saved as `capture_windows`; each span widened to a full interval so the
  alert lands inside).
- **Autotune** — **Run autotune** launches the [`dtk autotune`](autotune.md) engine
  **server-side** over the **window currently shown** (the **Points shown** trim — the
  same series you see and score here, not the full history), using your marked
  incidents as ground truth, then **re-seeds every knob** with the winning detector and
  shows the score + decision log; the chart leads with the band, like Tune. The run
  streams a structured, blocked log to the terminal you launched `dtk tune` from (the
  same `LABELS → … → RESULT` format as `dtk run` / `dtk autotune`), so you can watch
  what it computes. It is **advisory**
  — it computes + re-seeds only and writes nothing until you **Apply** (no run record
  / `__tuned_<id>.yml` / persisted detections, so `dtk tune` stays lock-free). It
  honours the metric's `autotune:` block, runs **supervised** when incidents are
  marked (also sweeping the alert window — `consecutive_anomalies` then the 2-D
  `anomaly_window` × `min_anomaly_share` pair) else **unsupervised**, and needs
  the live server (unavailable under `--no-serve`).

As you tune, a metrics bar shows **incident catch rate (recall)** — the share of
ground-truth incidents (marked + confirmed-valid alerts) caught by an alert (caught
when an alert's anomaly **streak overlaps** it, not just the fire instant) —
**false-alert rate** — the share of fired alerts outside every incident and not
confirmed valid ("≈1 in N false") — and **reviewed N/M**; only incidents within the
loaded window are scored. An optional **false-alert budget** (`false_alert_budget`, a
fraction in `(0, 1]` on the **metric** then **project**, default `0.5`) gently flags
the false-alert chip when the rate exceeds it — tuning-only, labeling stays optional.
**Save incidents** writes
a versioned `incidents/<metric>/<…>.yml`, the **same store
[`dtk autotune`](#dtk-autotune) reads** (it seeds incidents *and* capture windows
from the newest such file on open, **anchoring the budget-sized loaded window on
the seeded incidents** — ending just past the latest one rather than at the last
datapoint — so they render and count without loading the whole history; older
incidents stay list-only, use `--from`/`--to` to tune against them; per-alert
verdicts persist as an `alert_reviews` metadata block and re-seed on reopen), so a
labeling round here also feeds the next supervised tune. Saving incidents does not
end the session; only **Apply** does.

#### How Apply writes back

On **Apply to metric** detectkit validates the chosen detector and the whole metric config (with the same validation the pipeline uses) — a broken or untunable
config is rejected and nothing is written — then archives the current YAML
verbatim to `metrics/.history/<metric>/<metric>-<timestamp>.yml` and re-emits the
metric in place, **merging** the tuned detector(s) back in: only the detector(s)
you tuned are rewritten and every **other** detector (a `manual_bounds` floor, a
`prophet`/`timesfm` detector, another windowed one) is preserved
**verbatim** — so a `min_detectors: 2` alert isn't silently broken by a retune. The first `alerting`
block's `consecutive_anomalies` and the `anomaly_window`/`min_anomaly_share`
pair are updated if present (the pair is removed together when turned off —
never a half-pair), and the re-emitted header names what was updated vs
preserved. For a metric with more than one detector, a
**Tuning detector** picker chooses which one to tune. The archive keeps a trackable
history of chosen parameters, is **excluded from metric discovery** (so a tuned
metric never collides with its own snapshots as a duplicate name), and the original
is always recoverable.

#### Examples

```bash
# Tune interactively and apply on click
dtk tune --select api_error_rate

# Tune over a specific window
dtk tune --select api_error_rate --from 2026-05-01 --to 2026-06-01

# Static, read-only preview file (no write-back)
dtk tune --select api_error_rate --no-serve
```

See the [Tuning guide](../guides/tuning.md) for the full walkthrough and how it
relates to `dtk autotune`.

---

### `dtk ui`

Open an interactive, **project-wide** localhost cockpit: one overview of every
selected metric's alerting behavior (grouped by `metrics/` subfolder,
filterable by tag), a per-metric detail view (the existing HTML report in an
overlay), a pipeline panel that drives `dtk run` / `dtk autotune` /
`dtk unlock` as subprocesses — plus a **Tune** action that launches
[`dtk tune`](#dtk-tune) for a metric in a new tab — and **New metric** /
**Edit** actions that create, edit, and delete metric YAML files straight from
the browser (see [Managing metrics](#managing-metrics) below). Like
`dtk tune`, it is a *superstructure* over the existing commands and files: the
server never runs the pipeline in-process, takes **no pipeline lock**, and
never touches the database — every pipeline action it drives is the same
subprocess you'd run from a terminal, streamed back into the page, and every
metric-file write goes through the same validate-before-write discipline
`dtk tune`'s Apply uses.

#### Syntax

```bash
dtk ui [OPTIONS]
```

#### Options

##### `--select`, `-s` (default: `*`)

Metric selector — same semantics as [`dtk run`](#dtk-run) (metric name, path
pattern, or `tag:<name>`). Scopes which metrics the overview and the pipeline
panel cover.

```bash
dtk ui --select tag:critical
```

##### `--window` (default: `30d`)

The window preset selected when the page first opens: `24h`, `7d`, `30d`,
`90d`, or `all`. You can switch presets live in the browser afterward — this
only sets the initial one. An invalid value is rejected before the server
starts.

```bash
dtk ui --window 7d
```

##### `--no-open` (flag)

Don't auto-open the browser — just print the local `127.0.0.1` URL (mirrors
`dtk tune --no-open`).

##### `--profile` (optional)

Profile override (default: from the project config). Also forwarded to every
subprocess the pipeline panel spawns (`dtk run`, `dtk autotune`,
`dtk unlock`), so they run against the same database as the UI itself.

```bash
dtk ui --profile staging
```

#### What the overview shows

Computed fresh per request from the persisted `_dtk_*` tables — not cached —
for the selected window:

- **Alerts in window** (anomaly / recovery / no-data), **per-day rate**, and
  **last alert** timestamp. Counts are **replayed** from stored detections
  through the same pure `AlertOrchestrator.replay` logic
  [`dtk run --report`](#-report-optional-dual-mode) uses, so they match what
  the pipeline would actually have alerted.
- **Anomaly rate** — the share of scored points flagged by any configured
  detector (a union — a two-detector metric isn't double-counted).
- **Data freshness** — how stale the last datapoint is relative to the
  metric's interval, plus whether the metric's pipeline lock is currently
  held.
- **A sparkline** of the window's values with anomalous points marked.
- **Quality chips** (recall, false-alert rate, reviewed) — only when
  `incidents/<metric>/` labels exist (the same store [`dtk tune`](#dtk-tune)'s
  Label/Review + Save incidents writes), matched on alert **streak-span
  overlap** exactly like the `dtk tune` cockpit's metrics bar. Without labels,
  a metric still shows its frequency stats — labeling is optional grounding,
  never a requirement.

Metrics are grouped by their `metrics/` subfolder and filterable by tag.
Opening a metric shows the **existing self-contained HTML report** — the same
one `dtk run --report` writes — in an overlay; nothing is regenerated, it
reads the same persisted rows the overview did.

#### Pipeline panel

A side panel drives the real CLI commands as subprocesses and streams their
output live into the page:

- **`dtk run`** — select, steps (load/detect/alert), `--from`/`--to`,
  `--force`, `--full-refresh`.
- **`dtk autotune`** — select, `--from`/`--to`.
- **`dtk unlock`** — select.
- **Tune** — launches `dtk tune --select <metric>` for one metric and opens
  its cockpit in a new browser tab.

Only **one** `run` / `autotune` / `unlock` job runs at a time — starting a
second while one is in flight is refused, so two pipeline jobs from the panel
can never race the same database connection. **`dtk tune` jobs are the
exception**: several run concurrently (one per metric you're tuning), since
each opens its own isolated, lock-free tuning server.

The pipeline panel itself takes **no pipeline lock** and never mutates
anything on its own — it only spawns and streams these commands. Every spawned
command takes (and releases) its own lock exactly as it would from a
terminal, so the pipeline panel is a convenience layer, not a different code
path. (The metric-management routes below are a separate, file-only mutation
path — they never touch the database.)

#### Managing metrics

The header's **New metric** button and each metric row's **Edit** action open
a full-screen editor over the metric's raw YAML — a text-in, text-out model
that mirrors `dtk tune`'s config write-back, extended to the whole file:

- **New metric** opens the editor seeded with a starter YAML template plus an
  optional folder field. **Create metric** validates server-side and writes
  `metrics/[<folder>/]<name>.yml` (the filename is derived from the metric's
  `name:`). The new metric joins the current session immediately, even if it
  wouldn't match the `--select` the server was started with.
- **Edit** opens a metric's existing YAML verbatim in the same editor.
  **Save changes** validates, then **archives the previous file verbatim** to
  `metrics/.history/<metric>/<metric>-<stamp>.yml` — the same archive
  `dtk tune`'s Apply uses, excluded from metric discovery — and overwrites the
  file in place: the text you typed lands on disk, comments intact (no
  re-emit; the only normalization is ensuring a trailing newline). A save is
  refused if the file changed on disk after the editor was opened (a
  `dtk tune` Apply or another editor session landed first) — reopen the
  metric instead of silently overwriting the newer version. Renaming a metric
  (changing `name:`) is allowed; uniqueness is
  enforced against the whole project, and a rename leaves the old name's rows
  in the `_dtk_*` tables until `dtk clean` prunes them.
- **Delete metric** lives inside the edit overlay behind an explicit
  confirmation step; the server additionally requires the request to echo the
  metric name, so nothing deletes on a stray click. Deleting archives the
  file to `metrics/.history/<metric>/<metric>-<stamp>-deleted.yml` and then
  removes it — the metric's rows stay in the `_dtk_*` tables until
  `dtk clean` prunes them, and the archived copy makes the delete reversible
  by restoring it.
- **Validation is strict and server-side, before any write**: YAML syntax,
  then full `MetricConfig` validation, then a deep detector-params check
  (constructing each configured detector). An invalid config returns the
  validation error into the editor's error pane and writes nothing.
- **Guard against a running tune session**: while a `dtk tune` session for the
  metric is running (launched from the UI), Save/Delete for that metric are
  refused — a concurrent Apply from the tuner would race the edit.

`dtk ui` still takes **no** pipeline lock, and these routes never touch the
database — they only read and write metric YAML files under `metrics/`.

#### Examples

```bash
# Open the overview for the whole project
dtk ui

# Restrict to metrics tagged "critical"
dtk ui --select tag:critical

# Open with a 7-day window instead of the 30-day default
dtk ui --window 7d

# Don't auto-open a browser tab (e.g. over SSH)
dtk ui --no-open

# Point at a specific profile (also used by spawned dtk run/autotune/unlock)
dtk ui --profile staging
```

See the [Project UI guide](../guides/project-ui.md) for the full walkthrough.

---

### `dtk test-alert`

Send test alert for a metric.

#### Syntax

```bash
dtk test-alert <metric_name> [OPTIONS]
```

#### Arguments

**`metric_name`** (required)
Name of the metric to test alerts for.

#### Options

**`--profile`** (optional)
Profile to use (overrides project default).

#### Examples

Test alert for single metric:
```bash
dtk test-alert cpu_usage
```

Test with specific profile:
```bash
dtk test-alert cpu_usage --profile production
```

#### Behavior

Sends a mock alert through all configured channels with fake data:
- Current timestamp
- Mock anomaly value: `0.8532`
- Mock confidence interval: `[0.4521, 0.6234]`
- Mock severity: `4.52`
- Rule preview: the mock mirrors the alert config's own `min_detectors`,
  `direction`, and `consecutive_anomalies` (defaults `1` / `same` / `3`), so
  the message shows the alert-centric layout a real firing would produce
- Project label: the preview carries the project-name `[name]` prefix (from
  `detectkit_project.yml`), exactly as a real `dtk run` stamps it — so a preview
  on a shared multi-project channel reads identically to the real alert

**Use cases**:
- Verify webhook URLs work
- Check alert formatting
- Test custom templates
- Validate channel permissions

#### Example Output

```
📨 Sending test alert for metric: cpu_usage
   Timezone: UTC
   Channels: mattermost_ops

   → Sending to mattermost_ops... ✓ SUCCESS

✓ Sent test alert to 1/1 channels

💡 Check your configured channels to verify message formatting
   Mock data used: value=0.8532, confidence=[0.4521, 0.6234], severity=4.52
```

When the metric defines **multiple** enabled alerting blocks (the list form),
each block is tested independently: its `Timezone`/`Channels` are printed under
a `[config i/N]` header, followed by a combined `Total: x/y channels across N
alert configs` line.

---

### `dtk unlock`

Clear a stuck pipeline lock for the selected metric(s).

#### Syntax

```bash
dtk unlock --select <selector> [OPTIONS]
```

#### Options

**`--select`, `-s`** (required)
Metric selector — same semantics as `dtk run` (metric name, path pattern, or
`tag:<name>`).

**`--profile`** (optional)
Profile to use (overrides project default).

#### Examples

```bash
# Unlock a single metric
dtk unlock --select cpu_usage

# Unlock everything matching a tag
dtk unlock --select "tag:critical"
```

#### When to use it

Every `dtk run` records a `running` lock in `_dtk_tasks` while it works and
clears it on exit. If a run is killed without releasing its lock — most
commonly when **the database restarts mid-run** — the `running` row is left
behind. Until it's cleared, every subsequent **non-`--force`** run fails with:

```
RuntimeError: Failed to acquire lock for metric '<name>'. Another task is
running. Use --force to override.
```

Stuck locks **auto-expire** after their timeout (1 hour) — the next normal run
treats the stale `running` row as released and overrides it, so the error
clears itself. `dtk unlock` simply does this **immediately** instead of waiting
for the timeout. It marks the task `completed`, so the next scheduled (cron)
run proceeds normally without needing `--force`.

#### Behavior

- Reports, per metric, whether a lock was cleared (`lock cleared`) or none was
  held (`• <name>: no active lock`)
- Clears even a not-yet-expired lock (use with the same care as `--force`)
- Does **not** run the pipeline — only releases the lock

#### Example Output

```
Project root: /path/to/project
Found 1 metric(s) to unlock

  ┌─ cpu_usage
  └─ lock cleared

Done. Cleared 1 lock(s) of 1 metric(s).
```

---

### `dtk clean`

Remove internal data that no longer matches the project's YAML configs.

Editing metrics over time leaves stale rows behind in the internal tables.
`dtk clean` finds and removes that drift. **Both modes default to a dry-run**
that only reports what would be deleted; pass `--execute` to actually delete.

#### Syntax

```bash
dtk clean --select <selector> [--execute] [OPTIONS]   # drift mode
dtk clean --orphaned-metrics [--execute] [OPTIONS]    # GC mode
```

#### Options

##### `--select`, `-s` (drift mode)

Metric selector — same semantics as `dtk run`. For each selected
(still-existing) metric, removes:

- `_dtk_detections` rows whose `detector_id` is no longer produced by the
  config — i.e. you changed a detector parameter or `seasonality_components`
  (which changes the detector's hash), or removed a detector;
- `_dtk_alert_states` rows whose `alert_config_id` is no longer produced —
  i.e. you changed an alerting block's functional params (channels,
  `min_detectors`, `consecutive_anomalies`, cooldown) or removed the block.

Datapoints are **not** touched — they are keyed only by `(metric, timestamp)`
and are never orphaned by a parameter edit. Use `dtk run --full-refresh` to
reload those.

##### `--orphaned-metrics` (GC mode)

Deletes **all** rows, across every internal table, for metric names present in
the database but no longer defined by any YAML in the project (a renamed or
deleted metric). Operates over the whole project (ignores `--select`).

##### `--execute` (flag)

Actually delete. Without it, the command only reports (dry-run).

##### `--yes`, `-y` (flag)

Skip the confirmation prompt for `--orphaned-metrics --execute`.

##### `--profile` (optional)

Profile to use (overrides project default).

#### Examples

```bash
# See what stale detector/alert data a metric has accumulated (dry-run)
dtk clean --select cpu_usage

# ...then actually delete it
dtk clean --select cpu_usage --execute

# Clean drift across everything matching a tag
dtk clean --select "tag:critical" --execute

# List metrics in the DB that no longer exist in the project
dtk clean --orphaned-metrics

# Purge them (asks for confirmation unless -y)
dtk clean --orphaned-metrics --execute
```

#### Safety

- Dry-run by default; nothing is deleted without `--execute`.
- `--orphaned-metrics --execute` asks for confirmation (skip with `--yes`), and
  **refuses** to run if the project defines no metrics or its configs fail to
  parse — so a wrong directory or a duplicate-name error can't wipe valid data.
- In drift mode, if a metric's config defines no detectors/alerting at all (so
  *every* stored row counts as orphaned), the command prints a loud warning
  before deleting.
- Deletes are synchronous ClickHouse mutations and idempotent — safe to re-run.

#### Example Output

```
Project root: /path/to/project
DRY-RUN — nothing will be deleted. Use --execute to apply.

Found 1 metric(s) to inspect

  ┌─ cpu_usage
  │   detector a1b2c3d4e5f6a7b8: would delete 4,320 detection row(s)
  └─ alert_config 9f8e7d6c5b4a3210: would delete stale alert state

Done. Would remove 1 detector group(s) and 1 alert-state row(s).
Re-run with --execute to apply.
```

---

## `dtk osi`

Interop with [Open Semantic Interchange](https://github.com/open-semantic-interchange/OSI)
(OSI) semantic models — define a metric once in a governed OSI model and consume
it in detectkit. A **separate, additive** command group: it never runs the
pipeline, takes no lock, and its converter package is not imported by
load/detect/alert, so it cannot affect a running project. OSI is treated as an
*interchange* format, not an execution engine (detectkit does not build a live
OSI→SQL runtime — it converts at the edges).

sqlglot is needed only for the ClickHouse target — install the optional extra:

```bash
pip install 'detectkit[osi]'
```

### `dtk osi import`

Resolve one metric from an OSI model and **scaffold a normal native detectkit
metric** (SQL query, interval, a starter detector, the metric's `ai_context`).
Review the output and commit it like any hand-written metric — there is no
runtime dependency on OSI.

```bash
# preview the SQL only
dtk osi compile model.osi.yml --metric total_sales --interval 1h

# ClickHouse target: direct query from the dataset's physical `source`
dtk osi import model.osi.yml --metric total_sales --interval 1h --out metrics/

# Cube target: a Cube SQL-API MEASURE() query (alerts match the dashboard number)
dtk osi import model.osi.yml --metric total_sales --interval 1h \
  --target cube --cube store_sales --time-field sold_at --out metrics/
```

Only provably per-bucket-additive measures compile — `SUM`, `COUNT`,
`COUNT(DISTINCT)`, `AVG`, `MIN`, `MAX`, and ratios of them (e.g.
`SUM(x) / NULLIF(COUNT(DISTINCT y), 0)`). Window functions, non-aggregate
expressions and unsupported aggregates are **refused** with a message to use
`query_file:` — detectkit never emits a plausible-but-wrong series.

Key options: `--target {clickhouse,cube}`, `--dataset`, `--time-field`,
`--where`, `--cube` / `--cube-measure` / `--time-dimension` (cube target),
`--seasonality a,b`, `--detector <type>`, `--out <file|dir>`, `--force`.

### `dtk osi export`

Publish native detectkit metrics into an OSI fragment. Each metric becomes an OSI
`metrics` entry carrying its `ai_context` plus a **lossless snapshot** of the
detect/alert config in a `custom_extensions[detectkit]` block (a JSON string, per
the OSI spec), so the definition travels with the fragment while other OSI tools
still see the metric name + `ai_context`. This is a **one-way carrier**: `dtk osi
import` does not reconstruct a metric from that block (keep your metric YAML as the
source of truth).

```bash
dtk osi export --out semantic/detectkit.osi.yml          # all metrics
dtk osi export --select tag:critical                     # a subset, to stdout
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Normal completion — **including** most user-facing errors (bad project dir, missing `profiles.yml`, config/DB connection failures), which print an error message and return |
| 2 | Click argument error (e.g. a missing required option or an invalid `--steps`/`--from` value) |

> **Note:** detectkit does not currently exit non-zero on configuration or
> database errors — it reports them and returns `0`. Don't gate a scheduler on
> the exit code alone; check the logged output.

## Environment Variables

The CLI itself defines no special environment variables, but configuration
files support environment-variable interpolation so secrets stay out of YAML.
Both `${VAR}` and `{{ env_var('VAR') }}` syntaxes are supported:

```yaml
# profiles.yml
profiles:
  prod:
    type: clickhouse
    host: "{{ env_var('CLICKHOUSE_HOST') }}"
    port: 9000
    password: "${CLICKHOUSE_PASSWORD}"

alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
```

Unresolved placeholders (variable not set) are kept as-is, so missing
variables surface as configuration errors instead of empty strings.

## Common Workflows

### Initial Setup

```bash
# 1. Initialize project
dtk init my_monitoring
cd my_monitoring

# 2. Edit profiles.yml (add database connection)
# 3. Create metric config in metrics/

# 4. Run metric
dtk run --select my_metric
```

### Daily Operations

```bash
# Run all metrics (typically in cron/scheduler)
dtk run --select "*"

# Run critical metrics only
dtk run --select "tag:critical"

# Run specific metric manually
dtk run --select cpu_usage
```

### Backfilling Historical Data

```bash
# Load last 30 days
dtk run --select cpu_usage --from "2024-02-01"

# Load specific range
dtk run --select cpu_usage \
  --from "2024-01-01" \
  --to "2024-02-01"
```

### Reprocessing After Configuration Changes

```bash
# Detector config changed → rerun detection
dtk run --select cpu_usage --steps detect --full-refresh

# Query changed → reload data
dtk run --select cpu_usage --full-refresh

# Detector/alert params changed → prune the now-orphaned old results
dtk clean --select cpu_usage            # preview
dtk clean --select cpu_usage --execute
```

### Testing and Debugging

```bash
# Test alert channels
dtk test-alert cpu_usage

# Load data only (verify query works)
dtk run --select cpu_usage --steps load

# Detect only (verify detector works)
dtk run --select cpu_usage --steps detect
```

### Emergency Operations

```bash
# Clear a stuck lock left by a crashed run (e.g. DB restarted mid-run)
dtk unlock --select cpu_usage

# Force run if previous run crashed (also clears the stuck lock on exit)
dtk run --select cpu_usage --force

# Full refresh if data is corrupted
dtk run --select cpu_usage --full-refresh
```

## Scheduling

### Cron (Linux/Mac)

```bash
# Run all metrics every 10 minutes
*/10 * * * * cd /path/to/project && dtk run --select "*" >> /var/log/detectkit.log 2>&1

# Run critical metrics every 5 minutes
*/5 * * * * cd /path/to/project && dtk run --select "tag:critical" >> /var/log/detectkit.log 2>&1
```

### systemd Timer (Linux)

Create `/etc/systemd/system/detectkit.service`:
```ini
[Unit]
Description=detectkit metric monitoring

[Service]
Type=oneshot
WorkingDirectory=/path/to/project
ExecStart=/usr/local/bin/dtk run --select "*"
User=detectkit
```

Create `/etc/systemd/system/detectkit.timer`:
```ini
[Unit]
Description=Run detectkit every 10 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
```

Enable:
```bash
systemctl enable detectkit.timer
systemctl start detectkit.timer
```

### Task Scheduler (Windows)

```powershell
# Create scheduled task to run every 10 minutes
$action = New-ScheduledTaskAction -Execute "dtk" -Argument "run --select *" -WorkingDirectory "C:\projects\my_monitoring"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "detectkit" -Action $action -Trigger $trigger
```

### Docker Cron

```dockerfile
FROM python:3.11-slim

# Install detectkit
RUN pip install detectkit[clickhouse]

# Install cron
RUN apt-get update && apt-get install -y cron

# Copy project files
COPY . /app
WORKDIR /app

# Add cron job
RUN echo "*/10 * * * * cd /app && dtk run --select '*' >> /var/log/cron.log 2>&1" | crontab -

# Start cron
CMD ["cron", "-f"]
```

## Best Practices

### 1. Use Selectors Effectively

```bash
# Good: Specific selector
dtk run --select "metrics/critical/*.yml"

# Avoid: Selecting all when not needed
dtk run --select "*"
```

### 2. Test Before Scheduling

```bash
# Always test manually before adding to cron
dtk run --select my_metric
dtk test-alert my_metric
```

### 3. Log Output

```bash
# Redirect to log file for troubleshooting
dtk run --select "*" >> /var/log/detectkit.log 2>&1
```

### 4. Use --steps for Development

```bash
# Test query without detection
dtk run --select my_metric --steps load

# Test detector without alerting
dtk run --select my_metric --steps load,detect
```

### 5. Be Careful with --force

```bash
# Only use --force if you're sure no other process is running
# Check processes first:
ps aux | grep dtk
```

To recover from a *crashed* run (no live process), prefer `dtk unlock` — it
clears the stale lock without running the pipeline concurrently. A stuck lock
also auto-expires after 1 hour, so often no manual action is needed at all.

## Troubleshooting

### "Metric not found"

**Cause**: Selector doesn't match any metrics.

**Solution**: Check metric name and file path:
```bash
# List metric files
ls metrics/

# Try exact match
dtk run --select cpu_usage  # Not metrics/cpu_usage.yml
```

### "Task is locked" / "Failed to acquire lock"

**Cause**: Previous run is still in progress, or it crashed/was killed with the
`running` lock held. The most common crash cause is the **database restarting
mid-run**, which leaves a stale `running` row in `_dtk_tasks`.

**Solution**:
```bash
# Check if a process is actually still running
ps aux | grep dtk

# If no process is running, clear the stuck lock immediately:
dtk unlock --select cpu_usage

# (Or just wait — a stale lock auto-expires after 1 hour and the next
#  normal run overrides it. --force also clears it on exit.)
```

### "Connection refused"

**Cause**: Can't connect to database.

**Solution**: Check `profiles.yml` and database connectivity:
```bash
# Test ClickHouse connection
clickhouse-client --host=<host> --port=<port>
```

### "No data loaded"

**Cause**: Query returns empty result.

**Solution**: Test query manually in database client with sample dates.

## See Also

- [Configuration Guide](../guides/configuration.md) - Configure metrics
- [Detectors Guide](../guides/detectors.md) - Configure detectors
- [Auto-tuning Guide](../guides/autotuning.md) - Auto-configure a detector with `dtk autotune`
- [Auto-tune Reference](autotune.md) - `dtk autotune` flags, labels schema, scoring metrics
- [Project UI Guide](../guides/project-ui.md) - Project-wide live overview with `dtk ui`
- [Alerting Guide](../guides/alerting.md) - Configure alerts
- [Quickstart Guide](../getting-started/quickstart.md) - Getting started tutorial
