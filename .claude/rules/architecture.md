# Architecture

detectkit is a modular, database-agnostic library for monitoring metrics with
automatic anomaly detection. It is built around a three-stage pipeline —
**load → detect → alert** — driven by a dbt-like CLI (`dtk`) over YAML configs.
Core principles: **numpy-first** (no pandas in core logic; only in optional
helpers), **database-agnostic** (a generic manager interface with ClickHouse,
PostgreSQL, MySQL/MariaDB and DuckDB backends), **idempotent / resumable** (every stage resumes from the
last persisted timestamp), **modular** (small focused files, packages split into
mixins so nothing grows past ~250 lines), and **type-safe** (pydantic configs +
type hints throughout).

## The pipeline

`dtk run --select <selector>` loads the project, selects metrics, builds the DB
manager, ensures internal tables exist, then runs each metric through the
pipeline. `--steps load,detect,alert` (default: all three) restricts which
stages run. Each stage is idempotent and reads/writes the internal `_dtk_*`
tables described below. `run`/`autotune`/`clean` exit non-zero on any metric
failure (or a matching-nothing selector), so schedulers/CI can gate on the
process exit code; `dtk run --json` additionally emits one machine-readable
run summary on stdout while human logs go to stderr.

A metric-level **`enabled: false`** takes that metric out of the pipeline
entirely (no load/detect/alert, no lock). The gate lives in the **runner**
(`cli/commands/run.py:_run_impl` partitions the selected list right after
`--exclude`; `cli/commands/autotune.py:_tune_one` checks it before
`autotune.enabled`), deliberately **not** in discovery/`select_metrics`: the skip
stays visible (an `echo_noop` line + a `status: "skipped"` entry in `--json`,
never affecting the exit code — a run whose every selected metric is disabled
exits 0), and every command that shares `select_metrics` keeps seeing the metric
— `dtk tune` / `dtk ui` / `dtk mcp` are how you inspect one you just turned off,
and its rows must not read as orphaned to `dtk clean --orphaned-metrics`. The one
DB write a skipped metric still gets is its informational `_dtk_metrics` row
(`_refresh_disabled_registry`), so that table's `enabled` column can't go stale.
Until v0.67.2 the flag was a silent no-op — a disabled metric kept loading,
detecting and alerting while three doc surfaces promised otherwise (issue #162).

- **load** (`detectkit/orchestration/task_manager/_load_step.py` →
  `detectkit/loaders/metric_loader.py`): renders the metric's SQL with Jinja2
  (`dtk_start_time`/`dtk_end_time`/`interval_seconds` injected), executes it,
  extracts seasonality features, **fills gaps** so the series is on a complete
  time grid (missing points become NaN/NULL), and writes `_dtk_datapoints`.
  Resumes from the last datapoint timestamp (or `loading_start_time` on first
  run); batches by `loading_batch_size`; snaps the end to the last complete
  interval boundary. An optional `loading_delay` (metric → project → 0) shifts
  that "now" bound back first, so an interval isn't loaded until the upstream
  source has had time to finish writing it — an explicit `--to` bypasses this
  and is trusted verbatim. In **hybrid mode** (`source_profile`, resolved
  metric → project → unset like `loading_delay`) the load query runs against a
  *different* profile's database while `_dtk_*` state — and every other stage
  and command — stays on the state profile: the `TaskManager` keeps a lazy
  one-connection-per-source-profile pool (shared across metrics, built via
  `profiles_config.create_source_manager(name)` — so a source may be a full
  backend or a source-only type like Snowflake / BigQuery — closed at
  run end via `close_sources()`; a failed source connection is cached, not
  retried per metric), `_load_step` threads the pooled manager into
  `MetricLoader` as its `db_manager`, and the loader wraps only the source
  `execute_query` in `SourceDatabaseError` (`loaders/errors.py`, message leads
  with `source database (profile '<name>')`) so error alerts distinguish
  source-down from state-down. `dtk run` fail-fast validates every resolved
  name against `profiles.yml` before opening any connection (a typo exits 1
  without paging `error_alerting`); detect/alert-only runs never open source
  connections.
- **detect** (`detectkit/orchestration/task_manager/_detect_step.py`): for each
  configured detector, builds the detector, computes its `detector_id`, resumes
  after the last persisted detection, loads datapoints **plus a historical
  context window** (`get_context_size()`), runs `detect()`, strips the context
  from the persisted rows, and writes `_dtk_detections`. Batches by the
  detector's `batch_size`. On a first-ever detect with no lower bound from
  `--from`, the resume point, or the detector's `start_time`, it falls back to
  the metric's `loading_start_time` (then its first datapoint) so detection
  covers all loaded history instead of short-circuiting as "already up to date".
- **alert** (`detectkit/orchestration/task_manager/_alert_step.py` →
  `detectkit/alerting/orchestrator/`): for each enabled alerting config, finds
  the last complete interval, evaluates no-data → anomaly quorum → recovery, and
  dispatches templated messages to channels. Reads `_dtk_detections` /
  `_dtk_datapoints`, writes alert state to `_dtk_alert_states`.

Failures are caught per metric; a project-level error alert can fire once and
abort the remaining metrics (`detectkit/orchestration/error_dispatch.py`).

## Module map

```
detectkit/
├── cli/                         # Click CLI (dtk)
│   ├── main.py                  # entry point, command wiring
│   ├── commands/                # run, autotune, tune, init, init_claude, test_alert, unlock, clean
│   └── assets/claude/           # context shipped by `dtk init-claude` (rules, skills)
├── config/                      # pydantic config models
│   ├── project_config.py        # ProjectConfig + paths/tables/timeouts/error_alerting
│   ├── profile.py               # ProfileConfig / ProfilesConfig (+ create_manager)
│   ├── metric_config.py         # MetricConfig, DetectorConfig, AlertConfig, QueryColumnsConfig
│   ├── metric_io.py             # shared metric-YAML seams: nested-form unwrap, safe filename stem,
│   │                            #   collision-safe metrics/.history archive (tune Apply + ui editor)
│   └── validator.py             # validate_metric_uniqueness / validate_project_metrics
├── core/
│   ├── interval.py              # Interval parser ("10min"/"1h"/"1d"/seconds)
│   └── models.py                # ColumnDefinition, TableModel (DB-agnostic DDL spec)
├── database/
│   ├── source_manager.py        # SourceDatabaseManager ABC (minimal hybrid-source contract: execute_query + close)
│   ├── manager.py               # BaseDatabaseManager (generic, table_name-keyed interface; subclasses SourceDatabaseManager)
│   ├── clickhouse_manager.py    # ClickHouseDatabaseManager
│   ├── _sql_manager.py          # SQLDatabaseManager (shared base for Postgres/MySQL)
│   ├── postgres_manager.py      # PostgresDatabaseManager (psycopg2)
│   ├── mysql_manager.py         # MySQLDatabaseManager (pymysql)
│   ├── duckdb_manager.py        # DuckDBDatabaseManager (in-process file DB + DB-API adapter; md: paths = MotherDuck cloud)
│   ├── snowflake_manager.py     # SnowflakeSourceManager (source-only; key-pair/password auth, UTC session, col folding)
│   ├── bigquery_manager.py      # BigQuerySourceManager (source-only; key-file/ADC/anonymous auth, SELECT 1 probe, no col folding)
│   ├── tables.py                # TableModel factories for all _dtk_* tables
│   └── internal_tables/         # InternalTablesManager: per-table mixins over the manager
├── loaders/
│   ├── metric_loader.py         # SQL execution, gap filling, seasonality extraction
│   ├── errors.py                # SourceDatabaseError (hybrid source-vs-state distinction)
│   └── query_template.py        # Jinja2 SQL rendering (StrictUndefined)
├── detectors/
│   ├── base.py                  # BaseDetector, DetectionResult, detector_id hashing
│   ├── factory.py               # DetectorFactory registry
│   ├── seasonality.py           # seasonality mask + JSON parsing
│   └── statistical/
│       ├── _windowed.py         # WindowedStatDetector template (shared pipeline)
│       ├── mad.py / zscore.py / iqr.py   # thin subclasses (stats + interval + severity)
│       ├── manual_bounds.py     # ManualBoundsDetector (stateless thresholds)
│       └── autoreg.py           # AutoregDetector (prediction-based AR(p); own BaseDetector subclass)
├── alerting/
│   ├── orchestrator/            # AlertOrchestrator: decision / cooldown / recovery / dispatch
│   └── channels/                # base + factory + mattermost/slack/telegram/email/webhook
│                                #   + discord/teams/googlechat/ntfy (channels wave 1)
├── orchestration/
│   ├── task_manager/            # TaskManager: run-level lock + _load/_detect/_alert steps
│   └── error_dispatch.py        # project-level error alert (shared by CLI + TaskManager)
├── autotune/                    # `dtk autotune` engine (separate from load/detect/alert)
│   ├── autotuner.py             # AutoTuner facade + run_autotune_engine + alert-window sweep
│   ├── runner.py                # autotune_from_data: cap→scoring→ground-truth→settings→engine (CLI + dtk tune)
│   ├── labels.py / scoring.py / distribution.py / crossval.py   # ground truth, metrics, CV
│   ├── seasonality_search.py / detector_select.py / grid_search.py / window_select.py  # stages
│   ├── axis_spec.py             # per-detector-type AxisSpec: which grid axes apply + floors + max CV context
│   └── result.py / config_emitter.py / settings.py / _types.py / _base.py
├── reporting/                   # self-contained HTML reports (`dtk run/autotune --report`)
│   ├── builder.py               # build_report_payload: reads _dtk_* + replays alerts → JSON
│   ├── html_report.py           # render_report_html: inlines assets/report.js + payload
│   └── assets/report.js         # committed renderer bundle (shared core; ships in the wheel)
├── tuning/                      # `dtk tune` interactive manual tuning (write-back into metric YAML)
│   ├── payload.py               # build_tune_payload: bakes raw series + seeded detector config → JSON
│   ├── html.py                  # render_tune_html: inlines assets/tune.js + payload
│   ├── config_writer.py         # apply_tuned_config: validate → archive to metrics/.history → re-emit in place
│   ├── server.py                # serve_tuner/build_tune_server: localhost write-back (POST /apply, /labels, /autotune)
│   └── assets/tune.js           # committed renderer bundle (shared detector port; ships in the wheel)
├── ui/                          # `dtk ui` project-wide monitoring cockpit (superstructure over CLI subprocesses)
│   ├── overview.py              # build_overview_payload: per-metric alert-frequency/quality stats (replay-based)
│   ├── jobs.py                  # JobManager: subprocess registry + output pumping
│   ├── server.py                # build_ui_server/serve_ui: routes, token auth, db_lock (no pipeline lock)
│   ├── metric_files.py          # metric YAML create/update/delete: validate → archive to .history → write
│   ├── html.py                  # render_ui_html: inlines assets/ui.js + boot payload (mirrors tuning/html.py)
│   └── assets/ui.js             # committed bundle (generated by website/scripts/gen-ui-bundle.mjs)
├── semantic/                    # OSI (Open Semantic Interchange) interop — `dtk osi` (isolated; pipeline never imports it)
│   ├── osi_model.py             # lenient pydantic OSI models + custom_extensions / ai_context helpers
│   ├── query_gen.py             # OSI expr → ClickHouse/Cube series SQL (sqlglot; additive allowlist + hard-refuse)
│   ├── importer.py              # OSI metric → native MetricConfig scaffold (`dtk osi import`)
│   └── exporter.py              # MetricConfig → OSI fragment + custom_extensions[detectkit] (`dtk osi export`)
├── mcp/                         # `dtk mcp` read-only MCP server (isolated; pipeline never imports it)
│   ├── context.py               # McpContext: project load + no-DDL managers + session --select scope
│   ├── tools.py                 # the 10 read-only tools (list/get/status/query/replay/history/incidents)
│   ├── serialize.py             # ISO-8601 + numpy→JSON-safe conversion at the tool boundary
│   └── server.py / errors.py    # FastMCP wiring (lazy `mcp` SDK import) + friendly extra-missing error
└── utils/                       # datetime, json (sorted/orjson), env interpolation, stats
```

A root-level **`action.yml`** (composite GitHub Action) wraps the CLI for CI:
installs detectkit from PyPI, runs `dtk run`/`autotune`/`clean` in the given
project dir, preserves the 0/1/2 exit-code contract as the job outcome and
exposes the `dtk run --json` summary as an output. Self-contained example in
`examples/action-smoke/` (DuckDB, series synthesized in SQL) + a smoke
workflow; `uses: alexeiveselov92/detectkit@<tag>` resolves it — the vX.Y.Z
release tags double as action versions.

## Database layer

`detectkit/database/manager.py` defines `BaseDatabaseManager`, an abstract
interface of **generic** operations keyed by `table_name` — it deliberately does
**not** hardcode logic for any specific `_dtk_*` table:

- `execute_query(query, params)` → list of row dicts
- `create_table(table_name, table_model, if_not_exists)` — DDL from a `TableModel`
- `table_exists(table_name, schema)`
- `insert_batch(table_name, data, conflict_strategy)` — columns as numpy arrays
- `get_last_timestamp(table_name, metric_name, timestamp_column)`
- `upsert_task_status(...)` and `upsert_record(table_name, key_columns, data)`
- `delete_rows(table_name, where_clause, params, sync)` — the one generic delete
  primitive (ClickHouse renders `ALTER TABLE … DELETE`; SQL backends `DELETE FROM`)
- `final_modifier` — dedup-read modifier (`" FINAL"` on ClickHouse, `""` elsewhere)
- `internal_location` / `data_location` properties + `get_full_table_name(...)`

Four backends implement this interface:

- `clickhouse_manager.py` (`ClickHouseDatabaseManager`) — native protocol via
  `clickhouse-driver`. Auto-creates the internal/data databases on connect.
  ClickHouse has no native UPSERT, so `upsert_task_status` / `upsert_record` use
  `ALTER TABLE … DELETE` (with `mutations_sync = 1`) followed by `INSERT`, and
  dedup relies on `ReplacingMergeTree` + `FINAL` reads.
- `_sql_manager.py` (`SQLDatabaseManager`) — shared base for the two standard-SQL
  backends. Owns the DB-API flow once (cursor → dict rows, transactions, numpy →
  driver coercion, DDL rendering with an **enforced PRIMARY KEY** and per-dialect
  type mapping, version-aware upserts). Dialect hooks: `_connect`,
  `_ensure_locations`, `_TYPE_MAP` / `_string_type`, `_build_insert_sql`.
- `postgres_manager.py` (`PostgresDatabaseManager`, psycopg2) — connects to a
  `database` and uses **schemas** (`CREATE SCHEMA IF NOT EXISTS`); dedup via
  `INSERT … ON CONFLICT DO UPDATE` guarded by the version column.
- `mysql_manager.py` (`MySQLDatabaseManager`, pymysql, MySQL 8.0+) — uses
  **databases** (`CREATE DATABASE IF NOT EXISTS`); dedup via `INSERT … ON
  DUPLICATE KEY UPDATE` (row-alias form). PK `String` columns render as
  `VARCHAR(255)` (TEXT can't be PK-indexed). **MariaDB** is supported through
  this same manager: the vendor is sniffed at connect (`SELECT VERSION()`), and
  a detected MariaDB server falls back to the pre-8.0.19 `VALUES()` upsert form
  (the row-alias form is MySQL-only); `type: mariadb` is an identical profile
  alias for clarity.
- `duckdb_manager.py` (`DuckDBDatabaseManager`, duckdb >= 1.1) — an
  **in-process single-file** backend (no server/credentials; profile takes
  `path` — or `:memory:`, tests-only since it breaks resume — plus optional
  `read_only`). DuckDB's Python API takes `$name`/`?` placeholders and
  autocommits, so a small **DB-API adapter** (placeholder translation
  `%(name)s → $name`, lazy explicit transactions, cursor context manager)
  lets the shared `SQLDatabaseManager` flow and every internal-tables query
  run unmodified; `delete_rows` is overridden (DuckDB reports DELETE counts
  as a result row, not `rowcount`). Upsert is the PostgreSQL `ON CONFLICT`
  shape with the same version guard. The floor is 1.1 because the alert
  step's `timestamp IN %(timestamps)s` list-parameter query only parses from
  duckdb 1.1. Operationally the file is held read-write by **one process at
  a time** (readers need `read_only=True`), so `dtk ui`'s long-lived server
  conflicts with a concurrently spawned `dtk run` — run-then-look; the real
  engine runs in the unit suite (`tests/unit/test_duckdb_manager.py`, no
  Docker). The same manager also speaks **MotherDuck** (DuckDB's serverless
  cloud) through the same `duckdb` client — no new profile type or pip extra
  (rides `[duckdb]`): a `path` of the form `md:<database>` attaches the named
  cloud database (the `motherduck` core extension autoloads on first `md:`
  use — the first connect downloads it, so it needs network access), authed by
  the optional `motherduck_token` profile field passed as the connect config
  (unset → the extension falls back to a `motherduck_token` environment
  variable; an explicit `settings.motherduck_token` wins, the settings-over-pin
  precedent). Everything below the connect is identical (same SQL surface, same
  `ON CONFLICT` upsert, same internal-tables flow), so it is a **full,
  state-capable** backend (`_dtk_*` tables can live on MotherDuck) that also
  doubles as a hybrid-mode source like any full backend. The local-file
  single-writer caveats **do not apply** to `md:` paths — MotherDuck is a
  *served* database, so `dtk ui` and a concurrently spawned `dtk run` against
  the same cloud database coexist (run-then-look is local-files-only). One
  asymmetry: MotherDuck has no `read_only=True` attach, so `read_only` is a
  local-files-only knob, and the strict read-only probe
  (`ensure_locations=False`) skips the forced read-only for `md:` — its purpose
  there (preventing a missing local *file* being created on connect) doesn't
  apply to a served database (the probe still runs no DDL). Tested by
  connect-seam unit tests plus an env-gated real-account smoke
  (`tests/integration/test_motherduck.py`, needs `MOTHERDUCK_TOKEN`).

`ProfileConfig.create_manager()` (`detectkit/config/profile.py`) builds the right
backend from `type`; PostgreSQL additionally requires a `database` connect-target,
DuckDB a `path` (`port` is optional only for DuckDB — a per-type validator
enforces it for the server backends).

### The source-only seam (hybrid mode)

`detectkit/database/source_manager.py` defines `SourceDatabaseManager`, a
minimal ABC — just `execute_query(query, params=None) -> list[dict]` and
`close()` — that captures the **only** contract hybrid mode needs from a source
DB (run a metric's load SQL, return rows). `BaseDatabaseManager` subclasses it,
so every full backend doubles as a source. This lets a **source-only** backend
that can *never* hold `_dtk_*` state (no DDL / upsert / lock methods) still be a
metric's `source_profile`. `ProfileConfig` splits the types into
`STATE_TYPES = {clickhouse, postgres, mysql, mariadb, duckdb}` and
`SOURCE_ONLY_TYPES = {snowflake, bigquery}` (allowed `type` = the union): `create_manager()`
**refuses** a source-only type (`"Profile type 'snowflake' is source-only: …"`),
while the new `create_source_manager()` (on both `ProfileConfig` and
`ProfilesConfig`, keyed by profile name) is the pool's construction seam
(`orchestration/task_manager/_base.py`) — it routes a full type through
`create_manager()` and a source-only type to its dedicated source manager.

- `snowflake_manager.py` (`SnowflakeSourceManager`, extra `[snowflake]` →
  `snowflake-connector-python`) — the first source-only backend. Eager connect
  (a bad profile fails fast on pool build); **key-pair** auth (`private_key_path`
  PEM + optional `private_key_passphrase`, first-class and recommended since
  Snowflake retires single-factor service-account passwords through 2026) **or**
  `password`. The session `TIMEZONE` is pinned to **UTC** in the connect
  `session_parameters` (a user `settings` dict merges over it — explicit choice
  wins), because Snowflake's `TIMESTAMP_LTZ` / `CURRENT_TIMESTAMP` otherwise
  coerce via the session default `America/Los_Angeles`; tz-aware UTC results are
  handled by the loader (since v0.62.0). Snowflake uppercases unquoted
  identifiers, so an all-uppercase result column is **folded to lowercase** in the
  returned row dicts (`name.lower() if name.isupper() else name`) — the loader
  reads `row["timestamp"]` / `row["value"]`; deliberately-quoted mixed-case names
  pass through unchanged. Source-only: valid only as a `source_profile`, never as
  state (billing: each query resumes the warehouse with a 60-second minimum, the
  reason hybrid mode keeps state in a cheap local DB).
- `bigquery_manager.py` (`BigQuerySourceManager`, extra `[bigquery]` →
  `google-cloud-bigquery`) — the second source-only backend. Eager connect: a
  `bigquery.Client(...)` alone does no I/O, so construction runs a free
  `SELECT 1` **probe** (no table references, 0 bytes processed on on-demand
  billing) so a bad `project` / credentials / `settings` typo fails fast at
  hybrid-pool build; retries are **bounded** (probe 30s with job-retry off;
  load queries 120s request-retry / 600s job-retry) because the client
  library's defaults treat connection errors as transient and would retry an
  unreachable endpoint for 10+ minutes — a failed probe also closes the
  just-built client so nothing leaks into the pool's cached error. **Auth
  resolution** — `credentials_json_path` (a service-account JSON key file)
  when set, else **Application Default Credentials** (gcloud ADC / an attached
  service account / Workload Identity); a plain-`http://` `api_endpoint`
  *without* a key file — the BigQuery-emulator path — switches to **anonymous**
  credentials so no ADC lookup is attempted (an `https://` override — regional
  `*.rep.googleapis.com`, Private Service Connect — authenticates normally
  via key file/ADC). `dataset`
  becomes the job's `default_dataset` (unqualified table names in the load SQL
  resolve against it); each `settings` key is applied to a per-query
  `QueryJobConfig` and must name a real `QueryJobConfig` property — a typo would
  otherwise be a silently-ignored attribute, so it is **rejected** at the probe
  (`maximum_bytes_billed`, `labels`, …). BigQuery `TIMESTAMP` columns come back
  **tz-aware UTC** (the loader converts to naive UTC since v0.62.0); `DATETIME`
  comes back naive and is taken verbatim (recommend `TIMESTAMP` or a cast for the
  metric's `timestamp` column). **No** column-name folding (unlike Snowflake,
  BigQuery preserves alias case, so `SELECT ts AS timestamp` reaches the loader
  unchanged). Source-only: valid only as a `source_profile`, never as state
  (billing: on-demand queries bill a **10 MiB minimum** of bytes processed per
  referenced table, so frequent small monitoring queries are disproportionately
  expensive — the reason hybrid mode loads from BigQuery and keeps state in a
  cheap local DB; a `settings: {maximum_bytes_billed: …}` guardrail caps a single
  query).

The `TableModel` carries a `version_column` (the last-writer-wins key encoded as
`ReplacingMergeTree(<col>)` on ClickHouse and driving the version-aware upsert on
SQL backends). The `InternalTablesManager` mixins are backend-neutral: they emit
no ClickHouse-only SQL, routing all deletes through `delete_rows` and dedup reads
through `final_modifier` (locked in by `tests/unit/test_internal_tables_agnostic.py`).

`detectkit/core/models.py` holds `TableModel` and `ColumnDefinition` — the
database-agnostic schema spec the manager turns into backend-specific DDL.

`InternalTablesManager` (`detectkit/database/internal_tables/`) is a high-level
façade over a `BaseDatabaseManager`, assembled from per-table mixins
(`_datapoints`, `_detections`, `_tasks`, `_metrics`, `_alert_states`,
`_autotune_runs`, `_schema`, `_maintenance`). It owns all `_dtk_*` knowledge; the
base manager stays generic.
Alongside the resume-cursor readers (`get_last_datapoint_timestamp` /
`get_last_detection_timestamp`) and `load_datapoints`, it exposes
`load_detections(metric_name, detector_id=None, from_timestamp=None,
to_timestamp=None)` — flat per-(detector, timestamp) rows (dedup-correct via
`final_modifier`) that the reporting layer reads back.

### Internal tables (`detectkit/database/tables.py`)

All are auto-created on first run by `ensure_tables()` (idempotent). All are
keyed by `metric_name`, so removing a metric's YAML leaves orphan rows that
`dtk clean` prunes.

- **`_dtk_datapoints`** — gap-filled metric series. Columns: `metric_name`,
  `timestamp`, `value` (Nullable), `seasonality_data` (JSON), `interval_seconds`,
  `seasonality_columns`, `created_at`. PK `(metric_name, timestamp)`,
  engine `ReplacingMergeTree(created_at)`.
- **`_dtk_detections`** — per-detector results. Columns: `metric_name`,
  `detector_id`, `detector_name`, `timestamp`, `is_anomaly`, `confidence_lower/upper`,
  `value` (original), `processed_value` (smoothed/transformed), `detector_params`
  (JSON), `detection_metadata` (JSON: severity/direction/etc.), `created_at`.
  PK `(metric_name, detector_id, timestamp)`, engine `ReplacingMergeTree(created_at)`.
- **`_dtk_tasks`** — pipeline locks + resume state. Columns include `status`,
  `started_at`, `updated_at`, `last_processed_timestamp`, `error_message`,
  `timeout_seconds`. PK `(metric_name, detector_id, process_type)`,
  engine `MergeTree` (replaced via DELETE+INSERT).
- **`_dtk_alert_states`** — alert state per alerting config (not per detector).
  Columns: `metric_name`, `alert_config_id` (hash of the alert config),
  `last_alert_sent`, `last_recovery_sent`, `alert_count`, `updated_at`.
  PK `(metric_name, alert_config_id)`, engine `ReplacingMergeTree(updated_at)`.
- **`_dtk_metrics`** — **informational only** (for dashboards; does not affect
  logic). Mirrors each metric's config (interval, loading params, alert settings,
  tags, enabled). Rewritten every run via DELETE+INSERT. Engine `MergeTree`.
- **`_dtk_autotune_runs`** — one row per `dtk autotune` run (audit trail; does
  **not** affect logic). Inputs + outputs of the whole tuning pipeline: training
  period, `labels_json`, `mode`, `scoring_metric`, `score`,
  `chosen_seasonality_json`, `chosen_detector_type`/`chosen_detector_params_json`,
  `winning_detector_id`, `candidate_detector_ids_json`, `decision_log_json`,
  `generated_config_text`, `status`. PK `(metric_name, run_id)`, engine
  `ReplacingMergeTree(created_at)`. Deliberately excluded from
  `dtk clean --orphaned-metrics` (`_maintenance.METRIC_KEYED_TABLES`).

Dedup strategy: PRIMARY KEY + `INSERT IGNORE` semantics. For datapoints /
detections / alert-states this is reinforced by `ReplacingMergeTree`, which
collapses duplicate keys by the version column (`created_at` / `updated_at`).

## Detection

`detectkit/detectors/base.py` defines `BaseDetector`. Each detector implements
`_validate_params()` (fail fast at construction), `detect(data) ->
list[DetectionResult]`, and `_get_non_default_params()`. `data` is the dict from
the loader (`timestamp`, `value`, `seasonality_data`, `seasonality_columns`),
including the historical context window. Shared preprocessing helpers
(`_preprocess_input` for `input_type`, `_apply_smoothing` for EMA/SMA) live here.

`get_context_size()` reports how many historical points the detect step must load
before the first scored point (window size + smoothing warm-up + 1 for
change-based `input_type`).

**Detector identity.** `get_detector_id()` = first 16 hex chars of
`sha256(class_name + version_tag + sorted(non_default_params))`. **Every
parameter that changes detection output is hashed** — `threshold`,
`window_size`, `seasonality_components`, `smoothing`, weighting, `detrend`, etc.
Changing any of them yields a new `detector_id`, so detections recompute under
the new id instead of silently mixing two regimes in `_dtk_detections`.
`ALGORITHM_VERSION` feeds the hash too, so an algorithm change forces
recomputation for the same params (the windowed detectors are at v2).

**Windowed statistical detectors.** `detectkit/detectors/statistical/_windowed.py`
(`WindowedStatDetector`) is a template-method base owning the entire per-point
pipeline: preprocessing → trailing window (current point excluded) with NaN
filtering → optional **time-aware recency weighting** → optional **robust linear
detrending** (split-median slope) → global statistics + per-seasonality-group
multipliers → confidence interval, anomaly flag, severity/direction metadata.
Opt-in **`stabilization: clamp`** changes what later windows *see*, not what gets
scored: once a point is flagged anomalous, it is winsorized to the confidence
bound it violated before entering any later trailing window (global or
seasonality-group), so a sustained incident can't inflate the spread and drag
the band wide enough to mask its own tail; `get_context_size()` adds one extra
`window_size` of warm-up when it's enabled, so an incremental batch reproduces
the same substitution history a continuous run would see.
A seasonality group's multiplier engages only when the trailing window holds
`min_samples_per_group` points of the current point's key; since same-key points
recur once per *cardinality*, the window must span ≈ `min_samples_per_group ×
distinct_keys` (hourly `hour` ⇒ ≈ 240) or **every** point falls back to the global
band — a silent no-op at the default `window_size = 100`. `detect()` logs a
one-time warning (`_warn_if_groups_cannot_fill`) when the window is too small to
ever fill a group.
Subclasses add only class-level defaults plus three hooks — `_compute_stats`,
`_build_interval`, `_severity`:

- `mad.py` (`MADDetector`) — median + MAD; MAD scaled by **1.4826** so
  `threshold` is in σ-equivalents comparable with z-score (default 3.0).
- `zscore.py` (`ZScoreDetector`) — mean + std.
- `iqr.py` (`IQRDetector`) — q1/q3 + IQR.

Keep the windowed detectors detector-agnostic: a new statistical detector should
implement only the three hooks + defaults, never duplicate the pipeline.

`detectkit/detectors/statistical/manual_bounds.py` (`ManualBoundsDetector`) is
**separate and stateless** — no window, no statistics, just user `lower_bound` /
`upper_bound` checks (with optional `input_type`). It extends `BaseDetector`
directly.

`detectkit/detectors/statistical/autoreg.py` (`AutoregDetector`, type
`autoreg`) is detectkit's first **prediction-based** detector: per point it
fits AR(`lags`) on a trailing `window_size` window (numpy-only normal
equations with a tiny ridge + `lstsq` fallback), predicts ŷ from the previous
`lags` values and flags `|y − ŷ| > threshold·σ_r`, emitting the natural band
`ŷ ± threshold·σ_r` — it catches *dynamics/shape* anomalies (a value normal in
absolute terms but wrong given the last few points) that the level-modeling
windowed detectors can't. It is a **deliberate, documented exception** to the
"reuse the windowed template" rule — its own `BaseDetector` subclass, because
the template's NaN-gap window splicing would fabricate lag pairs and
seasonality multipliers are meaningless for a lag model. `stabilization:
"clamp"` is **default-on** (flagged points enter later fits clamped to the
violated bound — clamping, not ŷ-substitution, for the same band-collapse
reason as the windowed clamp); v1 has no seasonality/smoothing/weighting and a
strict NaN policy (a gap in the lag view → no score, never imputed; fit rows
with gaps are dropped, `min_samples` valid rows required).
`get_context_size() = window_size + lags` (+1 for change-based input, +
another `window_size` with stabilization). **Numerics (ALGORITHM_VERSION 2,
measured on NAB):** each fit window is centered/scaled before the normal
equations (an intercept column of ones next to raw ~1e9-scale lag columns
puts the Gram matrix's conditioning beyond float64 — garbage fits that the
clamp then amplified to inf), and the clamp substitution is capped to the
observed window range so a degenerate fit can never write an astronomic value
into later history; detection flags are affine-invariant. Fully **autotunable**
(via its `AxisSpec` — threshold/lags/stabilization/window axes only, see
Auto-tuning below) and **tunable in the `dtk tune` cockpit** (a `runAutoreg`
branch in the parity-checked TS port + a Lags knob; the windowed-only knobs
hide). The cockpit also exposes a **Min samples** knob (fit-rows floor, shown
for autoreg + the windowed detectors, hidden for `manual_bounds`), because an
autotune winner sized for a large window can carry a `min_samples` so high that
a smaller window/view can't collect it (the band then never appears, and there
was previously no way to lower it); the knob is **capped at the window size**
(its max tracks the Window slider) and the TS port clamps the effective
`min_samples` into `[lags + 2, window_size]` — mirroring the Python constructor's
validation and the config the cockpit emits, so the live band matches what Apply
would write instead of wedging to blank when `min_samples > window`.

`detectkit/detectors/factory.py` (`DetectorFactory`) is the registry mapping
type names to classes: `mad`, `zscore`, `iqr`, `manual_bounds`, `autoreg`,
and the alias `manual`.

## Alerting

The model is **alert-centric**: messages lead with the alert and the rule it
fired on; the anomaly is supporting evidence. The orchestrator
(`detectkit/alerting/orchestrator/`) is composed of mixins —
`_decision`, `_cooldown`, `_recovery`, `_dispatch`, `_replay`.

`_replay.py` adds a **pure** `AlertOrchestrator.replay(detections, value_at,
start, end) -> list[ReplayedEvent]` that reconstructs the alert / recovery /
no-data timeline over a historical period from persisted detections by
re-walking the *same* decision logic (quorum / consecutive / cooldown / recovery
/ no-data) — **no channel dispatch, no `_dtk_alert_states` writes, no
wall-clock**. The reporting layer uses it to surface alerts (`_dtk_alert_states`
is last-writer-wins state, not an event log). It reuses the decision/builder
functions verbatim; `_resolve_incident` (`_recovery.py`) takes an optional
in-memory `records=` so recovery resolution stays DB-free during replay (the
production path is unchanged).

**Per-point quorum** (`_decision.py`): for each timestamp, the quorum is the set
of anomalous detections matching the `direction` policy —

- `up` / `down`: only that-direction anomalies count.
- `any`: every anomaly counts (an up- and a down-anomaly can together meet
  `min_detectors`).
- `same`: at least `min_detectors` must agree on **one** direction; the winning
  direction is then locked for the consecutive walk.

An alert fires only when the latest `consecutive_anomalies` timestamps each meet
the quorum **and** are exactly one metric interval apart (grid adjacency — a gap
breaks the chain). The payload is built from the highest-severity record of the
latest quorum, with deterministic tie-breaks (name, then id).

**Fraction alert window** (opt-in, OR-ed with the consecutive rule): the
`AlertConfig` pair `anomaly_window` (duration/seconds → grid points via
`AlertConditions.from_alert_config`, the single seam shared by
`_alert_step.py` and `builder.replay_alert_events`) + `min_anomaly_share`
(fraction in `(0, 1]`). `_decision._share_fire` fires when the share of
quorum-meeting grid slots over the trailing window reaches the threshold
**and** the latest point itself meets the quorum (a stale window never fires);
for `same` the direction locks from the latest quorum, exactly like the
consecutive walk. Missing slots count in the denominator only (an outage makes
the rule *harder* to fire). The fetch width is `conditions.lookback_points =
max(consecutive, window_points)` (recovery adds +5). Recovery gains
**hysteresis** (`_share_still_elevated`, live + replay): besides a clean
latest point, the window share must drop below **half** the threshold, so the
alert can't flap around the boundary. Share-fired payloads carry
`window_points`/`window_matched`/`min_anomaly_share`/`fired_by_share` on
`AlertData`; `consecutive_count` holds the matched count and the onset is the
oldest matched slot the window can see. The new fields join
`make_alert_config_id` **only when set**, so existing configs keep their ids
and alert state. The rule chip on every channel renders through the shared
`format_rule_display` (`channels/base.py`) → `{rule_display}` — legacy
configs render byte-identically; a share-configured config names both OR-ed
rules; a share-fired alert leads with the share rule and a window-story lead
sentence instead of the consecutive-duration one. Both optimization paths
tune the pair: supervised autotune sweeps it 2-D (window × share, OR-ed with
the chosen consecutive rule — see Auto-tuning), and the `dtk tune` cockpit
has anomaly-window/min-share rail controls whose fires the worker replays
with the same latest-point-gate/denominator semantics.

Other behaviors: **suppression** — `suppress_until` skips a config's alert step
entirely while `now <` the deadline (load/detect keep running); its accepted
spellings live in one seam, `parse_suppress_until` (`config/metric_config.py`),
shared by the `AlertConfig` validator and `_alert_step.py`, so a malformed value
is refused at config load / at a `dtk ui` save instead of raising mid-run out of
a strict `strptime` (it also accepts the date-only form the docs' own examples
use); **cooldown** (`_cooldown.py`) suppresses repeat alerts within
`alert_cooldown`, optionally reset on recovery; **recovery** (`_recovery.py`)
sends a direction-aware all-clear once per incident when `notify_on_recovery`.
Its payload is **anchored on the incident's firing detector**: `_resolve_incident`
already re-walks the quorum to reconstruct the span, so it also returns that
quorum's `_primary_record`, and `_recovery_source` renders **that** detector's
band at the recovered point. Taking `detections[-1]` instead (the old behavior)
picked whichever `detector_id` sorted last in `get_recent_detections`'s
`ORDER BY timestamp DESC, detector_id` — so a metric pairing a MAD band with a
`manual_bounds` floor fired on `[249.34, 418.61]` and cleared on `>= 30.00`,
evidence from a detector that never fired (issue #159). A **one-sided** band
(`manual_bounds` with only `lower_bound`) is a band, not a missing one — the
no-band fallback requires *both* bounds absent, or every one-sided detector
would inherit an unrelated record's numbers. Note this is *rendering* only:
detectors stay **metric-level** and every alerting block quorums over all of
them (`AlertConfig` has no detector filter — scoping is issue #160).
**no-data** alerts fire when the latest expected datapoint is missing/NULL
(independent of quorum) — `get_last_complete_point` is both `loading_delay`- and
**grid-phase**-aware (two scalars ride as constructor state on the orchestrator,
so every call site, including the recovery mixin, agrees on the same boundary).
The delay shifts the effective now back; the **grid phase**
(`loading_start_time_epoch % interval`, resolved via `resolve_grid_phase_seconds`
— the mirror of `resolve_loading_delay_seconds`) then floors onto the metric's
**own** interval grid rather than plain epoch time, so the no-data check's
exact-timestamp lookup asks for a boundary the loader actually persisted. Without
it, a metric whose `loading_start_time` isn't epoch-aligned (e.g. `:07` on a
`10min` grid) would look up a boundary the loader never writes and false-fire
every cooldown cycle — issue #114 (phase 0 = the epoch grid, so epoch-aligned
metrics are unchanged; the anomaly/recovery/replay paths were never affected,
their fetches being `<=`-bounded not exact-match). State (last alert / recovery,
counts) is keyed by `alert_config_id` in `_dtk_alert_states`.

Channels live in `detectkit/alerting/channels/` behind `BaseAlertChannel`;
`AlertChannelFactory` builds them with env-var interpolation. Implemented:
`mattermost`, `slack`, `telegram`, `email`, `webhook`, `discord`, `teams`,
`googlechat`, `ntfy` (Rocket.Chat needs no type of its own — its script-less
incoming webhook accepts the generic `webhook` channel's Slack-style
attachments payload; documented recipe). Every channel defaults
to the **detectkit brand identity** — name + avatar from `channels/branding.py`
(`BRAND_USERNAME`, `BRAND_ICON_URL`, a PNG served from the docs site, generated
by `website/scripts/make-bot-icon.mjs`). Webhook-family channels send the brand
avatar as `icon_url` (override per channel with `icon_url` / `icon_emoji` —
`icon_url` wins, and setting either opts out of the brand avatar); email sets a
`From` display name + an HTML body carrying the logo; Telegram can't override
its bot avatar (set in @BotFather). Project-level error
alerting (`ProjectConfig.error_alerting` → `error_dispatch.py`) notifies on
DB-down / DDL / runtime failures, including early CLI failures before any metric
runs.

**Channels wave 1** (`discord.py` / `teams.py` / `googlechat.py` / `ntfy.py`)
all render natively from the same `build_context` seam, same
`description → Rule → Value/Expected → links → tail` order (the Rule chip only
on anomaly/recovery), transport errors swallowed (`print` + `False`), platform
limits enforced defensively: **Discord** — one status-colored embed (int
color) whose verbose tail rides in a compact inline field grid (Discord has no
"Show more" fold), brand `username`/`avatar_url`, mentions in top-level
`content` + `allowed_mentions` (`<@id>` pings pass through verbatim; bare
names render but don't ping), per-part caps plus the 6000-char embed-total
budget with newline-boundary truncation. **Teams** — the Power Automate
Workflows webhook path (the retired O365 connector's MessageCard payloads are
dead): `{type: message, attachments: [Adaptive Card 1.4]}`, status via
TextBlock color (Attention/Good/Warning/Accent), FactSet evidence,
`Action.OpenUrl` links; posts under the flow's identity — no branding, and
mentions render as plain text (real pings would need AAD-id mention
entities). **Google Chat** — space incoming webhook, Cards v2 only: brand
avatar + `detectkit · <project>` in the card header, HTML-escaped
`decoratedText` evidence rows (`<br>` not `\n`), `buttonList` links (button
text is plain text — deliberately unescaped), `<users/all>`/`<users/USER_ID>`
mention tokens in top-level `text` (the only place a ping fires). **ntfy** —
JSON publish to the server root (headers can't carry UTF-8): per-kind
priority (anomaly/error 4, else 3; a `priority` knob overrides only
anomaly/error) and tag emoji as the status cue (the title's status dot is
stripped so the glyph isn't doubled), `click` = dashboard, up to 3 view
actions, Bearer-token or basic auth, 3800-byte message cap.

**Default rendering is platform-native** (no custom `template`). The value
computation behind all of it is shared: `BaseAlertChannel.build_context` is the
single source feeding both custom templates and native rendering. A metric's OSI
`ai_context.synonyms` (`MetricConfig.ai_context`, mirroring the Open Semantic
Interchange `ai_context` shape — `instructions`/`synonyms`/`examples`, accepting a
bare string → `instructions`) ride through to `build_context` as the **opt-in**
`{synonyms}` / `{synonyms_line}` variables (stamped via `AlertData.ai_synonyms`,
`_alert_step.py` → `_OrchestratorBase`), but the **default** templates and native
renderers deliberately do **not** render them — so existing alerts stay
byte-identical and a custom `template` opts in. `ai_context` is descriptive only:
it never touches the pipeline, `detector_id`, or alert decisions; it is also baked
into the `dtk tune` cockpit payload (read-only grounding). This is detectkit's
first, additive step of OSI support — no runtime dependency on OSI. Every alert
title/headline leads with a colored **status circle** so the status reads from
color alone — 🔴 anomaly, 🟢 recovery, 🟡 no-data, 🔵 pipeline error
(`BaseAlertChannel._STATUS_EMOJI` / `status_color`, kept in sync with the
`--st-*` brand tokens). It then leads with the **project name** as a
`{project_name_prefix}` (`[name] `) on every kind, so multiple projects sharing
one channel stay distinct while keeping the brand bot name + avatar. The
orchestrator stamps `AlertData.project_name` from `ProjectConfig.name`
(`_alert_step.py` → `_OrchestratorBase`); the webhook/email footers also pair it
with the brand name (`detectkit · <project>`). Direct-API callers leave it
`None` and render unchanged.

- **Slack / Mattermost / generic webhook** (all via `WebhookChannel`) render an
  alert as **one status-colored attachment** whose whole body rides in a single
  markdown `text` block, ordered **most-important-first** so the platform's
  native fold hides the verbose tail and nothing else. This mirrors a reference
  AlertManager alert: one block, one color (the left accent bar), collapsed
  behind **"Show more"** when long. The body order is: the markdown lead (the
  duration sentence, see "Incident timing" below) with the **Rule** chip beneath
  it → **Value / Expected** → the compact **Links** line (dashboard + extra links
  + the "how to read this alert" guide as clickable labels, never raw URLs) → then
  the verbose tail (Quorum / Severity / the anomalous span — Anomaly began →
  Latest reading; began → fired → recovered on recovery — / Detectors /
  Parameters as a fenced code block). The title (clickable, linking to
  `dashboard_url` when set) leads above it all. This works because both clients
  fold **only** the attachment's `text` and render the `title`, the color bar and
  the **`footer`** *outside* that fold (Slack collapses `text` above 700 chars /
  5 line breaks; Mattermost wraps only the `text` in its `maxHeight`-200px
  `<ShowMore>` — `fields`/`footer`/`title` are siblings rendered after it). So the
  branded **footer + footer_icon (the brand logo)** rides on that single
  attachment and **stays visible even when the body is collapsed** — the prior
  two-card split (a neutral second attachment with the tail) is gone, because it
  read as a second, differently-colored alert and its short `text` never tripped
  the fold. No-data / error stay short, single un-folded cards; a long anomaly (or
  a full onset → fired → recovered recovery) folds its tail.
  `@mentions` ride in the **top-level** message text so they notify on Slack. A
  custom `template` still renders as a single plain text-only attachment (the raw
  template replaces the structured lead/Value/tail sections; color/title/branding
  kept). The generic webhook channel (`type: webhook` only) additionally takes a
  `format` knob — `attachments` (default, the rendering above, unchanged) /
  `json` (a versioned structured event, `schema_version: 1`) /
  `alertmanager` (a Prometheus Alertmanager webhook-receiver payload, v4 —
  trigger/resolve pairs sharing identical labels/fingerprint) — and an optional
  `secret` that HMAC-SHA256-signs the raw request body into
  `X-Detectkit-Signature-256`; `json`/`alertmanager` bypass the attachment
  rendering entirely and ignore a custom `template`.
- **Telegram** defaults to `parse_mode: HTML` (was Markdown). The default
  message is structured and HTML-escaped: a colored status dot (red anomaly /
  green recovery / yellow no-data / blue error), a bold headline, the lead +
  rule, then evidence in `<code>` (value / expected / quorum / severity /
  began → latest / detector / params), an inline "Open dashboard" link, then
  mentions. This fixes a real bug — the old Markdown mode raised `can't parse
  entities` on params JSON containing underscores (e.g. `window_size`). Custom
  templates are sent verbatim under the parse mode (so keep them HTML-safe; set
  `parse_mode: Markdown` for the old behavior).
- **Email** sends a branded HTML card (inline-CSS, table-based, Outlook-safe) —
  colored accent + status pill, the metric, the lead + Rule chip, a 2-col stat
  grid (value / expected / severity / quorum / anomaly began / latest reading;
  began / alert fired / recovered on recovery), a monospace
  params box, an optional "Open dashboard" button, and a footer; the plain-text
  body remains the multipart fallback.

**Message order is uniform** — `description → Rule → Value/Expected` on every
channel and for both anomaly and recovery (previously the anomaly led with the
Rule, recovery with the description; now both lead with the description). The
**firing rule is set apart uniformly**: a bold **Rule** label + an inline-code
chip (`min_detectors=… · direction=… · consecutive=…`). Bold is platform-aware
on webhook channels (`*Rule*` Slack mrkdwn vs `**Rule**` Mattermost/generic
CommonMark, via `WebhookChannel._bold`, mirroring `_link_markup`); Telegram
renders `<b>Rule</b> <code>…</code>`; email renders the same bold-label +
monospace chip via `EmailChannel._rule_html`. The backtick/`<code>` chip renders
identically everywhere; custom templates and the plain-text fallbacks follow the
same order.

**Incident timing — "how long has this been going on".** Every default-rendered
anomaly leads with a plain-language sentence — `Anomalous for 2h 30m — 15
consecutive 10min intervals.` — that surfaces the metric **interval**, the
**true streak length** and the wall-clock **duration**; the **Anomaly began /
Latest reading** fields bound the span. The timing labels are deliberately
self-describing so a stakeholder can't misread the onset as the alert-fire
moment: **Anomaly began** is the resolved onset (first anomalous point), **not**
when the alert fired. Recovery shows the fuller **began → fired → recovered**
timeline (`Incident lasted …`): **Alert fired** is the on-grid moment the rule
first tripped, computed in `build_context` as `onset + (consecutive_required −
1) × interval` (so no orchestrator change), exposed as `fired_display` and
omitted when the run is capped (onset is only a lower bound) or timing isn't
wired in; the firing message doesn't show it (it coincides with the latest
point). The decision only needs `consecutive_anomalies` points, so the *true*
streak/onset is resolved **only when an alert fires/clears**: `_decision.py`
(`_resolve_streak`) and `_recovery.py` (`_resolve_incident`) load up to
`STREAK_LOOKBACK_POINTS` (`_base.py`) detections and re-walk the same
direction-aware quorum logic; a run older than the window renders as `over …`.
The result rides on `AlertData.interval_seconds` / `onset_timestamp` /
`streak_capped` (`consecutive_count` now carries the *true* streak), and
`BaseAlertChannel.build_context` turns it into the shared `anomaly_lead` /
`recovery_lead` / `window_line` / `duration_display` / `fired_display` values.
The hot no-alert path is untouched (no extra query).

Two `AlertConfig` fields (`detectkit/config/metric_config.py`) drive the action
links, surfaced as first-class actions on every channel: **`dashboard_url`** (a
dashboard/runbook URL — clickable title on webhook channels, inline link on
Telegram, an "Open dashboard" button in email, and exposed to templates as
`{dashboard_url}` / `{dashboard_line}`) and **`links`** (a `{label: url}` map of
extra links appended alongside it).

Separately, every default-rendered alert also carries a **"How to read this
alert"** help link aimed at non-operator stakeholders. On webhook channels it
joins `dashboard_url` + `links` in one compact **Links** field of clickable
labels (never raw URLs — a Grafana URL can be paragraph-long; rendered with
`_link_markup` in Slack `<url|label>` vs Mattermost markdown-link syntax); it is
a links-line entry on Telegram, a footer link in email, and
`{help_url}` / `{help_line}` for templates. It defaults to the
brand guide (`BRAND_ALERT_GUIDE_URL` → the `/guides/reading-alerts/` docs page,
in `channels/branding.py`) and is controlled **project-wide** by
`ProjectConfig.alert_help_url` (tri-state: unset → default guide, a URL → your
own runbook, `false` → hide). `resolve_alert_help_url()` resolves it; the
orchestrator (and the error-dispatch path) stamps the result onto
`AlertData.help_url`. Unlike `dashboard_url`/`links`, it is a project-level
constant rather than per-`AlertConfig`.

## Reporting (`dtk run --report`)

`detectkit/reporting/` turns the persisted internal tables into one
**self-contained HTML report** per metric — the same self-contained offline
delivery model (inline JS, baked payload, nothing leaves the browser). It lets a
user *see how a metric actually performed* — values +
per-detector confidence bands + flagged anomalies + the alerts that fired + a
summary, with client-side period selection (24h / 7d / 30d / All + zoom/pan) and
an alerts list — without standing up BI / SQL / a 3rd-party charting tool.
`dtk run --report [PATH]` (after a run) and `dtk autotune --report [PATH]` (for
the tuned winner) both emit one; because the builder reads the stored `_dtk_*`
rows, even a `--steps load` run can produce one. `--report` is dual-mode: bare
`--report` → default path (`reports/<metric>.html`; autotune:
`reports/<metric>__tuned_<id>.html`), `--report <dir>` → `<dir>/<metric>.html`,
`--report file.html` → that file (`_resolve_report_path` in
`cli/commands/run.py`).

The pipeline is two pure functions:

- `builder.build_report_payload(...)` reads `_dtk_datapoints` +
  `_dtk_detections` (via `load_datapoints` / `load_detections`) and **replays
  alerts** into a JSON payload. The detector band series is derived straight from
  the stored detection rows, so the report shows *what actually ran*.
- `html_report.render_report_html(payload)` inlines the pre-built renderer bundle
  `detectkit/reporting/assets/report.js` + the baked payload into one HTML file.

**Alert replay seam.** Alerts are not read from `_dtk_alert_states` (that is
last-writer-wins *state*, not an event log). Instead the builder calls the pure
`AlertOrchestrator.replay(...)` (`alerting/orchestrator/_replay.py`,
returning `ReplayedEvent`s) to reconstruct the anomaly / recovery / no-data
timeline over the period by re-walking the **real** decision logic, with no
dispatch, no state writes and no wall-clock (see the Alerting section).

**Shared rendering core.** `assets/report.js` is a committed generated asset (the
`bot-icon.png` generated-asset pattern) built by
`website/scripts/gen-report-bundle.mjs` from the **same** framework-free
TypeScript core (`website/src/scripts/core/canvas.ts`) shared with the `dtk tune`
cockpit and the website's interactive playground, so all three draw from one
low-level rendering core. The bundle ships in the wheel
(`[tool.setuptools.package-data]` `"detectkit.reporting" = ["assets/*.js"]` +
MANIFEST.in) and must be regenerated when the renderer TS changes.

## Auto-tuning (`dtk autotune`)

`detectkit/autotune/` is a **separate offline pipeline** from load/detect/alert,
invoked by `dtk autotune --select <metric>` (`cli/commands/autotune.py`). Given a
metric's already-loaded `_dtk_datapoints` (and optional labeled incidents), it
chooses the best detector configuration and emits an annotated tuned config; it
never edits the original metric and never alerts. Labeled incidents come from
`dtk tune` (its **Label** mode writes versioned `incidents/<metric>/` files);
`dtk autotune` **auto-discovers** the newest labels in that directory, so after
labeling you just run `dtk autotune --select <metric>` (no `--incidents` flag
needed).

The engine is **pure and DB-free** — it operates on the in-memory `data` dict and
reuses `WindowedStatDetector`/`DetectorFactory`/`detector_id` unchanged. The
command loads data, threads it into `run_autotune_engine(...)`, then persists the
run, emits the config, persists the winner's detections, and prunes superseded
prior winners. The plumbing from a metric's `AutoTuneConfig` + labels to the engine
(cap history → resolve scoring → project ground truth → build `TuneSettings` → run)
is factored into `autotune/runner.py` (`autotune_from_data`), shared verbatim by the
CLI command and the `dtk tune` server's **Autotune** mode (so autotuning in the
cockpit and on the command line are the same computation). Stages
(`AutoTuner.tune()`), each appending to a decision log:

1. **Seasonality search** (`seasonality_search.py`) — greedy over the metric's
   seasonality columns (single-add or merge-into-last to form conjunctive
   groups), rejecting groupings that would under-fill a group. The criterion is
   **decoupled from the flag-objective** (which is structurally biased *against*
   seasonality): a leak-free, walk-forward, **band-width-aware** Gaussian-NLL
   probe (`scoring.oof_residual_reduction`) scores how much conditioning on a
   seasonal key tightens the per-group center/scale the detector actually applies
   — measured on *held-out* folds, so over-fragmented groups fall back to global
   and can't win mechanically; the no-seasonality baseline scores 0, a move is
   accepted only on a margin **and** improvement in the majority of folds.
   `autotune.force_seasonality` pins the grouping and skips the search.
2. **Detector selection** (`detector_select.py`) — a distribution suitability
   spec **keyed by detector type name** (kept here, NOT on the detector classes,
   so detectors stay untouched and the feature is easy to remove). The vote is
   **advisory only**: it *orders* the types (most promising first); the grid
   search then evaluates **all** of them and lets cross-validation pick the
   winner, so a hand-tuned heuristic never excludes a detector.
3. **Grid search** (`grid_search.py`) — bounded coordinate sweep (threshold →
   recency weighting → **half-life** of that weighting when exponential is adopted
   (`half_life_grid`, fractions of the window floored at `min_samples/2`) → detrend,
   gated by a trend test → **stabilization** (`none`/`clamp`, adopted only on the
   same score-margin rule as `window_weights`/detrend) → window size → a **final
   threshold re-sweep** at the
   chosen window, since the optimal threshold depends on window size) maximizing
   the cross-validated score. The threshold grid carries high "near-suppress" rungs
   so a heavy-tailed metric can widen the band under the flag-rate budget instead
   of being trapped flagging its tail. Which axes apply is dispatched per
   detector type through the **`AxisSpec`** seam (`axis_spec.py`): the windowed
   types get exactly the axes above (behavior-identical), `autoreg` sweeps only
   threshold / **lags** (`TuneSettings.lags_grid`, min_samples floored at
   `lags + 2`) / stabilization / window and never receives
   `seasonality_components` (v1 rejects them); unlisted future types default to
   the windowed axes. The spec also drives the CV plan's context reservation
   (`max_context_size` — stabilization warm-up + lags, not just the raw max
   window, so folds never silently score unscorable points).
4. **Window selection** (`window_select.py`) — window grid in natural seasonal
   units, **plus a seasonality-fill candidate** (`seasonal_fill_window` =
   `min_samples_per_group × max_seasonal_cardinality`, capped to the fold budget)
   so CV can evaluate a window where a chosen grouping actually engages instead of
   silently falling back to global; if even the largest fold-feasible window can't
   fill the groups, `grid_search` logs a `window` advisory. The tie-break is
   **trend-gated** by `trend_present` (a midpoint-median
   test): stationary → prefer the **larger** window ("more history is better");
   trend / regime shift present → prefer the **smaller** (fresher baseline).
   Supervised runs also sweep the alert rule (`autotuner._select_alert_window`):
   the 1-D `consecutive_anomalies` loop first, then a 2-D (window × share)
   sweep of the **fraction rule OR-ed with the chosen consecutive rule** —
   scoring exactly the composite the pipeline deploys — adopted only on a
   strictly greater score (legacy rule wins ties, existing tunes byte-stable);
   an adopted pair emits `anomaly_window` as an exact-seconds duration
   (lossless grid-points round-trip) + `min_anomaly_share`.
   Because `trend_present` only compares the two halves' medians against the
   *global* MAD, it misses a level shift that sits off-center (both halves
   straddle it) or one big enough to inflate that MAD; `detect_level_shift`
   (`window_select.py`) backstops it — a NaN-aware scan of every split point
   against the *within-segment* scale, returning the **boundary index** — and when
   the series reads stationary yet a large (≥3σ within-regime) shift is present,
   the grid step logs a `regime` advisory (rendered as `REGIME` in the config
   header) naming a **concrete `--from <date>`** mapped from that index (recorded
   as `shift_at`). Advisory only: it changes no chosen parameters.
5. **Cross-validation + scoring** (`crossval.py`, `scoring.py`) — walk-forward
   expanding-window folds; because the windowed detector is causal, `detect()`
   runs **once** per candidate and each fold is scored by slicing the results (no
   leakage, no per-fold recompute). The fold scores aggregate as
   `mean − stability_lambda · downside_deviation` (`_aggregate`): a **downside-only**
   penalty (shortfalls below the mean, averaged over all folds — always ≤ the old
   `std`), so a regime-adaptive config that scores *better* on recent folds isn't
   punished for that upside spread. `stability_lambda` (default 0.5) is exposed via
   the `autotune:` block. Supervised metrics are pure numpy (MCC default, plus
   `f_beta`/`balanced_accuracy`/`roc_auc`/`pr_auc`/`event_f1`). `event_f1`
   (`scoring.event_f_beta`) is **segment-aware / point-adjusted**: contiguous
   True runs in `y_true` are incidents (RLE via `true_segments`) — ≥1 flagged
   point inside → 1 TP, none → 1 FN, flags outside any incident → pointwise
   FPs — aligning the engine's objective with the alert pipeline and the
   `dtk tune` cockpit's streak-span-overlap recall/FDR. Its fold slices stay
   **unmasked** (boolean-masking invalid points would splice distinct
   incidents together); segments the detector couldn't score anywhere are
   dropped from the truth (`scorable_event_truth`) rather than counted missed,
   and segments recompute fold-locally by slicing. The supervised alert-window
   sweep honors it too. With no labels
   the objective is `unsupervised_objective` = `0.4·budget + 0.3·sharpness +
   0.3·separation`: a smooth flag-rate **budget** (no flat cliff, one-sided so a
   clean metric isn't pushed to flag), **sharpness** (median band-relative
   distance of the *normal* points — directly rewards a **tight** interval, the
   term the old ratio-only objective lacked), and **separation** (flagged points
   clearly outside vs normal). All-suppress now scores only `w_budget`, so a tight
   band that isolates real extremes strictly beats doing nothing. No scipy/sklearn.

`config_emitter.py` builds `metrics/<name>__tuned_<id>.yml` (deterministic
`run_id`) with a `#`-comment header rendering the decision log, validated through
`MetricConfig` before write. An optional `MetricConfig.autotune` block
(`config/metric_config.py`) constrains the search; resolved into `TuneSettings`
by the command. `dtk autotune` takes the same pipeline lock as `dtk run` (so the
two are mutually exclusive and `dtk unlock` clears a stuck autotune lock).

## Manual tuning (`dtk tune`)

`detectkit/tuning/` is the **human-in-the-loop sibling of `dtk autotune`**,
invoked by `dtk tune --select <metric>` (`cli/commands/tune.py`). Where autotune
searches automatically and writes a *new* `__tuned_<id>.yml` (never touching the
original), `dtk tune` opens an interactive browser view of the metric's **real**
persisted series, lets the user turn the detector's knobs and watch the band
recompute live, then writes the chosen config **back into the metric YAML in
place**. The two are complementary optimization paths; both share the
validate-before-write discipline and operate on the already-loaded
`_dtk_datapoints`.

The interactive recompute reuses the **same** framework-free TypeScript detector
port (`website/src/scripts/demo/detector.ts`) + chart (`demo/chart.ts`), fed the
real series. (The website playground now runs this **whole** cockpit renderer on a
*synthetic* series instead — see "The website playground" below.) So
unlike the read-only `--report` (which replays *stored* detections),
`dtk tune` recomputes detections client-side as the user moves a slider, with no
DB round-trip. The renderer (`website/src/scripts/report/tune.ts`, the
composition root — its state-free helpers (types, protocol, DOM controls,
config-text, formatters, styles, the worker client, the quality metrics) live in
`website/src/scripts/report/tune/`) is bundled to the committed
`detectkit/tuning/assets/tune.js` by `website/scripts/gen-tune-bundle.mjs` and
ships in the wheel — regenerate it when the renderer TS changes; the detector
port is the parity-checked
(`npm run check:demo-parity`) shared core. `demo/chart.ts` exposes an **opt-in
`navigable` mode** (a `ChartOptions` flag off by default): when set,
the chart gains mouse-wheel zoom, drag-to-pan, double-click reset and a bottom
**navigator strip** (full series + current-view window + alert ticks + an adaptive
time axis). `dtk tune` (and the website playground, which now runs this cockpit)
turns it on so a dense metric can be zoomed region-by-region to inspect alert
quality; the chart's other rendering is unchanged when the flag is off. On top of the chart, `tune.ts` adds a
**"Points shown" trim slider** (re-slices the active series to the most-recent N
points and re-posts to the worker, so recompute — cost ∝ points × window — speeds
up; view-only, never written), a **legend**, per-control **ⓘ tooltips**, a
recompute **spinner**, and a **per-column seasonality group** selector that emits
the full `seasonality_components` `string[][]` (columns in one group are conjoined,
separate groups apply independent corrections). Beside it (only when the metric
has seasonality columns) a **`min_samples_per_group`** knob controls how many
same-key points the window must hold before a group earns its own band — seeded
from the config (honoring a non-default value, no longer pinned to the per-type
default), clamped to the active detector's floor (IQR 4), and reset to the type
default on a detector switch like the threshold knob. It exists because shrinking
**Points shown** / **Window size** can silently drop a group below the fill
threshold (`window_size < min_samples_per_group × distinct_keys`), so the band
falls back to global and widens for a reason that isn't the window itself; the
under-window warning (`updateSeasonWarn`) now names lowering this knob as the
alternative to widening the window. It is a manual lever only — `dtk autotune`
still holds `min_samples_per_group` at the class default and steers group-fill
through `window_size` / `seasonal_fill_window`. The detector picker also offers
**Manual** (`manual_bounds`): selecting it swaps the windowed knobs for **lower /
upper bound** sliders ranged over the real value domain (seeded from the metric's
bounds, else the data p5/p95), recomputed by the same parity-checked detector port
(`runManualBounds`, a stateless branch of `runDetector`). A **Direction** control
(`both / up / down`) is a worker-side *view filter* — it drops anomalies of the
other direction from the dots **and** the alert tally without touching the band —
seeded from the metric's alerting `direction` (multi-detector `same` → `any`). The
window-size and half-life sliders echo their wall-clock span next to the point
count.

**Warm-up honesty.** Each recompute posts both the clamped `eff`
(`effectiveStartIndex`, capped to the shown series length) and the un-clamped
`need` (`warmupRequirement` in `demo/detector.ts` — kept equal to the Python
`get_context_size`), so the HUD's warm-up stat reports the true context
requirement instead of one silently capped to the shown length. The band and
anomaly dots are drawn **wherever the detector actually scores** — `chart.ts`'s
corridor/center/dots start from the first scored point (`scoredRuns(scored, 0)`
+ the dot loop from `0`), not from `eff` — so the cockpit shows the same band the
pipeline persists and a Grafana view displays. The `eff` warm-up zone is only
**dimmed as a cold-start marker** (`drawWarmupOverlay`'s divider), never erased.
This fixes the reported autoreg confusion where a metric whose shown window was
shorter than `2·window+lags` rendered a **blank** chart even though the detector
had already scored hundreds of points (autoreg ignores seasonality, so the wide
warm-up — not the seasonal grouping — was the real cause). The inline
`warmupWarn` now fires **only** when the detector scored *nothing at all* in the
shown window (window below `min_samples`, too little shown history, or gaps
spanning the view), naming the concrete fixes (raise Window size / Points shown,
lower Lags/`min_samples`, turn Stabilization off); `drawFullWarmupOverlay` dims
the plot only in that truly-blank case (`runs.length === 0`). The Window-size
slider's explore cap is now a uniform half-of-shown for every detector type
(`windowReachFor(shown)`) — the old clamp-aware autoreg tightening is gone, since
the band no longer disappears when the warm-up exceeds the view.
`seed_detector_params` seeds `window_size` per type (`_WINDOW_SIZE_DEFAULT`,
autoreg 200) so a bare `type: autoreg` config opens at its real default, not the
windowed template's 100. `warmupRequirement` still mirrors
`get_context_size` on both branches (the windowed `+window_size` clamp term
included), so `need` stays an honest context figure — the TS/Python parity the
`check-tune-worker` test locks in.

**The cockpit — chart-windshield + a mode-aware control rail.** `tune.ts` drives a
**single** chart (the shared `demo/chart.ts` with `labeling:true` + a `mode`): the
old detector and labeler charts are merged onto one canvas that fills the screen as
the windshield. The live **metrics ride pinned in a HUD strip over the chart** (the
speedometer — always in view across every mode), and every control lives in an
**always-visible right-hand rail** (`.dtk-tune-rail`) with its own scroll, so you
turn a knob and watch the band change with no scrolling and no gaze-drop to a dock
below; a `ResizeObserver` on the chart box re-fits the canvas when the rail
collapses (the slim `.dtk-rail-open` tab brings it back). The rail is
**mode-partitioned** — `setUiMode(md: UiMode)` shows only the current mode's group
(`.dtk-rail-group`) and renames the rail header: the detector knobs + the
effective-config echo + **Apply** (the last two in the `.dtk-tune-railfoot`; the
echo is collapsed by default) in **Tune**, the verdict actions in **Review**, the
capture tools + incident list + **Save incidents** in **Label**, the **Run
autotune** button + winner/decision-log in **Autotune** (the `.dtk-tune-railfoot`
also rides in Autotune, so the searched config can be Applied in place) — never
every control at once. Two **always-visible common groups**
sandwich the per-mode group (never toggled by `setUiMode`): `topCommon` (the
**Points shown** data-window trim) above it and `alertCommon` (the alert rule —
**direction** + **consecutive anomalies** + the fraction pair **anomaly
window / min share** (off below 2 points ⇒ legacy consecutive-only; the worker's
`shareFireRuns` replays it with pipeline semantics — latest-point gate, missing
slots in the denominator only — and OR-merges the fires with the consecutive
rule's, deduped per fire point; Apply writes the pair into the first alerting
block or removes both, never a half-pair) — plus the **y = 0** view toggle) below
it, since those shape the band / the reviewed alerts / the recall+FDR in every
mode. The **mode switch** lives in the HUD. `UiMode = ChartMode | 'autotune'`: the
chart itself only knows the three **layer**-modes (`ChartMode = tune | review |
label`), so `setUiMode` maps `'autotune' → chart.setMode('tune')` (the Autotune
panel leads with the band, like Tune — it adds a rail panel, not a new chart layer
set). `chart.setMode` decides which visual LAYERS are full/dimmed/hidden and which
interactions are armed, generalizing the old ad-hoc `runs = labeling ? [] : …`
band-suppression into a per-layer table:

| layer | `tune` (+ `autotune`) | `review` | `label` |
|---|---|---|---|
| band fill + center | full | ghost (~0.3) | hidden |
| anomaly dots | full | dim | dim (lasso target) |
| alert markers | full | full (subject) | dim |
| incident spans | dim, read-only | dim, read-only | full, **editable** |
| capture tools (threshold/lasso) | — | — | armed |
| hover window | on | — | — |

Layers are dimmed by scaling base alpha (not removed), so the non-active job recedes
to locatable context instead of competing for pixels. A non-labeling chart (the
landing demo) has no `mode` and always renders the `tune` layer set — i.e. exactly
as before.

In **Label** mode you mark incidents (drag a span, edges/middle, ✕/Delete; lasso the
anomaly cloud; threshold-capture). In **Review** mode the alerts lead and you
**confirm each fired alert**: clicking its marker cycles the verdict un-reviewed →
valid → false (chart-side `hitAlert` + `onAlertReviewChange`; the chart is stateless
about reviews, reading the verdict from the marker's `kind` —
`anomaly`/`anomaly-validated`/`anomaly-false`, colored red/green/slate via the
`drawAlertMarkers` color closure). `tune.ts` stores verdicts by **streak span**
(`reviews[]`, re-bound to the moved alerts by overlap on each recompute) and rebuilds
the alert `kind`s. **Confirming an alert valid IS marking an incident** there: a valid
verdict is the user asserting a real incident happened in that span, so it is a
first-class **ground-truth incident** — `validatedSpans()` derives one per valid
review **from the stored verdict span** (NOT the current `lastFireSpans`, so a
confirmed incident stays scored even when the detector no longer fires there — then it
correctly registers as a recall *miss*). `validatedExtra()` drops any validated span
already covered by a hand-marked incident (overlap dedup); `groundTruth()` =
`incidents` ∪ `validatedExtra()` is what the **Marked-incidents list** and **Save**
read, so confirmed alerts appear in the list (a read-only "✓ confirmed alert" row
whose ✕ clears the verdict via `unconfirmAlert`) and are written as incidents on Save
(feeding the next supervised autotune) with no double-count after a Save→reopen.
**Deleting** a hand-marked incident (the chart's ✕ handle / **Delete** key, or the
list's ✕) **retracts any confirmed-valid verdict it overlapped** (`retractConfirmationFor`,
mirroring `unconfirmAlert`), so the incident is fully removed instead of the hidden
verdict **resurfacing** as its own "✓ confirmed alert" row — i.e. the chart-✕ and
list-✕ delete paths stay in lockstep and a deleted incident never appears to *turn
into* a confirmed alert (the chart threads the removed span to the cockpit via
`onIncidentsChange(incidents, removed)`). Explicit `false` verdicts and confirmed
alerts that don't overlap the deleted span are left alone. The
live metrics build the **same** union but **window-filter first** and dedup the
confirmed spans against only the in-window incidents (not the full set), so trimming a
hand-marked incident out of the active window can't silently drop an overlapping
in-window confirmed span from recall. A `false` verdict stays
a false alarm. A **Confirm all unreviewed valid** button does the lot; the metrics bar
gains a **reviewed N/M** chip; verdicts persist as an `alert_reviews:` metadata block
(`autotune/labels.py` parses it like `capture_windows`; autotune ignores it).

A prominent **metrics bar** recomputes as you tune from the worker's fired-alert
**streak spans** vs `groundTruth()` (marked incidents **+** confirmed-valid alerts,
overlap-deduped): **incident
catch rate (recall)** = incidents whose span **overlaps** an alert's anomaly streak /
total, and **false-alert rate (FDR)** = alerts whose streak overlaps no incident and
aren't confirmed valid / total (shown as `%` and "≈1 in N false", kept to one decimal
below 10 so a mostly-false rate doesn't round to a misleading "1 in 1"). An optional
**false-alert budget** — `false_alert_budget` resolved metric → project → built-in
`0.5` (`DEFAULT_FALSE_ALERT_BUDGET`), baked into the payload — gently marks the
false-alert chip (`▲ over N% budget`) when the FDR exceeds it; it is tuning-only
(labeling stays optional, the pipeline is untouched). Matching on
the whole streak span (not just the fire instant, which lands `consecutive-1` intervals
into the streak) is the recall-undercount fix: `tune.worker.ts` returns a `fireSpans`
array (the maximal grid-adjacent flagged run per fire) alongside `fires`, and
`computeQuality` overlaps those. Only incidents overlapping the **loaded (possibly
trimmed) series** are scored, so an out-of-window label can't mechanically drag recall
down. Two capture tools are armed only in **Label** mode (mutually exclusive, toggled
from the Label panel of the rail): **Threshold
capture** (behind `setThresholdMode` +
an `onThresholdChange` callback) grabs every contiguous run of points on the chosen
side of a horizontal line in one click — click/value sets the line, a horizontal
plot drag paints a capture window (else the current view), `applyThreshold` merges
the runs into incidents (each **padded half an interval each side** so a single
matching point becomes a full-interval incident the fired alert lands inside); the
painted window persists as `capture_windows` in the
saved labels and re-seeds via `setCaptureWindow` on reopen (pure metadata —
autotune ignores it). **Lasso anomalies** (behind `setLassoMode` + an
`onLassoChange` callback) draws a freeform loop and turns the enclosed **anomaly
dots** into incidents — each grid-adjacent run, bridging gaps up to
`consecutive_anomalies`, becomes one span padded half an interval each side (a lone
anomaly ⇒ one full-interval incident; a separate burst in the loop ⇒ its own
incident). **Save incidents** POSTs to the server's `/labels` endpoint,
which writes a versioned `incidents/<metric>/<…>.yml` — the **same store
`dtk autotune` reads**, so a labeling round here also feeds the next supervised
autotune; the command seeds the labeler (incidents **and** capture windows) from
the newest file in that directory on open, and `build_tune_payload` **anchors the
(still budget-sized) loaded window on the seeded incidents** — ending it just past
the *latest* incident rather than at the last datapoint — so they render and count
without a single old outlier incident dragging the whole history in (which would
blow the recompute budget and hang the page); incidents older than the bounded
window stay list-only and are excluded from the live metrics. The whole labels stack (schema, validation, versioned filenames) is shared
with `dtk autotune` via `autotune/labels.py` (`parse_incident_labels`,
`incidents_to_display`, `newest_labels_file`, `versioned_labels_path`), which is
also the store `dtk autotune` auto-discovers. A **y = 0
reference line** toggle (shared chart `showZeroLine` + `setZeroLine`, also on
`dtk run --report`) draws a horizontal line at zero and folds 0 into the scale, for
real-valued metrics best read relative to zero. All these chart additions default
off, so the landing playground is untouched.

Three pure-ish pieces + a server:

- `payload.build_tune_payload(...)` reads `_dtk_datapoints` and bakes the **raw
  gap-filled series + per-point seasonality keys + the metric's current detector
  config (camelCased to seed the controls, including any `manual_bounds` lower/upper)
  + the alert `consecutive_anomalies` and seeded `direction` + seeded `incidents`
  and `capture_windows`** (newest `incidents/<metric>/` file → display dicts) into a
  JSON payload — plus, for a **multi-detector** metric, the **full `detectors`
  list** (`{index, type, tunable, seed, summary}` per configured detector) and the
  **`detector_index`** the cockpit opens on. The cockpit opens on the first
  **windowed** detector (mad/zscore/iqr) — the one you tune against a band —
  falling back to the first tunable one, then MAD defaults when none is tunable
  (`_choose_seed_index`); the picker can switch to any other tunable detector, and
  the non-tunable ones (`prophet`/`timesfm`) ride along read-only so the write-back
  can preserve them. Everything the client port needs to *recompute*. With seeded
  incidents it **anchors the budget-sized window on the incident region** (ending
  just past the latest incident via `_incident_span`, clamped to the first
  datapoint) so they render and score while the load stays bounded. It bakes **no** precomputed
  detection (the browser runs the detector itself). The detector seed is built by
  `seed_detector_params(type, params)` — the **same** snake→camel mapping the
  server uses to re-seed the controls from an autotune result, so the two paths
  produce an identical control state. `labels_save_url` and `autotune_url` (like
  `save_url`) are injected by the server.
- `html.render_tune_html(payload)` inlines `assets/tune.js` + the payload into one
  self-contained HTML page (mirrors `reporting/html_report.py`; assigns
  `window.__DTK_TUNE__`).
- `config_writer.apply_tuned_config(...)` is the **single mutation seam**: it
  validates each tuned detector through `DetectorFactory.create` **and** the whole
  body through `MetricConfig` *before touching the filesystem* (raising — writing
  nothing — on a bad/untunable config), then **archives the previous YAML verbatim**
  under `metrics/.history/<metric>/<stamp>.yml` (comments preserved; the history of
  chosen params is trackable), and only then re-emits the metric in place via
  `yaml.safe_dump` (PyYAML only — same no-round-trip-dep choice as
  `config_emitter.py`; the prepended `#`-header names what was updated vs preserved
  and points at the archive). It takes a **list of `TunedDetector(type, params,
  index)`** and **merges**: each rewrites only **its own slot** in the `detectors:`
  list; every detector the cockpit didn't touch — a `manual_bounds` floor, a
  `prophet`/`timesfm` detector (not even tunable), another windowed detector — is
  preserved **verbatim** (out-of-range/None index → append, so a metric with no
  tunable slot gains one without dropping the rest). Execution-only params
  (`start_time` / `batch_size`) on an edited slot are carried over from the old
  config (the constructor rejects them, so they're stripped for validation but
  re-emitted). This is the fix for the earlier bug where the whole list was
  overwritten with the single tuned detector — silently dropping the others and, on
  a `min_detectors >= 2` alert, permanently killing it. It optionally updates the
  first alerting block's `consecutive_anomalies` (it never invents alerting).
- `server.serve_tuner(...)` / `build_tune_server(...)` is the localhost write-back
  server: bound to `127.0.0.1:0`
  with a one-shot `secrets` token, serves the page, and handles **three** token-guarded
  POSTs. `POST /apply` (the **Apply** click) posts a `detectors: [{index, type,
  params}, ...]` list — one entry per detector the user tuned (the auto-seeded one
  plus any edited via the picker; `_parse_tuned_detectors`, with a fallback to the
  legacy single `detector` object) — into `apply_tuned_config` → responds with the
  updated/preserved detector types + **self-shuts-down** so the command reports what
  changed; an invalid config returns **400 and keeps serving**. `POST /labels` (the **Save incidents** click) validates
  via `parse_incident_labels` and writes a versioned file through
  `versioned_labels_path` into `incidents/<metric>/`, then **keeps serving** (labels
  save repeatedly while you tune; only Apply ends the session); invalid labels return
  **400 and keep serving**. `POST /autotune` (the **Run autotune** click, the
  **Autotune** mode) reloads the metric's datapoints from the `internal_manager`
  handle **constrained to the window the cockpit is showing** — the page posts its
  current `{start, end}` ms window (the **Points shown** trim), and `_autotune_window`
  maps it to the half-open `load_datapoints` bounds (upper bound nudged one interval
  past the last shown point) so the engine tunes on **exactly the series the user
  sees and scores**, not the full history (an absent/malformed window falls back to
  full history). It projects the POSTed labels YAML (the page's current ground truth)
  onto the grid, runs the shared `autotune/runner.autotune_from_data(...)` over the
  metric's `autotune:` config, and replies with the winning detector (shaped via
  `seed_detector_params`) + `consecutive_anomalies` + score + decision log for the
  page to **re-seed** every knob; it **keeps serving** (repeatable, advisory) and
  persists nothing — any error returns **400 and keeps serving**. It also **streams a
  structured run-log to the terminal** through `server.echo` (the command's
  `click.echo`): a cyan banner then the engine's `LABELS → SEASONALITY → DETECTOR
  SELECT → GRID SEARCH → WINDOW → RESULT` blocks — the **same** `StageLogRenderer`
  (`cli/_output.py`) the `dtk autotune` command uses, so the cockpit's terminal log
  matches `dtk run`'s load/detect/alert format. The engine (`run_autotune_engine`)
  quiets the windowed detectors' per-candidate "seasonality falls back to global"
  warning for the duration of a tune (the grid builds dozens of throwaway candidates;
  the under-fill of the *chosen* seasonality is still surfaced as a structured
  `window` advisory), so the log stays clean instead of flooding. `/autotune` needs
  the `metric_config` + `internal_manager` handles `build_tune_server` now carries
  (the tune command passes them); omit them (static preview) and it returns 400.
  `dtk tune --no-serve` writes a static read-only preview
  file (sliders recompute, no write-back; **Save incidents** downloads the labels
  file instead; **Autotune** is unavailable — no live server).

Unlike `run`/`autotune`, `dtk tune` takes **no pipeline lock** — it neither runs
the pipeline nor persists detections, it only edits a config file (the **Autotune**
mode computes a config server-side but persists nothing — no run record,
`__tuned_<id>.yml` or detections — so the lock-free property holds; the user
**Apply**s the searched config like any other). Changing the
detector params changes the `detector_id`, so detections recompute under the new
id on the next `dtk run` (the live preview is the TS approximation; the next real
run is the source of truth).

### The website playground

The marketing site's interactive playground (`website/src/pages/playground.astro`)
is **not a separate demo** — it is a **literal instance of this cockpit renderer**
(`report/tune.ts`) fed a **synthetic** metric instead of a real `_dtk_datapoints`
series. This is the "the playground is a continuation of the real product"
contract, enforced structurally by shared imports rather than by convention: the
same chart, detector worker, four modes (Tune / Review / Label / Autotune), HUD,
mode-aware rail, live recall/FDR metrics and warm-up honesty the tool ships. The
only extra layer is a data-**generator** toolbar (rhythm / noise / trend / interval
/ incident / size) the real product doesn't need, plus a one-click autoreg
"shape-break showcase".

- `website/src/scripts/playground/payload.ts` — the one adapter: a synth `Series`
  (`demo/synth.ts`) → the exact `TunePayload` the cockpit consumes, with the three
  server hooks (`save_url` / `labels_save_url` / `autotune_url`) **nulled**. That is
  precisely the `dtk tune --no-serve` shape, so every backend action degrades to its
  offline form (Apply → a preview note, Save → a download, Autotune → a "needs the
  live server" note) with no code path of its own. It sits ABOVE `demo/` (like
  `report/`), so `demo/` stays the shared lower layer.
- `website/src/scripts/playground/main.ts` — the composition root: reads the
  generator toolbar, builds the payload, and (re)mounts the cockpit. Because the
  cockpit builds its state once at mount, a data change **re-mounts** `render()`
  (idempotent). Two **purely additive** extension points on `tune.ts` support this
  without changing product behavior (the shipped HTML calls `render(payload, mount)`
  with neither): an optional `hooks.onState` callback (so a regeneration carries the
  user's tuned knobs across the re-mount) and a returned `{ destroy, resize }` handle
  (`destroy` releases the worker + global listeners before each re-mount; `resize`
  repaints the canvas on a live theme toggle — the canvas reads brand tokens off
  `:root`, flipped per-theme by `landing.css`, so it re-themes for free).
- The detector Web Worker is bundled to a string and injected as `__DTK_WORKER_SRC__`
  by `astro.config.mjs` (`vite.define`) — the **same** define `gen-tune-bundle.mjs`
  uses for the shipped bundle — so `tune.ts` runs byte-for-byte unmodified on the
  site build.
- The cockpit ships **light-only** (its injected stylesheet hardcodes light tokens);
  the playground page retints `.dtk-tune` under `[data-theme='dark']` in its own
  CSS (zero impact on the shipped bundle) so it honors the site's light/dark/auto
  theme like everything else.

The "playground can't drift from the product" property is then made hard by the
`website` CI job (see the contributing rule): it runs the parity checks (the TS
port against the committed golden, tolerant 1e-6) + regenerates all committed
bundles and fails on any stale bundle (`git diff --exit-code`), converting what
were manual release-checklist steps into a code-enforced gate. (It does not
byte-diff `golden.json` — that regenerates locally via `gen-demo-golden.py`; the
parity check catches a golden that no longer matches the port.)

## Project UI (`dtk ui`)

`detectkit/ui/` is a **project-wide** cockpit over the same persisted `_dtk_*`
tables: one **overview** of every selected metric's alerting behavior (grouped
by `metrics/` subfolder, filterable by tag), a per-metric **detail** view (the
existing HTML report in an overlay, with a **Clean stale** action pruning
superseded detector generations), and a **pipeline panel** that drives
`dtk run` / `dtk autotune` / `dtk unlock` / `dtk clean` as subprocesses (plus
`dtk tune`, launched per metric in a new tab), plus **metric management** — creating,
editing and deleting metric YAML files from the browser, through a structured
**Builder** form or the raw **YAML** tab. Invoked by `dtk ui
[-s/--select "*"] [--window 30d] [--profile] [--no-open]`
(`cli/commands/ui.py`), which mirrors
`run_command`'s build order (find_project_root → `ProjectConfig.from_yaml_file`
→ `select_metrics` → `ProfilesConfig`/`create_manager` → `InternalTablesManager`
→ `ensure_tables()`) before handing off to `serve_ui(...)`. The package is five
small modules plus the bundle: `overview.py` (`build_overview_payload`),
`jobs.py` (`JobManager`), `server.py` (`build_ui_server`/`serve_ui`),
`metric_files.py` (the metric-YAML CRUD seam), `html.py`
(`render_ui_html`), and the committed `assets/ui.js`, built by
`website/scripts/gen-ui-bundle.mjs`.

**A superstructure, not a new execution path.** `server.py` is a
`ThreadingHTTPServer` mirroring `tuning/server.py`'s patterns (per-request
try/except → 400 and keep serving; a `Content-Length` guard on POSTs), with two
deliberate differences from `dtk tune`'s server: **every** route — GET and
POST — checks the `?token=` query param (tune only guards POSTs), and it
**never self-shuts-down** (`serve_forever(poll_interval=0.3)` until Ctrl-C;
`finally:` runs `jobs.shutdown()` + `server_close()`). A single
`threading.Lock` (`db_lock`) serializes every DB-touching route — the manager
holds one connection, the same reason `dtk tune` serializes `/autotune`. `dtk
ui` itself takes **no pipeline lock** and never runs the pipeline in-process.

Routes (all token-guarded): `GET /` (shell HTML), `GET /api/stats/<name>?window=`
(**one metric's overview row — the unit the page actually loads**),
`GET /api/overview?window=` (the same rows in one monolithic payload, kept for
programmatic use), `GET /metric/<name>?window=` (the detail overlay),
`GET /api/jobs` / `GET /api/job/<id>?offset=` (job listing + paged,
**absolute-offset** log lines — a job more verbose than the line cap keeps
streaming), `GET /api/clean-preview/<name>` (**read-only** — what `dtk clean
--select <name>` would delete: the CLI dry-run's diff of stored
`detector_id`s / `alert_config_id`s against the ids the current config
produces, as structured JSON for the confirm strip; derives **strictly**, so
an underivable config 400s instead of presenting everything as stale), and
`POST /api/run` / `/api/autotune` / `/api/unlock` / `/api/clean` (spawns the
real `dtk clean --select <metric> --execute`; per-metric, name validated
against the session like `/api/tune`; both `/api/clean` and the preview refuse
while a tuner for that metric is open — its Apply rewrites the YAML the
spawned clean re-reads — the same guard metric update/delete carry) /
`/api/tune` / `/api/job/<id>/stop` — plus the metric-management routes:
`GET /api/metrics` (the refreshed boot-shaped session list),
`GET /api/metric-source/<name>` (raw YAML text for the editor, plus the
parsed mapping `data` / `parse_error` that seed the Builder tab — a broken
file degrades to `data: null` + the message, so the editor opens YAML-only
with the Builder tab disabled), `POST /api/metric-parse` (validate draft text
→ parsed mapping; powers the Builder⇄YAML tab sync and the live-validation
chip — pure CPU, **no `db_lock`**, no filesystem), `POST /api/osi-inspect` /
`/api/osi-import` (the Builder's "From OSI" sub-tab: summarize a pasted OSI
model, then compile one metric via the **same** `import_osi_metric` path as
`dtk osi import`), and `POST /api/metric-create` / `/api/metric/<name>/update`
/ `/api/metric/<name>/delete`.

**Metric management is file-only and mirrors `dtk tune`'s write discipline.**
`metric_files.py` is the mutation seam: every mutation validates the **raw
YAML text** through `MetricConfig` **plus** a deep detector-params check
(constructing each factory-known detector, so a bad `window_size` fails at
save, not at the next run) *before touching the filesystem*; update/delete
first **archive the previous file verbatim** under
`metrics/.history/<metric>/` (`…-<stamp>.yml` / `…-<stamp>-deleted.yml` — the
same discovery-excluded archive `dtk tune`'s Apply writes). The editor is
**two tabs over one draft**: a **Builder** form (`metric-form.ts`) and the
raw **YAML** textarea (kept for experts who paste whole configs). The server
side stays text-in: whatever text the active tab holds is what gets posted
and validated; a YAML-tab save lands on disk verbatim, comments intact
(normalized only to end with a newline), while a Builder save posts a
**deterministic client-side re-emit** (`yaml-emit.ts`, a minimal
provably-round-trip-safe emitter — no YAML lib in the bundle) that **drops
hand-written comments** (the archive keeps the previous file; the editor
warns when the source has any). The Builder's invariant is
**modeled-fields-plus-verbatim-passthrough**: it renders the config's main
knobs as controls (basics — including `source_profile` as a second profile
picker, so a **hybrid** metric is creatable in the browser and a source-only
backend has a home in the form —, schedule/loading, seasonality, minimal detector
rows — type + 1–2 key params, fine-tuning deferred to `dtk tune` —,
alerting — the rule + channels + `suppress_until`, with `timezone`, `links`
(a `{label: url}` pair-row editor), `cooldown_reset_on_recovery`,
`min_detectors`, the fraction pair, mentions and `dashboard_url` under
Advanced —, `ai_context`; SQL in a hand-rolled syntax-highlighted pane,
`sql-editor.ts`; `query_file` shown read-only, never inlined) and carries
every unmodeled key (`autotune:`, `tables:`, `false_alert_budget`, the four
`template_*` message bodies — multi-line text that belongs in the YAML tab —,
unknown detector types/params, a >1-entry alerting list) through untouched,
surfaced in a "Preserved fields" list. Tab sync goes through the server-side parse seam
`metric_files.parse_metric_mapping` (validated config **plus** the raw
unwrapped mapping — only the keys the file sets, no pydantic defaults) via
`POST /api/metric-parse`: leaving an edited YAML tab must parse (blocked on
error), leaving an edited Builder re-emits; the same route backs the
debounced live-validation chip. While the YAML tab still holds the form's
own representation (nothing hand-typed since the views last agreed), the
chip and Save reuse the Builder's client-side issue list — the same friendly
"name is required" in both tabs instead of a raw pydantic 400 on the form's
own re-emit; genuinely hand-edited YAML gets the server verdict, collapsed
to one `field — reason` line (`summarizeParseError`, full text in the
tooltip). The Builder's channel/profile pickers are
seeded from the boot payload's `form_meta` (`build_form_meta(profiles_config)`
in `server.py` — channel **names + types and profile names only, never
channel configs/secrets**). After a create, a **next-steps strip** closes the
loop: **Load & detect** spawns `dtk run --steps load,detect` for just that
metric (deliberately no alert step, so an untuned config can't spam a
channel); when the job succeeds, **Open tune** unlocks and opens the tune
cockpit on the loaded series. Saves carry an optimistic-concurrency `digest`
(from `GET /api/metric-source`, `text_digest`): a stale editor — opened
before a `dtk tune` Apply or another tab's save — is refused instead of
silently clobbering the newer config. Name uniqueness is enforced
against the **whole** `metrics/` tree (not just the session's selector), a
created metric joins the session list even when it wouldn't match the boot
`--select`, delete requires the client to **echo the metric name**
(`{"confirm": <name>}` — the server-side half of the UI's confirmation
dialog), and Save/Delete are refused while a `dtk tune` job for that metric
is running (its Apply would race the edit). The CRUD handlers replace the
in-memory `srv.metrics` list under `db_lock` and reply with the refreshed
`metric_entries(...)` list so the page re-syncs in the same round trip.
Deleting or renaming never touches the database — orphaned `_dtk_*` rows
wait for `dtk clean`, and the archived YAML makes either reversible by hand.

**The overview loads incrementally and reads only the current config's
detector ids.** The page renders the table instantly from the boot metric
list, then fetches `GET /api/stats/<name>` per metric a few at a time (an
`n/N` progress chip while loading) — a monolithic all-metrics request on a
production-sized project takes minutes and gets aborted by the browser as
"Failed to fetch" while the page spins. Per metric, `overview.py` derives the
**currently-configured** detector ids exactly the way the detect step does
(`get_algorithm_params` + seasonality → `DetectorFactory.create_from_config` →
`get_detector_id`, `_configured_detector_ids`) and loads only those ids'
window rows: every retune/autotune leaves the superseded generation's rows in
`_dtk_detections` forever, so an unfiltered read returns one row-set per
historical config — N× the transfer volume *and* replayed quorums mixing live
and dead configs (inflating alert counts a real run would never produce). No
derivable ids (no detectors configured / factory rejects one) → unfiltered
fallback. This is a deliberate semantic difference from the report, which
shows *what actually ran* (every stored detector id in its window). The same
derivation (now the shared `DetectorFactory.detector_id_for_config`, also
behind `dtk clean`'s drift diff) feeds each row's **`stale_detectors`** count
(stored ids the current config no longer produces — an amber `N stale` chip
next to the metric name; `null` when underivable, never "all stale"), so the
leftover generations are visible before opening the detail. The detail
overlay's **Clean stale** button closes the loop: `GET /api/clean-preview`
counts → an inline confirm strip → `POST /api/clean` spawns the real
`dtk clean --select <metric> --execute` as a `clean` pipeline job → on
success the report iframe reloads (only current-config series remain) and the
row's stats re-fetch drops the chip.

**Pipeline actions are real subprocesses.** `jobs.py` (`JobManager`/`Job`)
spawns `[sys.executable, "-m", "detectkit.cli.main", "run", ...]` (and
`autotune`/`unlock`/`clean`/`tune`) — never an in-process call — pumping merged
stdout/stderr into a capped per-job line buffer a client pages through. Each
spawned command takes its **own** pipeline lock exactly as if typed into a
terminal; `dtk ui` adds no new locking or mutation path, only a UI over the
existing one. `--profile`, when given to `dtk ui`, is forwarded to every
spawned command. **Only one `run`/`autotune`/`unlock`/`clean` job runs at a
time** (`JobManager.pipeline_active()`, checked before spawning), since a live
pipeline lock and DB connection already make a second one fail loudly;
**`dtk tune` jobs are the deliberate exception** — several run concurrently
(one per metric being tuned), since each opens its own isolated, lock-free
tuning server. `POST /api/tune` blocks briefly
(`wait_for_line`/`tune_url_timeout`) for the spawned `dtk tune`'s
`Tuner: <url>` echo before replying with that URL for the client to open in a
new tab; a process that exits or times out first is killed and the request
fails with the captured output tail.

**The overview reuses the report's replay seam, not a new one.**
`overview.py` (`build_overview_payload`) computes alert counts the way
`reporting/builder.py` does: via the pure `AlertOrchestrator.replay(...)`, so
the numbers match what the pipeline would actually have alerted rather than a
separate approximation. The per-alert-config replay loop is factored out of
`build_report_payload` into a public `builder.replay_alert_events(...)` used
by both callers (alongside making `_record_from_row` public as
`record_from_row`) instead of being duplicated. Each metric's stats compute
**inside a per-metric try/except**, so one metric's failure (a bad
connection, a missing table) surfaces as an `error` field on that row
without breaking the rest of the payload. Quality (recall / false-alert
rate / reviewed) stays **labels-optional**: populated only when
`incidents/<metric>/` has a labels file (the same `autotune/labels.py`
helpers `dtk tune` uses), matched on alert-streak-span overlap exactly like
the `dtk tune` cockpit's metrics bar — a metric with no labels just omits the
field. Each row also carries the resolved `loading_delay_seconds` (metric →
project → 0); the frontend nets it out of `lag_seconds` before judging
freshness, so a metric with a deliberately configured `loading_delay` doesn't
read as perpetually stale. Window presets (`24h`/`7d`/`30d`/`90d`) map to `now - N days`; `all`
bounds each metric to its most recent `MAX_STAT_POINTS` (20,000) points so a
years-long, fine-grained metric can't melt the browser or the database.
`GET /metric/<name>` reuses `build_report_payload` / `render_report_html`
**verbatim** — the same functions `dtk run --report` calls — so the detail
overlay is the identical report, not a rebuilt one.

The frontend (`website/src/scripts/ui/ui.ts` → the committed
`detectkit/ui/assets/ui.js`, built by `website/scripts/gen-ui-bundle.mjs`) is
self-contained like `report.ts`/`tune.ts`: no ESM exports, assigns
`window.__DTK_UI__`, ships in the wheel, and must be regenerated when the
renderer TS changes — the same generated-asset discipline as
`report.js`/`tune.js`. `html.py` (`render_ui_html`) mirrors `tuning/html.py`:
it inlines the bundle plus a small boot payload (project name, initial
window, the metric list, `form_meta`) into one page — the overview/detail/job
data itself is fetched by the page over the routes above, not baked in
(unlike `dtk tune`'s payload, which bakes the whole series so the client can
recompute with no round trip).

## Semantic interop — OSI (`dtk osi`)

`detectkit/semantic/` is an **isolated, additive** layer for the
[Open Semantic Interchange](https://github.com/open-semantic-interchange/OSI)
(OSI) — a vendor-neutral YAML format for defining a metric once and consuming it
in BI + AI. **Nothing in load/detect/alert imports it**, so it can never affect a
running project; it powers only the `dtk osi` command group
(`cli/commands/osi.py`). The reframe driving the design: **OSI is an interchange
format, not an execution engine** (SQL is generated by MetricFlow/Cube/Snowflake),
so detectkit does *not* build a live OSI→SQL runtime — it converts at the edges.

- `osi_model.py` — **lenient** pydantic models of the verified OSI core
  (`semantic_model` → `datasets` (with `source`) / `relationships` / `metrics`;
  `ai_context`; `custom_extensions` = `[{vendor_name, data}]`, `data` a JSON
  string). `extra="ignore"` everywhere so an evolving draft spec can't break
  parsing. ClickHouse is **not** an OSI dialect (enum: ANSI_SQL/SNOWFLAKE/MDX/
  TABLEAU/DATABRICKS/MAQL); there is no grain field and no ratio metric *type*.
  `parse_osi_models(text, source=...)` is the **text seam** behind
  `load_osi_models(path)` (which just existence-checks + reads + delegates):
  the `dtk ui` Builder's "From OSI" paste box consumes it via the server's
  `/api/osi-inspect` / `/api/osi-import` handlers — imported **inside the
  handlers**, never at `ui/server.py` module level, so the
  pipeline-never-imports-OSI isolation property holds.
- `query_gen.py` — compiles an OSI metric to a detectkit series query satisfying
  the loader contract (`timestamp` + `value`, one value per bucket, Jinja
  `{{ dtk_start_time }}`/`{{ dtk_end_time }}` left for the loader). Two targets:
  `clickhouse` (`toStartOfInterval(...) GROUP BY` from `dataset.source`, ANSI→CH
  via the optional **sqlglot** dep) and `cube` (Cube SQL-API `MEASURE(...)` +
  `DATE_TRUNC`, so detectkit alerts on the same governed series a Cube dashboard
  shows). **Safety is an allowlist, not best-effort**: only provably
  per-bucket-additive shapes (`SUM`/`COUNT`/`COUNT(DISTINCT)`/`AVG`/`MIN`/`MAX` +
  ratios) compile; window functions / non-aggregates / unknown aggregates are
  **hard-refused** (`OsiUnsupportedMetric`) rather than emitting a wrong series.
- `importer.py` (`dtk osi import`) — the "enhanced init": resolves a metric and
  emits a **normal native MetricConfig** (validated before write), so there is no
  runtime OSI coupling and the output is reviewed/committed like hand-written SQL.
  A compiled-SQL `fingerprint` rides in the header so a re-import that changes the
  definition is a visible diff (detectkit resumes from the last datapoint).
- `exporter.py` (`dtk osi export`) — emits an OSI fragment with the metric's
  `ai_context` + the **exact** detect/alert config in
  `custom_extensions[vendor_name=detectkit].data` (a lossless snapshot — a
  **one-way carrier**: `dtk osi import` does not reconstruct from it, so the metric
  YAML stays source of truth). The portable `expression` is a placeholder (a
  detectkit series query doesn't decompose into a clean OSI measure).

sqlglot is the optional `[osi]` extra, imported lazily in `query_gen`; the core
library and the rest of the CLI never import it. Deferred (needs the user's Cube
pilot + a live-dependency decision): a *runtime* `osi_source` binding where
detectkit itself resolves OSI at load time. See `project_osi_detectkit_integration`.

## MCP server (`dtk mcp`)

`detectkit/mcp/` is a strictly **read-only** Model Context Protocol stdio
server over the project's `_dtk_*` state — an AI assistant connects and asks
"which metrics fired this week and why" against real pipeline data. Same
isolation contract as `semantic/`: the pipeline never imports it (guarded by
`tests/unit/test_mcp_isolation.py`, subprocess-probed so the check can't
pollute `sys.modules` for later tests), and the `mcp` SDK (extra `[mcp]`,
pinned `>=1.27,<2` — SDK v2 renames FastMCP to MCPServer) is a lazy import
raising a friendly install hint. Read-only is *enforced*: managers are built
with `create_manager(ensure_locations=False)` (skips every backend's
connect-time `CREATE DATABASE/SCHEMA`; DuckDB opens `read_only=True`, a
missing state file degrades to a friendly "run `dtk run` first" instead of
creating it), `ensure_tables()` is never called, and there are no
write/DDL/subprocess code paths. `McpContext` resolves the project via
`--project-dir` → `DETECTKIT_PROJECT_DIR` → cwd (MCP clients pass no cwd, so
relative DuckDB profile paths are absolutized against the project root), and
the startup `--select` is an access-control scope — tools refuse metric names
outside it. Tools reuse the existing read seams verbatim
(`build_metric_row`, `record_from_row`/`replay_alert_events`,
`load_datapoints`/`load_detections` with fetch-clamped windows,
`get_autotune_runs`, the labels readers); one long-lived connection behind a
`threading.Lock`, mirroring `dtk ui`'s `db_lock`.

## Idempotency & locking

Every stage **resumes from the last persisted timestamp**: load from
`max(timestamp)` in `_dtk_datapoints`, detect from `max(timestamp)` in
`_dtk_detections` for that `detector_id` — never reprocessing from scratch
(`get_last_timestamp` / `get_last_datapoint_timestamp` /
`get_last_detection_timestamp`).

A run takes a **pipeline lock** in `_dtk_tasks` (`acquire_lock` →
`release_lock`, `detectkit/database/internal_tables/_tasks.py`). The lock is
**self-healing**: a `running` row older than its `timeout_seconds` is treated as
stale and overridden, so a process killed mid-run (e.g. DB restart) never blocks
future runs. `--force` skips the held-lock check but still takes and releases the
lock (so it also clears a stuck row). `dtk unlock` clears a held lock on demand;
`dtk clean` prunes internal rows orphaned by deleted/renamed metric YAML.

**Metric discovery** (`config/validator.py:discover_metric_files`, the single seam
shared by `validate_project_metrics` and `select_metrics` / tag+name search)
recursively globs `metrics/**/*.{yml,yaml}` but **excludes any hidden path
component** under `metrics/` — chiefly the `metrics/.history/<metric>/` archive
`dtk tune` writes. Those snapshots keep the original `name:`, and since `pathlib`
glob traverses dotdirs (unlike shell globbing) they would otherwise be discovered
as live metrics and fail uniqueness validation with a spurious `Duplicate metric
name` error. Autotune's top-level `<metric>__tuned_<id>.yml` files are not hidden,
so they stay discoverable.

## Key design decisions

1. **Generic database manager** — `BaseDatabaseManager` exposes only universal
   `table_name`-keyed methods; no internal-table logic is hardcoded in it.
   `InternalTablesManager` layers the `_dtk_*` semantics on top.
2. **Custom `Interval` parser** — no pandas; accepts seconds (int) or strings
   like `"10min"`, `"1h"`, `"1d"`, `"30s"`.
3. **JSON seasonality storage** — seasonality components are stored as a single
   JSON column (`seasonality_data`) for schema flexibility.
4. **Dedup via PRIMARY KEY + INSERT IGNORE**, reinforced by `ReplacingMergeTree`
   on the append tables.
5. **Detector identity hashing** — id = `class_name + ALGORITHM_VERSION +
   sorted non-default params`; only `start_time` and `batch_size` are
   execution-level and excluded. Changing a hashed param recomputes detections
   under a new id.
6. **Time-aware recency weighting** — weights are looked up by a point's age on
   the time grid, so NaN gaps don't compress decay and seasonality groups share
   the global recency horizon. Expressed as `half_life` (points or duration
   string); `weight_decay` is a deprecated alias.
7. **`TableModel`-driven DDL** — schemas are declared as `TableModel` /
   `ColumnDefinition` dataclasses and rendered to backend-specific DDL by the
   manager.
8. **Detector-agnostic windowed template** — MAD/Z-Score/IQR share
   `WindowedStatDetector`; a new statistical detector implements only
   `_compute_stats` / `_build_interval` / `_severity` + class defaults. Keep it
   this way.

## Roadmap & known gaps

- **Vectorize `WindowedStatDetector.detect()`** — points are scored in a Python
  loop. Fine for incremental runs, slow for large historical backfills; numpy
  rolling-window operations are the main performance opportunity. (The same
  applies, more acutely, to `AutoregDetector`'s per-point refit.)
- **Advanced detectors** — Prophet and TimesFM integrations are planned (the
  optional extras are already reserved in `pyproject.toml`).
- **`benchmarks/`** (top-level, dev tooling, not in the wheel) — the
  NAB/Yahoo/synthetic harness (issue #99) scoring F1-best / AUC-PR /
  point-adjusted F1 per detector variant; also hosts the benchmark-local
  spectral-residual implementation kept under a measure-first gate (measured
  weaker than everything on synthetic AND NAB — a documented negative
  result). First full NAB numbers live in `benchmarks/README.md`.
- **DB connection pooling** — each manager holds a single connection; the SQL
  backends use per-statement `executemany`, fine for incremental runs but not
  optimized for very large backfills.
- **Parallel execution** — a `--threads` option to process metrics concurrently.
- **Further performance** — vectorized seasonality extraction, DB connection
  pooling, query-result caching.
