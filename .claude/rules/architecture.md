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
│   ├── runner.py                # autotune_from_data: cap→scoring→ground-truth→settings→engine (CLI + dtk tune)
│   ├── labels.py / scoring.py / distribution.py / crossval.py   # ground truth, metrics, CV
│   ├── seasonality_search.py / detector_select.py / grid_search.py / window_select.py  # stages
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
│   ├── html.py                  # render_ui_html: inlines assets/ui.js + boot payload (mirrors tuning/html.py)
│   └── assets/ui.js             # committed bundle (generated by website/scripts/gen-ui-bundle.mjs)
├── semantic/                    # OSI (Open Semantic Interchange) interop — `dtk osi` (isolated; pipeline never imports it)
│   ├── osi_model.py             # lenient pydantic OSI models + custom_extensions / ai_context helpers
│   ├── query_gen.py             # OSI expr → ClickHouse/Cube series SQL (sqlglot; additive allowlist + hard-refuse)
│   ├── importer.py              # OSI metric → native MetricConfig scaffold (`dtk osi import`)
│   └── exporter.py              # MetricConfig → OSI fragment + custom_extensions[detectkit] (`dtk osi export`)
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

`detectkit/detectors/factory.py` (`DetectorFactory`) is the registry mapping
type names to classes: `mad`, `zscore`, `iqr`, `manual_bounds`, and the alias
`manual`.

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
  kept).
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
TypeScript core (`website/src/scripts/core/canvas.ts`) that powers the website's
interactive landing playground — so the report and the marketing demo render
identically. The bundle ships in the wheel
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
   gated by a trend test → window size → a **final threshold re-sweep** at the
   chosen window, since the optimal threshold depends on window size) maximizing
   the cross-validated score. The threshold grid carries high "near-suppress" rungs
   so a heavy-tailed metric can widen the band under the flag-rate budget instead
   of being trapped flagging its tail.
4. **Window selection** (`window_select.py`) — window grid in natural seasonal
   units, **plus a seasonality-fill candidate** (`seasonal_fill_window` =
   `min_samples_per_group × max_seasonal_cardinality`, capped to the fold budget)
   so CV can evaluate a window where a chosen grouping actually engages instead of
   silently falling back to global; if even the largest fold-feasible window can't
   fill the groups, `grid_search` logs a `window` advisory. The tie-break is
   **trend-gated** by `trend_present` (a midpoint-median
   test): stationary → prefer the **larger** window ("more history is better");
   trend / regime shift present → prefer the **smaller** (fresher baseline).
   Supervised runs also sweep `consecutive_anomalies` for the alert window.
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
   `f_beta`/`balanced_accuracy`/`roc_auc`/`pr_auc`). With no labels
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
port (`website/src/scripts/demo/detector.ts`) + chart (`demo/chart.ts`) that
power the landing playground — fed the real series instead of synthetic data. So
unlike the read-only `--report` (which replays *stored* detections),
`dtk tune` recomputes detections client-side as the user moves a slider, with no
DB round-trip. The renderer (`website/src/scripts/report/tune.ts`) is bundled to
the committed `detectkit/tuning/assets/tune.js` by
`website/scripts/gen-tune-bundle.mjs` and ships in the wheel — regenerate it when
the renderer TS changes; the detector port is the parity-checked
(`npm run check:demo-parity`) shared core. `demo/chart.ts` exposes an **opt-in
`navigable` mode** (a `ChartOptions` flag the playground leaves off): when set,
the chart gains mouse-wheel zoom, drag-to-pan, double-click reset and a bottom
**navigator strip** (full series + current-view window + alert ticks + an adaptive
time axis). `dtk tune` turns it on so a dense metric can be zoomed region-by-region
to inspect alert quality; the chart's other rendering is unchanged when the flag is
off, so the landing demo is untouched. On top of the chart, `tune.ts` adds a
**"Points shown" trim slider** (re-slices the active series to the most-recent N
points and re-posts to the worker, so recompute — cost ∝ points × window — speeds
up; view-only, never written), a **legend**, per-control **ⓘ tooltips**, a
recompute **spinner**, and a **per-column seasonality group** selector that emits
the full `seasonality_components` `string[][]` (columns in one group are conjoined,
separate groups apply independent corrections). The detector picker also offers
**Manual** (`manual_bounds`): selecting it swaps the windowed knobs for **lower /
upper bound** sliders ranged over the real value domain (seeded from the metric's
bounds, else the data p5/p95), recomputed by the same parity-checked detector port
(`runManualBounds`, a stateless branch of `runDetector`). A **Direction** control
(`both / up / down`) is a worker-side *view filter* — it drops anomalies of the
other direction from the dots **and** the alert tally without touching the band —
seeded from the metric's alerting `direction` (multi-detector `same` → `any`). The
window-size and half-life sliders echo their wall-clock span next to the point
count.

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
**direction** + **consecutive anomalies** — plus the **y = 0** view toggle) below
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

## Project UI (`dtk ui`)

`detectkit/ui/` is a **project-wide** cockpit over the same persisted `_dtk_*`
tables: one **overview** of every selected metric's alerting behavior (grouped
by `metrics/` subfolder, filterable by tag), a per-metric **detail** view (the
existing HTML report in an overlay), and a **pipeline panel** that drives
`dtk run` / `dtk autotune` / `dtk unlock` as subprocesses (plus `dtk tune`,
launched per metric in a new tab). Invoked by `dtk ui [-s/--select "*"]
[--window 30d] [--profile] [--no-open]` (`cli/commands/ui.py`), which mirrors
`run_command`'s build order (find_project_root → `ProjectConfig.from_yaml_file`
→ `select_metrics` → `ProfilesConfig`/`create_manager` → `InternalTablesManager`
→ `ensure_tables()`) before handing off to `serve_ui(...)`. The package is four
small modules plus the bundle: `overview.py` (`build_overview_payload`),
`jobs.py` (`JobManager`), `server.py` (`build_ui_server`/`serve_ui`), `html.py`
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
streaming), and `POST /api/run` / `/api/autotune` / `/api/unlock` /
`/api/tune` / `/api/job/<id>/stop`.

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
shows *what actually ran* (every stored detector id in its window).

**Pipeline actions are real subprocesses.** `jobs.py` (`JobManager`/`Job`)
spawns `[sys.executable, "-m", "detectkit.cli.main", "run", ...]` (and
`autotune`/`unlock`/`tune`) — never an in-process call — pumping merged
stdout/stderr into a capped per-job line buffer a client pages through. Each
spawned command takes its **own** pipeline lock exactly as if typed into a
terminal; `dtk ui` adds no new locking or mutation path, only a UI over the
existing one. `--profile`, when given to `dtk ui`, is forwarded to every
spawned command. **Only one `run`/`autotune`/`unlock` job runs at a time**
(`JobManager.pipeline_active()`, checked before spawning), since a live
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
field. Window presets (`24h`/`7d`/`30d`/`90d`) map to `now - N days`; `all`
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
window, the metric list) into one page — the overview/detail/job data itself
is fetched by the page over the routes above, not baked in (unlike
`dtk tune`'s payload, which bakes the whole series so the client can
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
  rolling-window operations are the main performance opportunity.
- **Advanced detectors** — Prophet and TimesFM integrations are planned (the
  optional extras are already reserved in `pyproject.toml`).
- **DB connection pooling** — each manager holds a single connection; the SQL
  backends use per-statement `executemany`, fine for incremental runs but not
  optimized for very large backfills.
- **Parallel execution** — a `--threads` option to process metrics concurrently.
- **Further performance** — vectorized seasonality extraction, DB connection
  pooling, query-result caching.
