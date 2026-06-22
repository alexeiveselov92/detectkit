# Architecture

detectkit is a modular, database-agnostic library for monitoring metrics with
automatic anomaly detection. It is built around a three-stage pipeline —
**load → detect → alert** — driven by a dbt-like CLI (`dtk`) over YAML configs.
Core principles: **numpy-first** (no pandas in core logic; only in optional
helpers), **database-agnostic** (a generic manager interface with ClickHouse,
PostgreSQL and MySQL backends), **idempotent / resumable** (every stage resumes from the
last persisted timestamp), **modular** (small focused files, packages split into
mixins so nothing grows past ~250 lines), and **type-safe** (pydantic configs +
type hints throughout).

## The pipeline

`dtk run --select <selector>` loads the project, selects metrics, builds the DB
manager, ensures internal tables exist, then runs each metric through the
pipeline. `--steps load,detect,alert` (default: all three) restricts which
stages run. Each stage is idempotent and reads/writes the internal `_dtk_*`
tables described below.

- **load** (`detectkit/orchestration/task_manager/_load_step.py` →
  `detectkit/loaders/metric_loader.py`): renders the metric's SQL with Jinja2
  (`dtk_start_time`/`dtk_end_time`/`interval_seconds` injected), executes it,
  extracts seasonality features, **fills gaps** so the series is on a complete
  time grid (missing points become NaN/NULL), and writes `_dtk_datapoints`.
  Resumes from the last datapoint timestamp (or `loading_start_time` on first
  run); batches by `loading_batch_size`; snaps the end to the last complete
  interval boundary.
- **detect** (`detectkit/orchestration/task_manager/_detect_step.py`): for each
  configured detector, builds the detector, computes its `detector_id`, resumes
  after the last persisted detection, loads datapoints **plus a historical
  context window** (`get_context_size()`), runs `detect()`, strips the context
  from the persisted rows, and writes `_dtk_detections`. Batches by the
  detector's `batch_size`.
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
│   ├── commands/                # run, init, init_claude, test_alert, unlock, clean
│   └── assets/claude/           # context shipped by `dtk init-claude` (rules, skills)
├── config/                      # pydantic config models
│   ├── project_config.py        # ProjectConfig + paths/tables/timeouts/error_alerting
│   ├── profile.py               # ProfileConfig / ProfilesConfig (+ create_manager)
│   ├── metric_config.py         # MetricConfig, DetectorConfig, AlertConfig, QueryColumnsConfig
│   └── validator.py             # validate_metric_uniqueness / validate_project_metrics
├── core/
│   ├── interval.py              # Interval parser ("10min"/"1h"/"1d"/seconds)
│   └── models.py                # ColumnDefinition, TableModel (DB-agnostic DDL spec)
├── database/
│   ├── manager.py               # BaseDatabaseManager (generic, table_name-keyed interface)
│   ├── clickhouse_manager.py    # ClickHouseDatabaseManager
│   ├── _sql_manager.py          # SQLDatabaseManager (shared base for Postgres/MySQL)
│   ├── postgres_manager.py      # PostgresDatabaseManager (psycopg2)
│   ├── mysql_manager.py         # MySQLDatabaseManager (pymysql)
│   ├── tables.py                # TableModel factories for all _dtk_* tables
│   └── internal_tables/         # InternalTablesManager: per-table mixins over the manager
├── loaders/
│   ├── metric_loader.py         # SQL execution, gap filling, seasonality extraction
│   └── query_template.py        # Jinja2 SQL rendering (StrictUndefined)
├── detectors/
│   ├── base.py                  # BaseDetector, DetectionResult, detector_id hashing
│   ├── factory.py               # DetectorFactory registry
│   ├── seasonality.py           # seasonality mask + JSON parsing
│   └── statistical/
│       ├── _windowed.py         # WindowedStatDetector template (shared pipeline)
│       ├── mad.py / zscore.py / iqr.py   # thin subclasses (stats + interval + severity)
│       └── manual_bounds.py     # ManualBoundsDetector (stateless thresholds)
├── alerting/
│   ├── orchestrator/            # AlertOrchestrator: decision / cooldown / recovery / dispatch
│   └── channels/                # base + factory + mattermost/slack/telegram/email/webhook
├── orchestration/
│   ├── task_manager/            # TaskManager: run-level lock + _load/_detect/_alert steps
│   └── error_dispatch.py        # project-level error alert (shared by CLI + TaskManager)
├── autotune/                    # `dtk autotune` engine (separate from load/detect/alert)
│   ├── autotuner.py             # AutoTuner facade + run_autotune_engine + alert-window sweep
│   ├── labels.py / scoring.py / distribution.py / crossval.py   # ground truth, metrics, CV
│   ├── seasonality_search.py / detector_select.py / grid_search.py / window_select.py  # stages
│   └── result.py / config_emitter.py / html_labeler.py / settings.py / _types.py / _base.py
└── utils/                       # datetime, json (sorted/orjson), env interpolation, stats
```

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

Three backends implement this interface:

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
  `VARCHAR(255)` (TEXT can't be PK-indexed).

`ProfileConfig.create_manager()` (`detectkit/config/profile.py`) builds the right
backend from `type`; PostgreSQL additionally requires a `database` connect-target.

The `TableModel` carries a `version_column` (the last-writer-wins key encoded as
`ReplacingMergeTree(<col>)` on ClickHouse and driving the version-aware upsert on
SQL backends). The `InternalTablesManager` mixins are backend-neutral: they emit
no ClickHouse-only SQL, routing all deletes through `delete_rows` and dedup reads
through `final_modifier` (locked in by `tests/unit/test_internal_tables_agnostic.py`).

`detectkit/core/models.py` holds `TableModel` and `ColumnDefinition` — the
database-agnostic schema spec the manager turns into backend-specific DDL.

`InternalTablesManager` (`detectkit/database/internal_tables/`) is a high-level
façade over a `BaseDatabaseManager`, assembled from per-table mixins
(`_datapoints`, `_detections`, `_tasks`, `_metrics`, `_alert_states`, `_schema`,
`_maintenance`). It owns all `_dtk_*` knowledge; the base manager stays generic.

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

`detectkit/detectors/factory.py` (`DetectorFactory`) is the registry mapping
type names to classes: `mad`, `zscore`, `iqr`, `manual_bounds`, and the alias
`manual`.

## Alerting

The model is **alert-centric**: messages lead with the alert and the rule it
fired on; the anomaly is supporting evidence. The orchestrator
(`detectkit/alerting/orchestrator/`) is composed of mixins —
`_decision`, `_cooldown`, `_recovery`, `_dispatch`.

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

Other behaviors: **cooldown** (`_cooldown.py`) suppresses repeat alerts within
`alert_cooldown`, optionally reset on recovery; **recovery** (`_recovery.py`)
sends a direction-aware all-clear once per incident when `notify_on_recovery`;
**no-data** alerts fire when the latest expected datapoint is missing/NULL
(independent of quorum). State (last alert / recovery, counts) is keyed by
`alert_config_id` in `_dtk_alert_states`.

Channels live in `detectkit/alerting/channels/` behind `BaseAlertChannel`;
`AlertChannelFactory` builds them with env-var interpolation. Implemented:
`mattermost`, `slack`, `telegram`, `email`, `webhook`. Every channel defaults
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

**Default rendering is platform-native** (no custom `template`). The value
computation behind all of it is shared: `BaseAlertChannel.build_context` is the
single source feeding both custom templates and native rendering. Every alert
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

- **Slack / Mattermost / generic webhook** (all via `WebhookChannel`) render one
  message *attachment* — a status-colored accent bar, a clickable title (the
  metric, linking to `dashboard_url` when set), a short markdown lead (the
  duration sentence, see "Incident timing" below) with the **Rule** chip beneath
  it, and a compact fields grid: short fields Value / Expected / Quorum /
  Severity / Started / Latest (Started / Cleared on recovery), then full-width
  Detectors / Parameters, plus a branded footer + footer_icon. `@mentions` ride
  in the **top-level** message text so they notify on Slack. A custom `template`
  still renders as a plain text-only attachment (color/title/branding kept, no
  fields grid).
- **Telegram** defaults to `parse_mode: HTML` (was Markdown). The default
  message is structured and HTML-escaped: a colored status dot (red anomaly /
  green recovery / yellow no-data / blue error), a bold headline, the lead +
  rule, then evidence in `<code>` (value / expected / quorum / severity /
  started → latest / detector / params), an inline "Open dashboard" link, then
  mentions. This fixes a real bug — the old Markdown mode raised `can't parse
  entities` on params JSON containing underscores (e.g. `window_size`). Custom
  templates are sent verbatim under the parse mode (so keep them HTML-safe; set
  `parse_mode: Markdown` for the old behavior).
- **Email** sends a branded HTML card (inline-CSS, table-based, Outlook-safe) —
  colored accent + status pill, the metric, the lead + Rule chip, a 2-col stat
  grid (value / expected / severity / quorum / started / latest), a monospace
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
**true streak length** and the wall-clock **duration**; the Started/Latest
fields bound the span. Recovery is symmetric (`Incident lasted …`, Started /
Cleared). The decision only needs `consecutive_anomalies` points, so the *true*
streak/onset is resolved **only when an alert fires/clears**: `_decision.py`
(`_resolve_streak`) and `_recovery.py` (`_resolve_incident`) load up to
`STREAK_LOOKBACK_POINTS` (`_base.py`) detections and re-walk the same
direction-aware quorum logic; a run older than the window renders as `over …`.
The result rides on `AlertData.interval_seconds` / `onset_timestamp` /
`streak_capped` (`consecutive_count` now carries the *true* streak), and
`BaseAlertChannel.build_context` turns it into the shared `anomaly_lead` /
`recovery_lead` / `window_line` / `duration_display` values. The hot no-alert
path is untouched (no extra query).

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

## Auto-tuning (`dtk autotune`)

`detectkit/autotune/` is a **separate offline pipeline** from load/detect/alert,
invoked by `dtk autotune --select <metric>` (`cli/commands/autotune.py`). Given a
metric's already-loaded `_dtk_datapoints` (and optional labeled incidents), it
chooses the best detector configuration and emits an annotated tuned config; it
never edits the original metric and never alerts.

The engine is **pure and DB-free** — it operates on the in-memory `data` dict and
reuses `WindowedStatDetector`/`DetectorFactory`/`detector_id` unchanged. The
command loads data, threads it into `run_autotune_engine(...)`, then persists the
run, emits the config, persists the winner's detections, and prunes superseded
prior winners. Stages (`AutoTuner.tune()`), each appending to a decision log:

1. **Seasonality search** (`seasonality_search.py`) — greedy over the metric's
   seasonality columns (single-add or merge-into-last to form conjunctive
   groups), scored with a cheap MAD probe; rejects groupings that would
   under-fill a group.
2. **Detector selection** (`detector_select.py`) — a distribution suitability
   spec **keyed by detector type name** (kept here, NOT on the detector classes,
   so detectors stay untouched and the feature is easy to remove) votes per
   seasonality group; quorum + the global winner form the candidate shortlist.
3. **Grid search** (`grid_search.py`) — bounded coordinate sweep (threshold →
   recency weighting → detrend, gated by a trend test → window size) maximizing
   the cross-validated score.
4. **Window selection** (`window_select.py`) — window grid in natural seasonal
   units; on near-ties prefers the **larger** window ("more history is better").
   Supervised runs also sweep `consecutive_anomalies` for the alert window.
5. **Cross-validation + scoring** (`crossval.py`, `scoring.py`) — walk-forward
   expanding-window folds; because the windowed detector is causal, `detect()`
   runs **once** per candidate and each fold is scored by slicing the results (no
   leakage, no per-fold recompute). Metrics are pure numpy (MCC default, plus
   `f_beta`/`balanced_accuracy`/`roc_auc`/`pr_auc`); no labels → an unsupervised
   objective (low flag-rate + cross-fold stability). No scipy/sklearn dependency.

`config_emitter.py` builds `metrics/<name>__tuned_<id>.yml` (deterministic
`run_id`) with a `#`-comment header rendering the decision log, validated through
`MetricConfig` before write. An optional `MetricConfig.autotune` block
(`config/metric_config.py`) constrains the search; resolved into `TuneSettings`
by the command. `dtk autotune` takes the same pipeline lock as `dtk run` (so the
two are mutually exclusive and `dtk unlock` clears a stuck autotune lock).

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
  rolling-window operations are the main performance opportunity.
- **Advanced detectors** — Prophet and TimesFM integrations are planned (the
  optional extras are already reserved in `pyproject.toml`).
- **DB connection pooling** — each manager holds a single connection; the SQL
  backends use per-statement `executemany`, fine for incremental runs but not
  optimized for very large backfills.
- **Parallel execution** — a `--threads` option to process metrics concurrently.
- **Further performance** — vectorized seasonality extraction, DB connection
  pooling, query-result caching.
