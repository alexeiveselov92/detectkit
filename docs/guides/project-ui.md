# Project UI

`dtk ui` opens an interactive, project-wide localhost page over the metrics
you already run: one overview of every metric's alerting behavior, a detail
view per metric, a panel that drives `dtk run` / `dtk autotune` /
`dtk unlock` and launches `dtk tune` — plus **New metric** / **Edit** actions
that create, edit, and delete metric YAML files, either through a structured
**Builder** form or the raw **YAML** directly — all from the browser instead
of memorized flags and a text editor. Like `dtk tune`, it is a
superstructure over the existing CLI and config files: the server itself
never runs the pipeline in-process, takes no pipeline lock, and never touches
the database; every pipeline action it takes is the same subprocess you'd
type in a terminal, streamed back into the page, and every metric-file edit
goes through the same validate-before-write, archive-before-overwrite
discipline `dtk tune`'s Apply uses.

## When to use it

- **A per-metric HTML report** (`dtk run --report`) is the fastest way to look
  at one metric after a run — a static, offline snapshot you can email or
  commit. `dtk ui` is the live, **whole-project** counterpart: instead of
  opening N report files, you get one page ranking every metric by how often
  it's alerting, which ones have gone stale, and which ones need attention —
  with the same report still a click away in an overlay.
- **`dtk tune`** is where you turn a detector's knobs against the metric's
  real series and watch the confidence band recompute live before writing the
  result back. `dtk ui` is the project-wide surface around it: it surveys
  every metric, drives the pipeline, and lets you create, edit, or delete a
  metric's YAML directly — but it doesn't recompute a detector live; when a
  metric needs that kind of work, its row's **Tune** button still opens the
  real `dtk tune` cockpit in a new tab.
- Reach for `dtk ui` when you're asking "what's alerting across the project
  right now", "which metrics have gone stale", or "did that config change
  actually reduce false alerts" — questions a single metric's report can't
  answer — and increasingly also for quick metric edits (a threshold tweak, a
  new tag, a config typo) you'd otherwise open a terminal and editor for.

## Starting it

```bash
dtk ui
```

This opens a local `127.0.0.1` server and your browser to the overview,
covering every metric in the project. Restrict or adjust it like any other
command:

```bash
# Only metrics tagged "critical"
dtk ui --select tag:critical

# Start with a shorter window than the 30-day default
dtk ui --window 7d

# Don't open a browser tab (e.g. over SSH — copy the printed URL instead)
dtk ui --no-open

# Point at a specific profile — also used by every dtk run/autotune/unlock
# the pipeline panel spawns
dtk ui --profile staging
```

`--select` accepts the same selector syntax as `dtk run` — a metric name, a
glob, or `tag:<name>` — and defaults to `*` (everything). `--window` only sets
which preset is selected when the page opens; switch freely between `24h` /
`7d` / `30d` / `90d` / `All` once it's up.

## Reading the overview

Every metric gets one row, computed **fresh** for the selected window — the
numbers aren't cached snapshots, they're the same counts a real `dtk run`
would have alerted, because the anomaly / recovery / no-data counts are
**replayed** from the stored detections through the same pure
`AlertOrchestrator.replay` logic the HTML report uses (see
[Visualizing Results](visualizing-results.md#html-reports)). Rows load
**incrementally**: the table appears immediately and each metric's stats
stream in (a small `n/N` progress chip shows how many have landed), so a
large project never blocks on one slow metric — a failing one just marks its
own row. The stats consider only the metric's **current** detector
configuration: detections persisted by superseded configs (each retune or
autotune run changes a detector's identity) are excluded, so the counts answer
"how does the metric behave as configured today", not "what did some past
config once flag".

- **Alerts in window** — how many anomaly, recovery, and no-data events fired,
  from the alert rule the metric actually has configured.
- **Per-day rate** — alerts in window normalized by the window's length, so a
  24h view and a 90d view read on the same scale.
- **Last alert** — how long ago the most recent anomaly alert fired.
- **No-data events** — how many times the metric's latest expected point was
  missing or NULL (independent of the anomaly quorum).
- **Anomaly rate** — the share of scored points flagged by *any* configured
  detector (a union — a two-detector metric isn't double-counted).
- **Freshness** — how stale the last datapoint is relative to the metric's
  interval, shown as a status dot: green when the lag is under 2x the
  interval, amber under 6x, red at or beyond that (or no data at all); a lock
  icon marks a metric whose pipeline lock is currently held.
- **Sparkline** — a compact chart of the window's values with anomalous
  points marked, so you can eyeball the shape without opening the detail
  view.

### Quality chips (only with labels)

If you've labeled a metric — `dtk tune`'s **Label** / **Review** mode, **Save
incidents** — its row also shows **recall**, **false-alert rate (FDR)**, and a
**reviewed-alert count** (hover the chips for the valid/false breakdown).
These are computed the same way the `dtk tune` cockpit's
metrics bar computes them: matched on **streak-span overlap** (an incident
counts as caught when an alert's whole anomaly streak overlaps it, not just
the instant it fired), against the union of hand-marked incidents and
confirmed-valid alerts. A metric with no `incidents/<metric>/` file simply
shows no chip — labeling stays entirely optional.

### Evaluating a project with no labels at all

You don't need to label anything to get value out of `dtk ui`. Sort by
**alerts in window** to find the noisiest metrics, click **Open** on each one
to eyeball its chart and confidence band in the detail overlay, and use your
own judgment on whether what's flagged looks real. Labeling only adds a
second, quantified read (recall/FDR) on top of that — it's the same
eyeball-first workflow `dtk tune` supports with no incidents marked.

## Tags and folder grouping

The metrics table groups rows by their `metrics/` subfolder (root metrics
under `metrics/` itself), with a per-folder alert total in the group header —
useful once metrics are organized by team or domain. A tag strip above the
table lets you filter to one tag at a time (or reset to **All**); untagged
metrics group under `untagged`.

## The detail view

Click **Open** on any row to open that metric's **existing self-contained
HTML report** — the same one `dtk run --report` writes — in a full-screen
overlay: values, each detector's confidence band, flagged anomalies, and the
alerts that fired, with its own period selector. Nothing is regenerated for
the overlay; it reads the same persisted `_dtk_*` rows the overview did.
Close it with **Esc** or a click outside it.

## Running the pipeline from the UI

The pipeline panel is a convenience layer over the CLI, not a different code
path: clicking **Run** spawns the **same** `dtk run` you'd type in a
terminal — with the same selector, `--steps`, `--from`/`--to`, `--force`, and
`--full-refresh` options — as a subprocess, and streams its output into a log
terminal live. **Autotune** and **Unlock** work the same way for
`dtk autotune` and `dtk unlock`.

Because a spawned `dtk run` takes the **same pipeline lock** as any other run,
`dtk ui`'s panel doesn't create a second way for two runs to race the same
metric: only **one** `run` / `autotune` / `unlock` job is allowed at a time
from the panel, and starting a second one while the first is still going is
refused. This mirrors the lock's own behavior — you'd hit the same
"failed to acquire lock" running two terminals side by side.

`dtk ui` itself never runs the pipeline in-process and takes no lock of its
own; it only spawns and streams these commands.

## Launching Tune

Every row has a **Tune** button that spawns `dtk tune --select <metric>
--no-open` in the background and opens its cockpit in a **new tab** once it's
ready — you get the full interactive tuning experience described in the
[Tuning guide](tuning.md), just launched from the overview instead of a
terminal. Unlike `run` / `autotune` / `unlock`, **tune jobs are not mutually
exclusive** — you can tune several metrics side by side, since each opens its
own isolated tuning server and none of them touch the pipeline lock.

## Managing metrics

Every row's **Edit** action, and a **New metric** button in the header, open a
full-screen editor with **two tabs sharing one draft**: **Builder** — a
structured form over every metric parameter — and **YAML** — the raw text,
kept for experts who paste whole configs. The last-edited tab wins, and never
silently: switching away from an edited YAML tab first validates it
server-side and blocks the switch on error, so the two views can't hold
diverging state; switching away from an edited Builder re-emits the YAML, so
you can always inspect exactly what will be written. A live validation chip
in the footer re-checks the draft as you type (debounced; the same
server-side validation Save runs), so most errors surface before you ever
click Save.

### The Builder

The Builder covers the whole config as form controls: the basics (name,
description, tags, profile, enabled), schedule & loading (interval with
common presets, `loading_start_time`; `loading_delay`, `loading_batch_size`
and `query_columns` under an advanced fold), seasonality-feature checkboxes,
detector rows, alerting, and `ai_context`.

- **SQL gets a real code pane** — syntax-highlighted (keywords, strings,
  comments, numbers, and the Jinja `{{ dtk_start_time }}`-style variables),
  not a plain textarea. A metric that uses `query_file:` shows the path
  read-only instead: edit the file on disk (or switch to the YAML tab); the
  Builder never converts a `query_file` into an inline query.
- **Detector rows are deliberately minimal** — the type plus one or two key
  parameters (threshold and window size; lags for `autoreg`; lower/upper
  bounds for `manual_bounds`). That's intentional: picking a detector and a
  rough starting point belongs here, but fine-tuning belongs in the
  [`dtk tune` cockpit](tuning.md), against the metric's real series — the
  form says as much next to the rows.
- **Alerting is form-first too**: channels come as a multi-select seeded from
  the channel names in your `profiles.yml` (names and types only — channel
  configs and secrets never reach the browser), alongside direction,
  consecutive anomalies, no-data / recovery toggles and the cooldown;
  `min_detectors`, the `anomaly_window` + `min_anomaly_share` pair, mentions
  and `dashboard_url` sit under an advanced fold.
- **Nothing you don't edit is lost.** Config keys the form doesn't model — an
  `autotune:` block, `tables:`, a custom alert `template`, a detector
  parameter the row doesn't render (say `smoothing`), a detector type the
  picker doesn't know (`prophet`, `timesfm`), a multi-entry alerting list —
  round-trip verbatim and are listed in a **Preserved fields** section so you
  can see what's riding along.
- **One caveat: comments.** Saving from the Builder re-emits the YAML
  deterministically, and hand-written comments don't survive a re-emit — the
  editor warns about this when the file has any, and the previous file is
  always archived first (see below), so nothing is unrecoverable. When a
  file's comments matter, edit it from the YAML tab, which still writes your
  text verbatim.

### From OSI

The query source has a second sub-tab, **From OSI**, for teams with a
governed [OSI semantic model](osi.md): paste the model, the page inspects it
server-side and lists its metrics, pick one and a target — `clickhouse` or
`cube` — and **Compile**. This is the exact code path `dtk osi import` runs,
so the Builder and the CLI produce identical output: the compiled SQL lands
in the code pane, the metric's description and `ai_context` seed the form,
and the sql-fingerprint is recorded as a header comment in the emitted YAML.
The `clickhouse` target needs the optional `[osi]` extra (sqlglot) — the
error message says so if it's missing; the `cube` target doesn't.

### Creating, editing, deleting

- **New metric** opens the Builder seeded with sensible defaults (the YAML
  tab holds the equivalent starter template) and an optional folder field, so
  a new file can land in a `metrics/` subfolder instead of the root. **Create
  metric** validates server-side and writes `metrics/[<folder>/]<name>.yml`,
  with the filename derived from the metric's `name:`. The new metric joins
  the current session immediately — even if it wouldn't match the `--select`
  the server was started with — so you don't need to restart `dtk ui` to see
  it in the overview.
- **After a create, a next-steps strip closes the loop**: **Load & detect**
  spawns `dtk run --steps load,detect` for just that metric — deliberately
  *without* the alert step, so an untuned starter config can't spam a real
  channel — and once the job succeeds, **Open tune** unlocks and opens the
  `dtk tune` cockpit on the freshly loaded series. That's the intended flow:
  create with rough defaults, load real data, then tune the detector against
  it.
- **Edit** opens the metric on the Builder whenever the file parses; a file
  that doesn't (hand-edited on disk into a broken state) opens YAML-only,
  with the parse error shown on the disabled Builder tab — fix it in YAML and
  reopen. Saving from the YAML tab behaves exactly as before: the text you
  typed lands on disk, comments and formatting intact (normalized only to
  end with a newline). Either way, Save first **archives the previous file
  verbatim** to `metrics/.history/<metric>/<metric>-<stamp>.yml` — the same
  archive `dtk tune`'s Apply writes to, and excluded from metric discovery,
  so it never collides with the live file as a duplicate name.
  Saves are also **conflict-checked**: if the file changed on disk after the
  editor was opened — a `dtk tune` Apply landed, another tab saved, or you
  edited the file directly — Save is refused with a clear message instead of
  silently overwriting the newer version; reopen the metric to pick up the
  latest text.
  Renaming a metric (changing its `name:`) is allowed; uniqueness is checked
  against the whole project. A rename leaves the old name's rows in the
  `_dtk_*` tables behind — run [`dtk clean`](../reference/cli.md#dtk-clean)
  to prune them once you're sure the rename stuck.
- **Delete metric** lives inside the edit overlay, behind an explicit
  confirmation step — you can't delete from the row itself. The server
  additionally requires the confirmation to echo the metric's name back, so a
  stray click can't remove a file. Deleting archives the file to
  `metrics/.history/<metric>/<metric>-<stamp>-deleted.yml` and then removes
  it from `metrics/`; its rows stay in the `_dtk_*` tables until `dtk clean`
  prunes them, and since the archived copy is a verbatim snapshot, the delete
  is reversible by hand — restore the archived file and it's a live metric
  again.
- **Validation happens before anything is written**: YAML syntax first, then
  full config validation, then a deep check of each detector's parameters (by
  actually constructing it) — the same discipline `dtk tune`'s Apply uses. An
  invalid config never touches the filesystem; it comes back as an error in
  the editor's error pane so you can fix it in place. The live chip runs the
  same validation while you type, but it's advisory — Save's own response is
  authoritative.
- **If you're tuning the metric at the same time**, Save and Delete are
  refused while a `dtk tune` session for that metric (launched from this UI)
  is still running — the tuner's own **Apply** would otherwise race your
  edit. Close or apply the tune session first.

None of this touches the database: create/edit/delete only read and write
metric YAML files under `metrics/`, the same files you'd otherwise edit by
hand.

## Security note

`dtk ui` binds to `127.0.0.1` only — it is not reachable over the network.
Every route, including the page itself, requires a random token minted when
the server starts (the URL the CLI prints already carries it) — this also
guards the metric create/edit/delete routes, which only ever write inside the
project's `metrics/` directory. There is no authentication beyond that token,
so treat the printed URL like you would a local `dtk tune` session — don't
share it, and stop the server (Ctrl-C) when you're done. A fresh token is
minted each time you start `dtk ui`.

## Advanced

- **The `all` window is capped.** To keep a page with years of 1-minute data
  from melting the browser or the database, the overview's `all` preset loads
  at most ~20,000 points per metric (bounded from the most recent datapoint
  backward). Metrics with less history than that are unaffected.
- **The detail overlay's `all` differs from the overview's.** The embedded
  report iframe is the same one `dtk run --report` produces, so its own `all`
  period follows the report's convention — the most recent 1,500 points —
  which is a tighter cap than the overview's ~20,000-point limit used for the
  table's stats and sparkline.

## See also

- [Visualizing Results](visualizing-results.md) — the per-metric HTML report
  and BI recipes `dtk ui`'s detail view and replay logic build on.
- [Tuning a Detector by Hand](tuning.md) — the cockpit `dtk ui`'s **Tune**
  button opens.
- [Auto-tuning a Detector](autotuning.md) — the engine behind the pipeline
  panel's **Autotune** button.
- [CLI reference](../reference/cli.md#dtk-ui) — `dtk ui` flags.
