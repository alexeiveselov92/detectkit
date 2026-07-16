# detectkit — contributor & AI-assistant guide

**detectkit** is a Python library + CLI (`dtk`) for monitoring time-series
metrics with anomaly detection and multi-channel alerting. It is dbt-like:
metrics are YAML + SQL run through a `load → detect → alert` pipeline.
numpy-first (no pandas in core logic), ClickHouse / PostgreSQL / MySQL / MariaDB / DuckDB backends + Snowflake / BigQuery (source-only hybrid sources), Python 3.10+.

> **Using detectkit, not hacking on it?** See the [README](README.md), the
> [docs](docs/), and `dtk init-claude` (which sets up assistant context inside
> *your own* project).

## Working context lives in `.claude/rules/`

The detailed dev context is kept as focused rules (the single source — also
rendered on the docs site under **For developers**). Read the relevant one:

| If you're working on… | Read |
|---|---|
| Pipeline, module map, database layer, internal `_dtk_*` tables, detectors, alerting, design decisions | [.claude/rules/architecture.md](.claude/rules/architecture.md) |
| Dev setup, running tests, lint/format/types, conventions, adding a detector or channel, release checklist | [.claude/rules/contributing.md](.claude/rules/contributing.md) |

## Quick reference

- **Tests:** `python3 -m pytest tests/unit` — **lint/format/types:** `pre-commit run --all-files`
- `__version__` lives in `detectkit/__init__.py`; **`CHANGELOG.md` is authoritative** for behavior changes.
- **Automation contract:** `dtk run`/`autotune`/`clean` exit non-zero on failure
  (0 success / 1 failure — including a selector matching nothing / 2 usage error);
  `dtk run --json` emits one machine-readable summary on stdout (`schema_version: 1`,
  human logs move to stderr) — schedulers/CI gate on these. The generic webhook
  channel takes `format: attachments|json|alertmanager` (versioned event schema /
  Alertmanager receiver payload v4 whose trigger↔resolve fingerprints pair —
  direction is an annotation, never a label) plus an HMAC-SHA256 `secret`
  (`X-Detectkit-Signature-256` over the raw body). **MariaDB** is a first-class
  backend through the MySQL manager (vendor sniff at connect → `VALUES()` upsert
  fallback; `type: mariadb` profile alias; in the integration test matrix).
- **Channels wave 1:** `discord` (status-colored embed; the verbose tail is an
  inline field grid — Discord has no fold), `teams` (Power Automate Workflows +
  Adaptive Cards 1.4 — the retired O365-connector path is dead; posts under the
  flow's identity, so no branding and mentions never ping), `googlechat`
  (Cards v2; only `<users/all>`/`<users/USER_ID>` tokens in top-level text
  ping), `ntfy` (JSON publish; per-kind priority, tag emoji as the status cue)
  are first-class channel types; Rocket.Chat rides the generic `webhook`
  channel (its script-less incoming webhook takes the Slack-style attachments
  payload — documented recipe). All render from the shared `build_context`
  seam in the uniform `description → Rule → Value/Expected → links → tail`
  order.
- **MCP server:** `dtk mcp` (extra `[mcp]`, SDK pinned `>=1.27,<2`) — a
  strictly read-only MCP stdio server over `_dtk_*` (10 tools: list/get
  metric+status, bounded query_datapoints/detections, replay_alerts via the
  pure replay seam, autotune history, incidents, server info). Read-only is
  enforced: `create_manager(ensure_locations=False)`, no `ensure_tables`, no
  write paths; startup `--select` scopes tool access; isolated like
  `semantic/` (pipeline never imports it). **GitHub Action:** root
  `action.yml` (composite) — PyPI install + `dtk run` with the 0/1/2
  exit-code contract as job outcome + the `--json` summary as an output;
  example in `examples/action-smoke/`.
- **Hybrid mode:** `source_profile` (metric → project → unset) runs a
  metric's **load** SQL against a different profile's database while all
  `_dtk_*` state stays in the state profile (`--profile`/`default_profile`,
  meaning unchanged) — the warehouse unlock. Lazy one-connection-per-source
  pool on the TaskManager (failures cached; closed at run end);
  `SourceDatabaseError` distinguishes source-down from state-down in error
  alerts; `dtk run` fail-fast validates resolved names (typo → exit 1, no
  paging); autotune/tune/ui/clean/unlock are state-only and untouched.
- **DuckDB** is a first-class backend (`type: duckdb`, profile takes `path` —
  or `:memory:`, tests-only — + optional `read_only`; duckdb **>= 1.1**, the
  alert step's `IN`-list query needs it): an in-process single-file DB behind
  a small DB-API adapter (`%(name)s → $name` translation, lazy transactions)
  over the shared SQL manager, PostgreSQL-shaped version-aware `ON CONFLICT`
  upsert. The file is held read-write by **one process at a time** — `dtk ui`
  open + a spawned `dtk run` on the same file conflict (run-then-look). Real
  engine runs in the unit suite, no Docker. **MotherDuck** rides the same
  `type: duckdb` (no new type/extra): a `path: "md:<database>"` attaches
  DuckDB's cloud service through the same client (the `motherduck` extension
  autoloads on first `md:` use — first connect downloads it, needs network),
  authed by an optional env-interpolated `motherduck_token` field (sent as the
  connect config; unset → the extension's own `motherduck_token` env var; an
  explicit `settings.motherduck_token` wins). It stays a **full state-capable**
  backend (same SQL/upsert; `_dtk_*` can live there; also a hybrid source). Two
  `md:`-only asymmetries: it's a **served** database, so the single-writer /
  run-then-look caveat is **local-files-only** (`dtk ui` + a spawned `dtk run`
  coexist), and it has no `read_only=True` attach, so `read_only` is a
  local-files-only knob (the MCP strict probe skips the forced read-only for
  `md:`).
- **Snowflake** (`type: snowflake`, extra `[snowflake]`) is a **source-only**
  backend behind a minimal `SourceDatabaseManager` seam (`database/source_manager.py`
  — `execute_query` + `close`; `BaseDatabaseManager` subclasses it so full
  backends double as sources). Valid **only** as a metric/project
  `source_profile` (hybrid mode: its load SQL runs on Snowflake, all `_dtk_*`
  state stays in a full state backend); `ProfileConfig.STATE_TYPES` vs
  `SOURCE_ONLY_TYPES` split (`{snowflake, bigquery}`) — `create_manager()`
  refuses it as state, the pool builds it via `create_source_manager()`.
  `SnowflakeSourceManager` (`snowflake_manager.py`): eager connect, key-pair
  (recommended) or password auth, session `TIMEZONE` pinned UTC (`settings`
  override wins), all-uppercase result columns folded to lowercase for the loader.
- **BigQuery** (`type: bigquery`, extra `[bigquery]`) is the **second**
  source-only backend on that same `SourceDatabaseManager` seam — valid **only**
  as a metric/project `source_profile` (hybrid mode: load SQL runs on BigQuery,
  all `_dtk_*` state stays in a full state backend), `create_manager()` refuses
  it as state, the pool builds it via `create_source_manager()`.
  `BigQuerySourceManager` (`bigquery_manager.py`): eager connect via a free
  `SELECT 1` probe (0 bytes on on-demand billing → fails fast on a bad
  `project` / credentials / `settings` typo; retries are bounded — probe 30s,
  load queries 120s/600s — so an unreachable endpoint can't stall the run on
  the client library's 10+-minute connection-error retry defaults); auth is a
  `credentials_json_path` service-account key or **Application Default
  Credentials** (a plain-`http://` `api_endpoint` without a key file — the
  emulator path — uses anonymous credentials; `https://` endpoint overrides
  authenticate normally);
  `dataset` → the job's `default_dataset`, `settings` apply to each query's
  `QueryJobConfig` (a non-`QueryJobConfig` key is rejected at the probe);
  `TIMESTAMP` results are tz-aware UTC (loader converts) and there is **no**
  column folding (aliases keep case). Source-only for billing: on-demand queries
  bill a **10 MiB minimum** of bytes processed per referenced table, so keep
  state in a cheap local DB and cap scans with `settings: {maximum_bytes_billed: …}`.
- User-facing docs are in `docs/`. The context that `dtk init-claude` ships to
  users lives in `detectkit/cli/assets/claude/` — **keep both in sync on every
  release** (see the contributing rule's release checklist).
- Keep the library **detector-agnostic** (new statistical detectors reuse
  `WindowedStatDetector`; the prediction-based `autoreg` is the one documented
  exception — its own `BaseDetector` subclass) and use the **generic** database
  manager (`insert_batch(table_name=...)`, never hardcoded per-table logic).
- **Auto-tuning** lives in `detectkit/autotune/` (the `dtk autotune` command,
  separate from load/detect/alert), records each run in the `_dtk_autotune_runs`
  internal table, and ships a `dtk-autotune` skill + `autotune.md` rule — keep
  those in sync on release.
- **Reporting** lives in `detectkit/reporting/` (`dtk run --report` /
  `dtk autotune --report`): it reads the `_dtk_*` tables and **replays alerts**
  into one self-contained HTML report per metric, sharing a framework-free JS
  rendering core with the website landing demo. The committed
  `assets/report.js` bundle ships in the wheel — regenerate it (and keep it in
  sync on release) when the report renderer TS changes. The website
  **playground** (`/playground/`) is a **literal instance of the `dtk tune`
  cockpit renderer** fed a *synthetic* metric (the three server hooks nulled = the
  `--no-serve` shape) via a small `playground/` adapter — not a separate demo — so
  it evolves with the product; a `website` CI job regenerates the golden parity
  vectors + all committed bundles (`build:bundles`) and fails on any stale
  artifact, so it can't drift.
- **Manual tuning** lives in `detectkit/tuning/` (the `dtk tune` command): the
  human-in-the-loop sibling of `dtk autotune`. It serves an interactive view of a
  metric's real series (recomputing the band live via the **same** TS detector
  port as the landing playground) and, on **Apply**, writes the chosen config
  back into the metric YAML — validating first, archiving the previous version to
  `metrics/.history/<metric>/`, then re-emitting in place. Write-back **merges**:
  it rewrites only the detector(s) you tuned and preserves every other detector
  (a `manual_bounds` floor, a `prophet`/`timesfm` detector, another windowed one)
  **verbatim** — a metric with several detectors gets a **Tuning detector** picker
  to choose which to tune, and a `min_detectors>=2` alert is never silently broken
  by a retune (the earlier bug). The archived `.history/` copies are **excluded
  from metric discovery** (`discover_metric_files`), so a tuned metric no longer
  collides with its own snapshots as a "duplicate metric name". The whole screen is a
  **chart-first cockpit**: ONE mode-driven chart (the windshield) fills the view,
  the live **metrics ride pinned in a HUD over the chart** (the speedometer —
  always in view), and every control lives in an **always-visible side rail**
  beside the chart with its own scroll. The rail is **mode-aware** — it shows only
  the current mode's panel (detector knobs + effective config + Apply in **Tune**,
  verdict actions in **Review**, capture tools + incident list + Save in **Label**,
  the search button + winner/decision-log in **Autotune**)
  and collapses to give the chart the whole width — but the controls that aren't
  detector-specific stay visible in **every** mode (the **Points shown** data
  window, the alert rule — **direction** + **consecutive anomalies** + the
  fraction pair **anomaly window / min share** (off below 2 points = legacy
  consecutive-only; the worker OR-merges its fires with the consecutive rule's,
  pipeline semantics) — and the **y = 0** toggle). A **mode switch** picks which layers lead / dim / hide and
  which interactions are armed — **Tune** (band leads), **Review** (confirm the
  fired alerts: click a marker to cycle un-reviewed → valid (green) → false alarm
  (slate); **confirming an alert valid IS marking an incident** — the confirmed
  streak becomes a first-class **ground-truth incident** that shows in the
  Marked-incidents list as a "✓ confirmed alert" row, counts toward recall/FDR, and
  is written on Save, so a clean metric is validated in a few clicks without
  hand-drawing spans), **Label** (band hides,
  incidents editable; **Lasso anomalies** loops a cloud of anomaly dots into
  per-streak incident spans, **Threshold capture** grabs every span past a line),
  and **Autotune** (runs the **real** `dtk autotune` engine **server-side** over the
  **window the cockpit is showing** — the page posts its current **Points shown**
  trim window so the engine tunes on exactly the series the user sees and scores, not
  the full history — via a repeatable `POST /autotune`, using the marked incidents
  as ground truth, then **re-seeds every knob** with the winner + renders the
  decision log; the band leads like Tune). The run also **streams a structured
  run-log to the terminal** (cyan banner → `LABELS → SEASONALITY → … → RESULT`
  blocks via the same `StageLogRenderer` `dtk autotune` uses, matching `dtk run`'s
  format; the per-candidate "falls back to global" warning flood is quieted during
  the search). Autotune-in-tune is **advisory** — it
  computes + re-seeds only, persisting **no** run/`__tuned_<id>.yml`/detections (so
  `dtk tune` stays lock-free); the user reviews and **Apply**s, and the next
  `dtk run` is source of truth. The CLI command and the server share one
  `autotune/runner.py` (`autotune_from_data` — cap history → resolve scoring →
  ground truth → settings → `run_autotune_engine`), and the result re-seeds via the
  same `payload.seed_detector_params` the controls were first seeded from.
  The incident list, the live metrics and Save share **one** ground-truth set —
  hand-marked spans **plus** confirmed-valid alerts (derived from the stored
  verdict, not the current fire, so a confirmed incident stays scored — as a recall
  *miss* — even if the detector no longer fires there), deduped by overlap.
  **Deleting** a hand-marked incident (chart ✕ / Delete key **or** the list ✕)
  **retracts any confirmed-valid verdict it overlapped** (`retractConfirmationFor`,
  mirroring `unconfirmAlert`), so the span is fully removed instead of the hidden
  verdict **resurfacing** as a "✓ confirmed alert" row — the two delete paths stay in
  lockstep (the chart threads the removed span via `onIncidentsChange(incidents,
  removed)`); explicit `false` verdicts and non-overlapping confirmed alerts are left
  alone.
  Watch live **catch-rate (recall)** / **false-alert rate (FDR)** / **reviewed**
  metrics — matched on each alert's anomaly **streak span**, not just the fire
  instant — as you tune; an optional **false-alert budget** (`false_alert_budget`,
  a fraction in `(0, 1]`, on the **metric** then **project**, default `0.5`) gently
  flags the false-alert chip when the FDR exceeds it (tuning-only — labeling stays
  optional and it never touches the pipeline).
  **Save incidents** writes versioned `incidents/<metric>/*.yml` (the same store
  `dtk autotune` reads, including the painted `capture_windows` and per-alert
  `alert_reviews` metadata; confirmed alerts are written as incidents too) via a
  `POST /labels` endpoint, reusing `autotune/labels.py`. Seeded incidents from that
  store **anchor the (budget-sized) loaded window** — it ends just past the latest
  incident rather than at the last datapoint, so they render/score without an old
  outlier dragging the whole history in. A **y = 0 reference line** toggle is shared with
  `dtk run --report`. Committed bundle `assets/tune.js` (built by
  `website/scripts/gen-tune-bundle.mjs`) ships in the wheel — regenerate it when
  the renderer TS changes. Takes no pipeline lock. `dtk init-claude` ships a
  `dtk-tune` skill (the hands-on entry point for the user's assistant — the
  cockpit umbrella, with autotune built in) — keep it in sync on release.
- **Project UI** lives in `detectkit/ui/` (the `dtk ui` command): a
  project-wide localhost cockpit — an overview of every metric's alert
  frequency/freshness (replayed via the same seam as `dtk run --report`;
  quality chips when `incidents/` labels exist) plus a pipeline panel that
  drives `dtk run` / `dtk autotune` / `dtk unlock` / `dtk clean` as real
  subprocesses and launches `dtk tune` per metric — a per-metric **Clean
  stale** action on the detail overlay prunes superseded detector generations
  (read-only `GET /api/clean-preview/<name>` dry-run counts → confirm strip →
  `POST /api/clean` spawning the real `dtk clean --select <metric> --execute`
  as a `clean` pipeline job; the overview row's `stale_detectors` count shows
  an amber `N stale` chip, `null`/no-chip when the config's ids can't be
  derived, so an underivable config is never presented as all-stale) — and
  **metric management**: create / edit /
  delete metric YAMLs from a browser editor (`ui/metric_files.py`, the
  mutation seam) with validate-before-write (full `MetricConfig` + deep
  detector-params), a verbatim archive to `metrics/.history/<metric>/` before
  every overwrite/delete (same discovery-excluded archive as `dtk tune`), a
  name-echo confirmation on delete, and a refusal while a tune session for
  that metric runs. The editor is two tabs over one draft: a **Builder** form
  (modeled fields + verbatim passthrough of everything unmodeled, listed as
  "Preserved fields"; a highlighted SQL pane; a "From OSI" sub-tab compiling
  via the same path as `dtk osi import`; Builder saves re-emit the YAML,
  dropping comments — the archive keeps the old file) and the raw **YAML**
  tab (verbatim writes, for experts); after a create, a next-steps strip runs
  `dtk run --steps load,detect` (no alert step) and then opens the tune
  cockpit. Takes no pipeline lock; the CRUD routes never touch the
  database (orphaned `_dtk_*` rows wait for `dtk clean`). Committed bundle
  `assets/ui.js` (built by
  `website/scripts/gen-ui-bundle.mjs`) ships in the wheel — keep it and the
  docs in sync on release.
- **OSI interop** lives in `detectkit/semantic/` (the `dtk osi import` /
  `export` / `compile` commands): an **isolated, additive** bridge to
  [Open Semantic Interchange](https://github.com/open-semantic-interchange/OSI) —
  the pipeline never imports it, so it can't affect a running project. OSI is an
  *interchange* format (define a KPI once, consume in BI + AI), not an execution
  engine, so detectkit converts at the edges rather than running OSI live:
  `import` scaffolds a **normal native metric** from an OSI model metric
  (`--target clickhouse` compiles from `dataset.source` via **sqlglot**;
  `--target cube` emits a Cube SQL-API `MEASURE(...)` query for dashboard
  number-parity), compiling only provably per-bucket-additive measures and
  hard-refusing the rest; `export` publishes metrics back as an OSI fragment with
  a lossless snapshot of the config in `custom_extensions[detectkit]` (a **one-way
  carrier** — `import` doesn't reconstruct from it; the metric YAML stays source of
  truth). OSI adoption is early, so the broadly-useful piece today is the
  metric-level `ai_context` (`{instructions, synonyms, examples}`, mirroring OSI) —
  descriptive grounding usable on any metric with no OSI model: opt-in
  `{synonyms}`/`{synonyms_line}` alert vars (no
  default-message change) + the tune cockpit payload. sqlglot is the optional
  `[osi]` extra (lazy import). A live runtime `osi_source` binding is deliberately
  deferred. Keep the `dtk osi` docs (cli reference + the OSI guide) in sync on
  release.

Repo: https://github.com/alexeiveselov92/detectkit
