# Changelog

All notable changes to detectkit will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.14.0] - 2026-06-20

### Added
- **`dtk-feedback` skill** shipped by `dtk init-claude`. When a `dtk` command
  fails or behaves unexpectedly, the user wants a feature, or has feedback, the
  assistant can file it as a GitHub issue on the upstream repo
  (`alexeiveselov92/detectkit`). The skill rules out local config problems
  first, auto-collects diagnostic context (detectkit/Python/OS versions, backend
  type, command + traceback, a minimal redacted repro), **strips every secret**,
  searches for duplicates, and **never submits without explicit confirmation** —
  using the `gh` CLI when available, or a prefilled "new issue" URL as a
  fallback. Filed issues carry a `via:assistant` attribution (a body marker, and
  the label when the maintainer has created it) so the assistant funnel can be
  triaged. Surfaced across the docs (the `CLAUDE.md` block,
  `docs/reference/cli.md`, the README feature list, the getting-started "Getting
  Help"/"AI Onboarding" sections, and the landing page).

## [0.13.1] - 2026-06-20

### Fixed
- Sync the `dtk init-claude` AI-context assets and the dev rules with the
  0.13.0 alerting redesign: document the colored **status circle** that leads
  every alert title (🔴 anomaly / 🟢 recovery / 🟡 no-data / 🔵 pipeline error),
  correct the stale "stop error" wording, cover `build_context` + native
  rendering in the add-a-channel guide, and surface `dashboard_url` in the
  metric example. Docs/assets only — no code or behavior change.

## [0.13.0] - 2026-06-20

### Added
- **Rich, platform-native alert rendering.** Every channel's default message is
  now laid out using that platform's own rich primitives instead of a flat text
  block — the alert still leads with the rule that fired, but the evidence reads
  cleanly at a glance.
  - **Slack / Mattermost / generic webhook** build a single message attachment
    with the status-colored accent bar, a clickable title, a short markdown
    lead, and a compact **fields grid** (Value / Expected / Quorum / Severity,
    then full-width Detected-at / Detectors / Parameters), branded with a
    `footer` + `footer_icon`. Mentions now ride in the **top-level** message
    text so they reliably notify on Slack. A custom `template` still renders as
    a plain text attachment (color/title/branding preserved).
  - **Telegram** now defaults to `parse_mode: HTML` and sends a structured,
    HTML-escaped message with a colored status dot, bold headline and `<code>`
    evidence. This **fixes** silent delivery failures: the legacy `Markdown`
    mode raised *"can't parse entities"* on detector params JSON containing
    underscores (e.g. `window_size`).
  - **Email** ships a fully branded **HTML card** (inline-CSS, table-based,
    Outlook-safe) — a colored accent + status pill, the metric, a 2-column
    value/expected/severity table, a monospace params box and a footer. The
    plain-text part remains the fallback.
- **First-class dashboard / runbook links.** New `dashboard_url` and `links`
  fields on a metric's `alerting:` config attach actionable links to every
  alert: a clickable attachment title on Slack/Mattermost, an inline link on
  Telegram, and an **Open dashboard** button in email. `{dashboard_url}` is also
  available to custom templates, and `{dashboard_line}` is appended to the
  default plain-text templates.

### Changed
- **Colored status circle leads every alert.** Titles and headlines now open
  with a status dot — 🔴 anomaly, 🟢 recovery, 🟡 no-data, 🔵 pipeline error —
  so the status reads at a glance from color alone (replaces the previous
  `⚠`/`✅` glyphs in the default titles, bodies and email subject).
- **Telegram default `parse_mode` is now `HTML`** (was `Markdown`). Custom
  Telegram templates are sent verbatim under the configured parse mode, so they
  should be HTML-safe; set `parse_mode: Markdown` on the channel to keep the old
  behavior.
- The shared message-context builder (`BaseAlertChannel.build_context`) is now
  the single source of the values used by both templates and native rendering,
  so chat, email and the website preview stay consistent.

## [0.12.0] - 2026-06-20

### Added
- **Branded alert bot identity by default.** Every alert channel now leads with
  the **detectkit brand** — display name and avatar — instead of the old
  `:warning:` emoji, so notifications are instantly recognizable. The defaults
  live in `detectkit/alerting/channels/branding.py` (`BRAND_USERNAME`,
  `BRAND_ICON_URL`) and remain fully overridable per channel.
  - **Slack / Mattermost / generic webhook** send the brand avatar as
    `icon_url` (a PNG served from the docs site at
    `https://dtk.pipelab.dev/bot-icon.png`). New `icon_url` parameter for a
    custom avatar image; `icon_emoji` still works to use an emoji instead. Icon
    precedence: `icon_url` wins over `icon_emoji`, and setting either opts out
    of the brand avatar.
  - **Email** sends as `detectkit <from_email>` (new `from_name` parameter,
    default `detectkit`) and now ships a multipart **HTML body with the brand
    logo** in the header — the plain-text body remains the fallback.
  - **Telegram** shows the bot account's own avatar (set in @BotFather, not
    per-message), so it can't be overridden by detectkit; the docs explain how
    to brand it with `/setuserpic`.
  - New brand asset `website/public/bot-icon.png`, generated from the logo
    geometry by `website/scripts/make-bot-icon.mjs`.

### Changed
- **Default webhook/Slack/Mattermost bot name is now `detectkit`** (was
  `detectk`) and the default icon is the brand avatar (was the `:warning:`
  emoji). Channels that explicitly set `username` / `icon_emoji` are
  unaffected. Sent webhook payloads now include `icon_url` (or `icon_emoji`
  when configured) rather than always sending `icon_emoji`.

## [0.11.0] - 2026-06-20

### Added
- **PostgreSQL and MySQL are now fully supported backends.** detectkit's
  database-agnostic architecture is realized end to end: ClickHouse, PostgreSQL
  (12+) and MySQL (8.0+) all run the complete `load → detect → alert` pipeline.
  Only the connection and the SQL dialect of your metric queries differ —
  detectors, alerting, the CLI and the project layout are identical.
  - `PostgresDatabaseManager` (`detectkit[postgres]`, psycopg2) — connects to a
    `database` and stores tables in **schemas** (`CREATE SCHEMA IF NOT EXISTS`).
  - `MySQLDatabaseManager` (`detectkit[mysql]`, pymysql) — uses **databases**
    (`CREATE DATABASE IF NOT EXISTS`); requires MySQL 8.0+.
  - Both share a new `SQLDatabaseManager` base that renders DDL with an enforced
    `PRIMARY KEY`, maps the abstract column types per dialect, and reproduces
    ClickHouse's `ReplacingMergeTree` last-writer-wins dedup with a **version-aware
    upsert** (`ON CONFLICT DO UPDATE` / `ON DUPLICATE KEY UPDATE`).
- **`dtk init --db-type {clickhouse,postgres,mysql}`** scaffolds `profiles.yml`
  and the example metric query for the chosen backend (default: `clickhouse`).
- **New `database` profile field** — the connect-target database, required for
  PostgreSQL (the database inside which the schemas live).
- **Per-database documentation** — a new **Databases** section in the docs
  (overview + ClickHouse / PostgreSQL / MySQL pages) covering install extras,
  `profiles.yml` shape, connection fields and SQL dialect per backend; plus a
  "Works with" database badge row on the landing page.

### Changed
- The shared `InternalTablesManager` layer is now genuinely backend-neutral: a
  generic `delete_rows()` primitive and a `final_modifier` dedup-read hook replace
  the ClickHouse-only `ALTER TABLE … DELETE` / `FINAL` / `count()` SQL that
  previously leaked through `execute_query`. `TableModel` gained an explicit
  `version_column`. ClickHouse behavior is unchanged.
- `ProfileConfig.create_manager()` no longer raises `NotImplementedError` for
  `postgres` / `mysql`.

## [0.10.0] - 2026-06-19

### Added
- **`dtk init-claude` — AI-native onboarding.** A new command that scaffolds
  [Claude Code](https://claude.com/claude-code) context into the folder holding
  your detectkit project(s), so an assistant can natively help you build and
  operate metrics, detectors and alerts. It writes:
  - `CLAUDE.md` — created if absent, otherwise a managed detectkit block is
    injected/refreshed between `<!-- BEGIN detectkit … -->` /
    `<!-- END detectkit -->` markers (your own content is preserved).
  - `.claude/rules/detectkit/` — reference docs the assistant reads on demand
    (`overview`, `cli`, `project`, `metrics`, `detectors`, `alerting`).
  - `.claude/skills/` — skills that scaffold work: `dtk-setup-project`
    (first-time DB/channel setup) and `dtk-new-metric` (a validated metric YAML).

  The content ships with the package and tracks the installed version, so
  **re-run `dtk init-claude` after upgrading** to refresh it. The operation is
  idempotent. The canonical source lives in `detectkit/cli/assets/claude/` and
  is kept in sync with the user docs on every release.
- **`dtk-setup-project` skill** (shipped by `dtk init-claude`): an interactive,
  database-type-aware setup that gathers your real connection details, points
  the profile at your database, optionally configures a first alert channel, and
  verifies with a non-destructive `--steps load` run. Surfaced at the top of the
  Quickstart and in the `dtk init-claude` reference.
- **Visualizing results guide** (`docs/guides/visualizing-results.md`):
  BI-tool-agnostic and database-agnostic SQL recipes for charting the `_dtk_*`
  tables (value + confidence band, anomaly markers, anomaly counts, latest-value
  stat, multi-detector comparison, severity breakdown) in Grafana, Superset,
  Metabase, Tableau, or plain SQL.
- **Developer docs** rendered on the site under a "For developers" section
  (architecture, contributing, design & brand), single-sourced from
  `.claude/rules/` so they double as in-repo AI-assistant context.

### Fixed
- **`dtk init` now scaffolds a runnable, schema-correct project.** The generated
  configs carried keys the loader silently ignores or the channels reject:
  - `profiles.yml` set `database:` on each profile — not a real field, so
    `internal_database` / `data_database` stayed unset and the first `dtk run`
    aborted with `internal_database must be set for ClickHouse`. The `dev`
    profile now sets both locations and is runnable against a local ClickHouse.
  - the `mattermost_alerts` channel set `icon_url`, which the Mattermost channel
    rejects (`Invalid parameters for mattermost channel`) the moment it is built
    (e.g. on `dtk test-alert`); replaced with the supported `icon_emoji`.
  - `detectkit_project.yml` used flat `metrics_path:` / `sql_path:` keys instead
    of the nested `paths:` mapping the model expects (silently dropped).
  - the commented generic-webhook example used `url` / `method` / `headers`
    instead of the real `webhook_url` / `extra_headers` (also corrected in the
    `dtk init-claude` project rules).

### Changed
- Example ClickHouse `host` in the shipped `dtk init-claude` rules/skill and in
  the profiles docs is now a neutral placeholder (`clickhouse.example.com`)
  instead of a sample IP address.

## [0.9.0] - 2026-06-19

### Changed
- **Alert messages are now alert-centric, not anomaly-centric.** The default
  notification leads with the **alert** and the parameters it fired with — the
  quorum/direction/consecutive rule — and shows the triggering anomaly as
  supporting evidence below. This reflects the library's model: the alert is
  the primary entity, and an anomaly is a secondary signal the rule interprets
  (a detector anomaly can mean very different things under different
  `min_detectors`/`direction`/`consecutive_anomalies` settings). The old
  `"Anomaly detected in metric: …"` body and `"Anomaly detected: …"` /
  `"Metric recovered: …"` titles become:
  - Anomaly: title `⚠ Alert: <metric>`; body shows
    `Quorum <actual>/<required> · direction <observed> (policy <configured>) ·
    consecutive <actual>/<required>`, a `Rule:` line restating the configured
    thresholds, then the latest point (time / value / expected range / severity)
    and the detectors + params as evidence.
  - Recovery: title `✅ Alert cleared: <metric>`; body states the alert
    condition no longer holds and echoes the same rule.
  Custom templates are unaffected — every previous template variable still works.

### Added
- **New alert template variables** that surface the rule the alert fired with:
  `{min_detectors}`, `{direction_policy}`, `{consecutive_required}` (the
  configured thresholds) and `{detector_count}` (observed detectors that
  agreed). Plus `{expected_range}`, a one-sided-aware expected band that renders
  one-sided detector bounds cleanly — `>= 7.00` for a lower-only
  `manual_bounds` instead of the confusing `[7.00, nan]`.
- `AlertData` now carries the alert-rule fields (`min_detectors`,
  `direction_policy`, `consecutive_required`, `detector_count`); the
  orchestrator fills them from the alert config's `AlertConditions`, and
  `dtk test-alert` previews them using the metric's own alert rule.

## [0.8.2] - 2026-06-15

### Changed
- **Unified CLI output style.** `dtk clean` and `dtk unlock` now render in the
  same tree layout (`┌─ / │ / └─`) as the `dtk run` pipeline steps, instead of
  each command's own ad-hoc formatting. Per-metric findings appear as child
  lines under a cyan metric header; metrics with nothing to do show a single
  `•` line; per-metric errors use `✗`; each run ends with a cyan-bold
  `Done. …` summary. Shared helpers live in `detectkit/cli/_output.py`.

## [0.8.1] - 2026-06-15

### Fixed
- **`--select "*"` (and other glob selectors) no longer crash on `.gitkeep` or
  non-YAML files.** The glob branch of metric selection passed raw `glob()`
  results — including the `.gitkeep` stub `dtk init` creates, stray files, and
  directories — straight to the YAML parser, so `dtk run/unlock/clean --select "*"`
  failed with `Empty metric config file: .../metrics/.gitkeep`. Glob results are
  now filtered to `.yml`/`.yaml` files. Additionally, `--select "*"` now resolves
  **recursively** so metrics in subdirectories are included (previously it
  expanded to a non-recursive `metrics/*` and silently skipped them).

## [0.8.0] - 2026-06-15

### Added
- **`dtk clean` command** — prune internal data that no longer matches the
  project's YAML configs, the rows left behind when metrics are edited on
  production. Two modes, both dry-run by default (`--execute` to apply):
  - `dtk clean --select <selector>` removes `_dtk_detections` rows whose
    `detector_id` is no longer produced by the config (a detector parameter or
    `seasonality_components` changed, or the detector was removed) and
    `_dtk_alert_states` rows whose `alert_config_id` is no longer produced (an
    alerting block's functional fields changed, or the block was removed).
    Valid hashes are recomputed with the same functions the pipeline uses, so
    pruning stays in lockstep with detection/alerting. Datapoints are not
    touched (they are keyed only by timestamp).
  - `dtk clean --orphaned-metrics` purges all rows, across every internal
    table, for metric names present in the database but no longer defined by
    any YAML in the project (a renamed or deleted metric). Asks for
    confirmation (skip with `--yes`) and refuses to run when the project
    defines no metrics or its configs fail to parse, so a wrong directory or a
    duplicate-name error can't wipe valid data.
- Internal-tables helpers backing the command: `list_detector_ids`,
  `list_alert_config_ids` / `delete_alert_state`, and a maintenance mixin
  (`list_known_metric_names`, `count_metric_rows`, `purge_metric`).
  `delete_detections` gained an opt-in `mutations_sync` parameter.
- New test suite `test_clean.py` (+23 tests).

### Documentation
- CLI reference gains a full `dtk clean` section; the configuration, detectors,
  and alerting guides note how config edits orphan data and link to the command.

## [0.7.0] - 2026-06-12

Major detector and alerting overhaul. Detector IDs change for many configs
(see Migration below) — affected detectors recompute detections on the next
run, which is safe and intended.

### Added
- **`half_life` parameter for recency weighting** (mad/zscore/iqr). With
  `window_weights: exponential`, a point's weight halves every `half_life`
  points — accepts an int (points) or a duration string (`"3d"`, `"12h"`,
  converted via the metric's grid step). Defaults to `window_size / 20`.
  Replaces `weight_decay` (still accepted, deprecated: decay `d` ≡
  half_life `ln(0.5)/ln(d)` points; the old default 0.95 ≈ 13.5 points was
  so aggressive that detectors adapted to real incidents within hours).
- **`detrend: linear` parameter** (mad/zscore/iqr). Estimates a robust
  linear trend over the window (split-median slope) and projects window
  points to the current point before computing statistics, so a gradually
  trending metric no longer drifts out of its own confidence interval while
  sharp deviations from the trend are still caught. In the reference
  trend-spam simulation (60-day window, daily seasonality, −15% gradual
  decline over 30 days): 1557 false "below" alerts → 26 with
  `half_life: "3d"`, → 19 combined with `detrend: linear`; a sharp −40%
  incident is still caught at every point.
- **Time-aware weighting.** Weights now depend on a point's age on the time
  grid, not its position among valid points: data gaps no longer compress
  the decay, and seasonality-group statistics share the same recency horizon
  as global statistics (the horizon mismatch was the main reason weighting
  "barely helped" trending metrics before).
- **`ess` metadata field** (Kish effective sample size) on weighted
  detections and **`trend_slope_per_point`** on detrended ones.
- New test suites: weighted statistics, shared windowed-detector behavior
  (weights, detrend, validation, hashing), multi-detector decision matrix,
  channel send contract (+89 tests).

### Changed
- **MAD threshold is now in σ-equivalents.** MAD is scaled by the
  normal-consistency constant 1.4826, so `threshold: 3.0` genuinely means
  ~3-sigma (≈0.27% false positives on Gaussian noise) like Z-Score. Raw
  3×MAD was only ≈2σ and fired on ~4.3% of perfectly normal points — the
  main source of baseline alert noise. MAD severity is in σ-equivalents too.
- **Multi-detector alert contract is now direction-aware and deterministic**
  (`min_detectors` × `direction` × `consecutive_anomalies`):
  - `up`/`down`: only anomalies in that direction count toward the quorum;
  - `any`: every anomaly counts regardless of direction;
  - `same`: at least `min_detectors` detectors must agree on ONE direction
    at the latest point (an up + a down detector is no longer "consensus");
    the winning direction locks for the whole consecutive chain.
  - Consecutive points must be exactly one interval apart — detection gaps
    no longer count as "consecutive".
  - The alert payload comes from the highest-severity quorum record (ties
    broken by detector name) instead of arbitrary SQL ordering.
- **Every result-affecting detector parameter now feeds the detector ID**
  (`seasonality_components`, `min_samples_per_group`, `smoothing_alpha`,
  `smoothing_window`, `window_weights`, `half_life`, `weight_decay`,
  `detrend`). Previously tuning e.g. `weight_decay` silently mixed old and
  new detection regimes under one ID.
- **Severity is now one convention for all windowed detectors**: distance
  beyond the violated bound in spread units (σ-equivalents for MAD and
  Z-Score, IQR units for IQR; 0 = at the bound). Z-Score previously
  reported the point's |z| (≥ threshold at the bound), which made
  cross-detector severities incomparable in multi-detector alerts.
- MAD/Z-Score/IQR collapsed into one shared `WindowedStatDetector`
  template (~1250 duplicated lines removed); behavior is identical across
  the three for windowing, preprocessing, weighting, detrending and
  seasonality.
- Detector parameters are fully validated at construction: bad
  `input_type`, `smoothing`, `window_weights`, `detrend`, `half_life`
  values fail fast with a clear error instead of mid-detection.
- `template_single` is now actually used (alerts with
  `consecutive_count ≤ 1`); `template_consecutive` covers streaks; each
  falls back to the other when unset.
- `AlertConditions` dataclass defaults (direct API) now match the YAML
  defaults: `direction="same"`, `consecutive_anomalies=3`.
- Internal version is unified: `pyproject.toml` reads
  `detectkit.__version__`; `dtk --version` reports the real version
  (was hardcoded `0.1.0` while `__init__` said `0.5.3` and pyproject
  `0.6.0`).

### Fixed
- **Telegram and Email channels could never deliver an alert** through the
  orchestrator: their `send()` signatures didn't accept the template
  argument, so every dispatch raised `TypeError` (and was swallowed as a
  failed channel). Both now follow the channel contract and return success.
- **Failed runs were recorded as `status='completed'`** with no error
  message in `_dtk_tasks`; they are now recorded as `failed` with the error.
- **Query-provided seasonality shifted onto wrong timestamps** whenever gap
  filling inserted rows mid-range (padding was appended at the end); it is
  now realigned by timestamp.
- **Seasonality grouping silently became a no-op** when seasonality data
  arrived as numpy unicode strings with orjson installed (`json_loads`
  rejected `numpy.str_`, the error was swallowed, and the group mask matched
  the whole window). Parsing now coerces string types.
- EMA smoothing no longer poisons the whole series when it starts with NaN.
- `get_context_size()` now includes the smoothing warm-up, so batched
  detection with smoothing is deterministic across batch boundaries.
- `weighted_percentile` uses the midpoint (Hazen) convention — with uniform
  weights the median now matches `np.median` exactly (the old interpolation
  was biased).
- `weighted_std(ddof=1)` no longer explodes when the effective sample size
  is ≤ 1.
- IQR seasonality multipliers can no longer produce an inverted interval.
- Two alert channels of the same type no longer collapse into one dispatch
  result entry.

### Migration
- Detector IDs change for ALL mad/zscore/iqr detectors: the shared
  implementation carries an algorithm-version tag (`@v2`: σ-equivalent MAD,
  Hazen-midpoint weighted percentiles, unified severity), and additionally
  any non-default `seasonality_components`, `min_samples_per_group`,
  smoothing or weighting parameters now feed the hash. Affected detectors
  recompute from scratch on the next run (rows under old IDs remain;
  `--full-refresh` purges them).
- MAD users: intervals widen ×1.4826 by design. If you raised `threshold`
  to fight noise, try lowering it back toward 3.0.
- `direction: same` with `min_detectors ≥ 2` now requires true directional
  consensus and may alert less than the old (buggy) behavior.
- Persisting anomalies still re-alert on every run unless `alert_cooldown`
  is set — recommended for production metrics (e.g. `alert_cooldown: "2h"`).

## [0.6.0] - 2026-05-26

### Fixed
- **Stuck pipeline locks now self-heal; `--force` clears them.** If a run was
  killed without releasing its lock — most commonly when **the database
  restarted mid-run** — the `running` row in `_dtk_tasks` was left behind, and
  *every* subsequent non-`--force` run failed with `RuntimeError: Failed to
  acquire lock ... Another task is running`. With `error_alerting` enabled this
  produced a continuous stream of error alerts. Two gaps caused it, both now
  closed:
  - `acquire_lock` ignored `timeout_seconds` (the staleness check was an
    unimplemented TODO). Now a `running` row older than its stored
    `timeout_seconds` (default 1 hour for the pipeline lock) is treated as
    stale and overridden, so the next normal run recovers automatically —
    matching the `can_start_process` logic in TECHNICAL_SPEC.md §13.1.
  - `--force` *bypassed* the lock but never *cleared* it: it skipped both
    acquire and release, so a forced run left the stale row in place and the
    spam continued. `--force` now takes ownership of the lock and releases it
    on exit, so a forced run also heals a previously stuck lock.

### Added
- **`dtk unlock --select <selector>` command.** Clears a stuck pipeline lock
  immediately instead of waiting for the timeout to expire. Reports per metric
  whether a lock was cleared, accepts the same selectors as `dtk run` (name,
  path, `tag:`), and marks the task `completed` so the next scheduled run
  proceeds without `--force`. Does not run the pipeline.

## [0.5.3] - 2026-05-12

### Added
- **Project name in error alerts.** When multiple detectkit projects
  route `error_alerting` to the same Slack/Mattermost channel, the
  generic `Pipeline error: <startup>` title made it impossible to tell
  which project crashed (especially if both bots happened to share a
  username). `AlertData` now carries `project_name`, automatically
  populated from `detectkit_project.yml`'s `name` field by
  `dispatch_project_error_alert`. The default error title becomes
  `[project_name] Pipeline error: <metric>` when the project name is
  known; collapses to the previous form when it isn't. New template
  variables `{project_name}` and `{project_name_prefix}` are available
  in custom `error_alerting.template` values (and in every other alert
  template — just empty for callers that don't set it yet).

## [0.5.2] - 2026-05-10

### Fixed
- **`dtk test-alert` no longer crashes with `AttributeError`.** The
  command had been broken since v0.3.9 (when `alerting` became a list):
  `create_mock_alert_data` still dereferenced
  `metric_config.alerting.mentions` and raised
  `AttributeError: 'list' object has no attribute 'mentions'` on every
  invocation. Now it sources mentions from the specific
  `AlertingConfig` under test — more correct anyway since different
  alert routes can ping different teams.

## [0.5.1] - 2026-05-10

### Fixed
- **Project `error_alerting` now fires for startup failures.** In v0.5.0
  the dispatch lived inside `TaskManager.run_metric`, but three classes
  of failures crash earlier — at the CLI level, before a TaskManager
  exists: `ProfilesConfig.from_yaml`, `profiles_config.create_manager`
  (the user-reported "Connection reset by peer" case), and
  `internal_manager.ensure_tables`. The DB outage that the feature was
  designed for is exactly the case that crashed in
  `create_manager` → no alert went out.
  Extracted the dispatch into `detectkit.orchestration.error_dispatch.
  dispatch_project_error_alert` and call it from both the CLI early
  paths (with `metric_name="<startup>"`) and from `TaskManager`. The
  helper takes `profiles_config + project_config` directly so it does
  not need a TaskManager instance to run.

## [0.5.0] - 2026-05-10

### Added
- **`no_data_alert` now actually fires.** The flag had been defined and
  persisted but was never read by the orchestrator, so missing-data
  alerts silently never went out. New `should_alert_no_data()` checks
  the latest expected interval in `_dtk_datapoints` (no row OR row with
  NULL/NaN value → "missing") and dispatches a dedicated alert through
  the same channels, honouring the existing `alert_cooldown` /
  `suppress_until` machinery. New `template_no_data` field on
  `AlertingConfig` for the message body.
- **Project-level `error_alerting`.** New optional section in
  `detectkit_project.yml` that catches any pipeline exception (DB
  outage, query timeout, lock failure, channel HTTP, etc.) and ships
  one alert through the named channels. After the alert fires the run
  aborts (`result["abort_run"] = True`) so a dead source doesn't cause
  N alerts for N metrics. No persistent cooldown — storing state in
  the DB doesn't help when the DB itself is down, and a local file
  would break the dbt-style stateless model. Custom `template`,
  `mentions`, and `timezone` supported.
- `AlertData` gains `is_no_data`, `is_error`, `error_type`,
  `error_message`. `format_message` handles three new statuses
  (`NO_DATA`, `ERROR`, plus the existing `RECOVERED` / `ANOMALY`),
  exposes `{value_display}` as a NaN-safe template variable, and
  falls back to a kind-appropriate default if a user template uses
  `{value:.2f}` on a no-data / error payload. `WebhookChannel` adds
  amber `#F0AD4E` for no-data and keeps red for error (visual parity
  with existing anomaly cards).

### Fixed
- `[dev]` extras pinned `pytest-requests-mock>=0.1`, which does not
  exist on PyPI. Every CI Test job aborted in 10s with "No matching
  distribution found" before pytest could even start. Replaced with
  `pytest-mock`.
- `AlertData.value` is now `Optional[float]` (was `float`). Required
  by the no-data / error paths where there is no real value; unchanged
  semantics for existing anomaly / recovery callers.

### Internal
- Whole codebase brought up to ruff + black compliance (autofixed
  pyupgrade rules, `raise ... from e`, `zip(strict=True)`, formatting).
  No behaviour changes; 385 unit tests still pass. CI's lint job is
  now actually a gate rather than a permanent red tile.
- `[tool.ruff]` migrated to `[tool.ruff.lint]` to silence the
  deprecation warning.

## [0.4.1] - 2026-04-27

### Fixed
- **`min_detectors >= 2` never fired**: `_load_recent_detections` collapsed
  every detector at a given timestamp into a single `DetectionRecord`, so
  `should_alert` saw at most one record per timestamp regardless of how
  many detectors actually flagged the point. Channels configured with
  `min_detectors: 2` therefore went silent even when both detectors agreed
  on a "down" anomaly, while a parallel `min_detectors: 1` channel fired
  normally. Now one record is emitted per detector per timestamp, matching
  the contract that the orchestrator and recovery code already expect.

## [0.4.0] - 2026-04-19

### Breaking
- `DetectionResult` field order changed. The dataclass is now declared as
  `timestamp, value, is_anomaly, processed_value=None, confidence_lower=None,
  confidence_upper=None, detection_metadata=None`. Custom detectors that
  construct `DetectionResult` with **keyword arguments** (the way every
  built-in detector does) are unaffected. Detectors that relied on the
  previous **positional** order (`DetectionResult(ts, val, processed_val,
  True, ...)`) must switch to keyword arguments or reorder.

### Security
- **SQL injection hardening**: every `_dtk_*` query now uses parameterised
  placeholders. Previously `metric_name`, `detector_id` and timestamp filters
  were interpolated via f-strings into `WHERE` and `ALTER TABLE … DELETE`
  clauses; a crafted `metric_name` could execute arbitrary SQL. Affected
  methods: `load_datapoints`, `delete_datapoints`, `delete_detections`,
  `get_recent_detections` (all in `internal_tables`).
- **Secrets in `profiles.yml`**: `${VAR}` and `{{ env_var('VAR') }}` placeholders
  are now interpolated when the profile is loaded
  (`ProfilesConfig.from_yaml`). Database passwords no longer have to live
  in plaintext alongside the YAML.

### Added
- `detectkit.utils.env_interpolation.interpolate_env_vars` — recursive helper
  used by both the profile loader and the alert-channel factory.
- `detectkit.utils.json_utils` — single source of truth for JSON helpers
  (replaces three local copies of `json_dumps_sorted`).
- `detectkit.detectors.seasonality` — shared `parse_seasonality_data` /
  `create_seasonality_mask` (replaces ~240 lines of duplication across MAD,
  Z-Score and IQR).
- GitHub Actions workflows: `ci.yml` (pytest / mypy / ruff / black on
  Python 3.10–3.12) and `publish.yml` (PyPI trusted publishing on tags).
- `.pre-commit-config.yaml` with ruff/black/mypy/yaml/whitespace hooks.
- Integration test scaffold under `tests/integration/` using
  `testcontainers[clickhouse]`. Marked with `@pytest.mark.integration` and
  skipped in environments without Docker. Install via
  `pip install -e ".[integration]"`.

### Changed
- `internal_tables.py` (1066 lines) became the `internal_tables/` package
  with one mixin per logical table (`_datapoints`, `_detections`, `_tasks`,
  `_metrics`, `_alert_states`, `_schema`). Public API
  (`from detectkit.database.internal_tables import InternalTablesManager`)
  unchanged.
- `task_manager.py` (875 lines) became the `task_manager/` package
  (`_load_step`, `_detect_step`, `_alert_step`, `_base`, `_types`,
  `manager`). Public exports preserved.
- `alerting/orchestrator.py` (777 lines) became the `alerting/orchestrator/`
  package (`_decision`, `_cooldown`, `_recovery`, `_dispatch`, `_types`).
- `_compute_sma` in `detectors/base.py` rewritten using cumulative sums; the
  previous nested Python loop is gone.
- `DetectionResult.processed_value` is now optional and defaults to `value`
  when not supplied — convenient for detectors that don't pre-process data.
- Pipeline failures now print the exception type and a traceback to stderr
  instead of just the message string.
- ClickHouse "epoch-as-NULL" handling consolidated into a single
  `_normalize_max_timestamp` helper used by every `MAX(timestamp)` query.

### Fixed
- `pytest.ini` and `pyproject.toml` no longer fight over pytest configuration:
  the `pytest.ini` file was removed and `--cov=detectkit` (was
  `--cov=detectkitit`) is the single source of truth.
- `[tool.setuptools]` `packages = ["detectkit"]` only shipped the top-level
  package; switched to `setuptools.packages.find` so detector / alerting /
  CLI submodules end up in the wheel.
- Stale unit tests that still expected the pre-`processed_value` schema and
  the wrong `_dtk_detections` column order have been refreshed.

### Removed
- Public-repo `.gitignore` no longer hides `TECHNICAL_SPEC.md`,
  `ARCHITECTURE.md`, `TODO.md`, `PROGRESS.md`, `init_plan.md`,
  `GRAFANA_DASHBOARD.md`. `CLAUDE.md` and `.claude/` remain ignored.

### Migration notes (0.3.x → next)
- If you patched `detectkit.orchestration.task_manager.MetricLoader` in tests,
  update the dotted path to
  `detectkit.orchestration.task_manager._load_step.MetricLoader` (or import
  `MetricLoader` directly from `detectkit.loaders.metric_loader`).
- If you imported the private helpers `_parse_detection_metadata` /
  `_direction_from_metadata` from `detectkit.alerting.orchestrator` —
  they're still re-exported from the same path, no change needed.
- To use env-var interpolation for DB credentials, set the variable in your
  shell and reference it as `password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"`
  in `profiles.yml`. Previously this only worked for alerting channels.

## [0.3.17] - 2026-04-11

### Fixed
- **Recovery alert CI display**: recovery messages now show the confidence interval from the
  *current* detection point (matching the displayed value's seasonality group), not the stale
  CI from the last anomalous point. Previously, with hourly seasonality, recovery could show
  a CI from a different hour, making the value appear outside bounds when it was actually normal.

## [0.3.16] - 2026-04-10

### Added
- **`suppress_until`** field in alerting config — temporarily suppress alerts until a specified
  UTC datetime without disabling the metric. Load and detect steps continue running; alerts
  auto-resume after the specified time. One-time setup, no need to toggle `enabled` twice.

### Fixed
- **Timezone display in alerts**: timestamps are now converted from UTC to the configured
  `timezone` (e.g., `Europe/Moscow`) before formatting. Previously, UTC time was displayed
  with the timezone label appended, showing incorrect local time.
- **Recovery alert metadata**: recovery messages now show the detector name and confidence
  interval from the last anomalous detection instead of "Detector: unknown" and "CI: N/A".

## [0.3.14] - 2026-04-09

### Fixed
- **Direction-aware recovery**: recovery for `direction="up"` / `"down"` / `"same"` alerts no
  longer waits for the metric to return inside the confidence interval. A `down`-only alert
  now recovers as soon as the latest point is no longer a `down` anomaly (including when it
  flips to an `up` anomaly), matching the semantics of `_count_consecutive_anomalies()`.
- **ManualBoundsDetector recovery / alerting**: anomaly direction is now read from
  `detection_metadata.direction` (authoritative `"below"`/`"above"` written by every detector)
  instead of being reconstructed from `value` vs `confidence_lower/upper`. One-sided manual
  bounds (e.g. only `upper_bound` set, `confidence_lower=None`) no longer break direction
  resolution in `AlertOrchestrator._check_recovery_since_last_alert()` and
  `TaskManager._load_recent_detections()`.

### Changed
- `InternalTablesManager.get_recent_detections()` now selects `detection_metadata` and exposes
  it as `detection_metadata_list` in the grouped result.
- New `AlertOrchestrator._get_alert_trigger_direction()` helper resolves the direction of the
  alert-triggering point for `direction="same"` recovery checks.

## [0.3.13] - 2026-04-08

### Added
- New internal table `_dtk_alert_states` for independent alert state per alerting config block
  (`last_alert_sent`, `last_recovery_sent`, `alert_count` keyed by `metric_name` + `alert_config_id`)
- `alert_config_id` generated as MD5 hash of all config params (channels, min_detectors, direction,
  consecutive_anomalies, alert_cooldown, cooldown_reset_on_recovery) — configs with the same channels
  but different conditions correctly get different IDs and independent state

### Fixed
- **Multi-config alerting**: when a metric has multiple `alerting:` blocks, each now tracks its own
  alert/recovery state independently — fixes false recoveries caused by shared `last_alert_sent`
- **Recovery threshold**: recovery now requires 0 detectors flagging the latest point as anomalous
  (previously used `< min_detectors`, causing false recovery when some detectors still saw anomaly)
- **Recovery message point**: `_build_recovery_data()` now correctly uses the newest detection point
  (`detections[-1]`) instead of the oldest (`detections[0]`)

### Changed
- `get_last_alert_timestamp`, `update_alert_timestamp`, `get_last_recovery_timestamp`,
  `update_recovery_timestamp` now require `alert_config_id` parameter
- `upsert_task_status` simplified — alert state no longer stored in `_dtk_tasks`
- `AlertOrchestrator.__init__` requires `alert_config_id` parameter

### Migration
New table is created automatically on next `dtk run` via `ensure_tables()`.
Existing alert state in `_dtk_tasks` is not migrated — first run after upgrade starts with clean state.

## [0.3.12] - 2026-04-08

### Fixed
- Custom `template_consecutive` from alerting config now correctly passed to `send_alerts()`
- Numpy timezone warning in `upsert_task_status`: strip tzinfo from datetime fields before
  converting to `datetime64[ms]`

### Changed
- Centralized UTC datetime handling into `detectkit/utils/datetime_utils.py`
  (`now_utc`, `now_utc_naive`, `to_naive_utc`, `to_aware_utc`)

## [0.3.11] - 2026-04-08

### Fixed
- Recovery notifications never fired: `upsert_task_status` was destroying `last_alert_sent` /
  `last_recovery_sent` on every DELETE+INSERT cycle (fields were reset to NULL)
- Alert mutations now use `mutations_sync=1` to prevent race conditions between alert step
  and lock release

## [0.3.10] - 2026-04-08

### Fixed
- False recovery detection: check latest point's anomaly status instead of counting consecutive anomalies
- Alert step now always runs (recovery notifications need it even when no new anomalies detected)
- `min_detectors` now correctly read from alerting config instead of being hardcoded to 1

## [0.3.9] - 2026-04-07

### Added
- Multiple alerting configurations per metric: `alerting` now accepts a list of alert configs, each with its own channels, timezone, template, and conditions
- Backward-compatible: single `alerting:` dict still works as before

## [0.3.8] - 2026-04-07

### Added
- **Channel-agnostic mentions** in alert messages (`mentions` config field)
- `format_mentions()` method on `BaseAlertChannel` — overridable per channel
- Platform-specific formatting: Mattermost (`@user`), Slack (`<!here>`, `<@UID>`), Telegram (`@user`), Email (`CC: user`)
- `{mentions}` and `{mentions_line}` template variables for custom placement
- Special keywords: `here`, `channel`, `all` for broadcast mentions
- Documentation: mentions guide, 4 example scenarios, updated configuration reference

## [0.3.7] - 2026-04-06

### Changed
- Mattermost alerts now use attachments format with colored sidebar (red for anomaly, green for recovery)
- Webhook default templates omit metric name from body (shown in attachment title)

## [0.3.6] - 2026-04-06

### Added
- Recovery notifications: `notify_on_recovery: true` in alerting config sends a message when metric stabilizes after an anomaly
- `template_recovery` config option for custom recovery message template
- `{status}` template variable in all alert templates (`"ANOMALY"` or `"RECOVERED"`)
- `is_recovery` field on `AlertData` to distinguish recovery messages from anomaly alerts
- `AlertOrchestrator.should_send_recovery()` — checks recovery conditions and returns AlertData
- `AlertOrchestrator.send_recovery()` — sends recovery via configured channels and tracks timestamp
- `_dtk_tasks.last_recovery_sent` column for deduplication (one recovery notification per incident)
- `InternalTablesManager.get_last_recovery_timestamp()` and `update_recovery_timestamp()` methods
- `BaseAlertChannel.get_default_recovery_template()` method

### Migration
Existing installations need to add the new column manually:
```sql
ALTER TABLE _dtk_tasks ADD COLUMN last_recovery_sent Nullable(DateTime64(3, 'UTC'));
```

## [0.3.2] - 2025-11-11

### Fixed
- Critical bug: Newly added detectors no longer start processing from 1970-01-01 (epoch)
- `get_last_detection_timestamp()` now properly handles epoch timestamps returned by ClickHouse for NULL values
- This completes the epoch fix from v0.2.5 which only fixed the datapoints method

## [0.3.1] - 2025-11-10

### Fixed
- CLI now shows warnings when metric files fail to parse (YAML syntax errors, validation errors, etc.) instead of silently skipping them
- Tag selector (`--select tag:`) now searches both `.yml` and `.yaml` files (previously only searched `.yml`, inconsistent with name selector)

### Changed
- Improved error messages when no metrics are found - now provides feedback about which files were skipped due to parsing errors
- Made metric file discovery consistent across both tag and name selectors

## [0.3.0] - 2025-11-10

### Added
- Alert cooldown system to prevent spam from persistent anomalies
- `alert_cooldown` configuration parameter (supports "30min" string or integer seconds)
- `cooldown_reset_on_recovery` option to reset cooldown when metric recovers
- `_dtk_tasks.last_alert_sent` column to track last alert timestamp
- `_dtk_tasks.alert_count` column to track total alerts sent per metric

### Changed
- `AlertOrchestrator` now checks cooldown period before sending alerts
- `InternalTablesManager` added methods: `get_last_alert_timestamp()`, `update_alert_timestamp()`
- Alert orchestration moved cooldown check before expensive operations for performance

### Fixed
- Alert spam when persistent anomalies generate duplicate alerts at every interval

## [0.2.8] - 2025-11-10

### Fixed
- Detection step no longer runs with 0 points when current interval is incomplete
- Alerts no longer sent when 0 anomalies detected in current run
- `get_recent_detections()` now filters by `created_after` to prevent loading old detections from previous runs

## [0.2.7] - 2025-11-10

### Added
- `_dtk_metrics` informational table for analysts and dashboards
- Metric configuration metadata stored automatically on every `dtk run`
- `description` field support in metric configuration files
- Tags extraction and storage in `_dtk_metrics` table

### Fixed
- Timezone warning in `load_datapoints()` by converting timezone-aware datetimes to naive
- Project name handling in `dtk init` command (now extracts basename from path)

## [0.2.5] - 2025-11-08

### Fixed
- Critical bug: `get_last_timestamp()` returning epoch (1970-01-01) instead of None when no data exists
- Prevented incorrect historical data loading due to epoch timestamp

## [0.2.4] - 2025-11-07

### Changed
- Improved logging output formatting
- Enhanced error messages for better debugging

### Fixed
- Numpy datetime64 comparison warnings by ensuring datetime objects are timezone-naive

## [0.2.3] - 2025-11-07

### Fixed
- Metric name selector (`--select`) now correctly searches metrics in subdirectories
- Previously only searched in root `metrics/` directory

## [0.2.2] - 2025-11-07

### Added
- `requests` dependency for HTTP-based alert channels

## [0.2.1] - 2025-11-07

### Changed
- Alert formatting improved for better readability
- Database-agnostic architecture maintained across all components

### Fixed
- Recursion error in alert message formatting by adding `detector_params` field
- Broadcasting error in seasonality mask application
- Timezone comparison issues in datetime handling

## [0.2.0] - 2025-11-06

### Added
- **Detector Preprocessing**: Transform input values before detection
  - `input_type: "raw"` - Use values as-is (default)
  - `input_type: "diff"` - Detect on differences between consecutive points
  - `input_type: "pct_change"` - Detect on percentage changes
- **Value Smoothing**: Reduce noise with moving average
  - `smoothing_window: N` - Apply N-point moving average before detection
- **Recent Value Weighting**: Weight recent data more heavily
  - `recent_weight: 0.0-1.0` - Weight for recent 20% of window (default: 0.0)
- All statistical detectors (MAD, Z-Score, IQR, ManualBounds) support preprocessing

### Changed
- Detector base classes updated to support preprocessing pipeline
- Detection metadata now includes preprocessing information

## [0.1.2] - 2025-11-05

### Added
- Data integrity validation: uniqueness checks for datapoints and detections
- Tags support for metric categorization and filtering
- `tags` field in metric configuration (YAML array)

### Changed
- Internal tables rebuilt with ReplacingMergeTree engine for automatic deduplication

## [0.1.1] - 2025-11-04

### Added
- Seasonality support for Z-Score detector
- Seasonality support for IQR detector
- Documentation for seasonality features in all statistical detectors

## [0.1.0] - 2025-11-03

### Added
- Initial release of detectkit
- Core functionality:
  - Metric data loading from databases (ClickHouse, PostgreSQL, MySQL)
  - Statistical anomaly detectors (MAD, Z-Score, IQR, Manual Bounds)
  - Seasonality support (MAD detector)
  - Multi-channel alerting (Mattermost, Slack, Telegram, Email)
  - CLI interface (`dtk init`, `dtk run`)
  - Idempotent operations with resume capability
  - Internal tables for state management (_dtk_datapoints, _dtk_detections, _dtk_tasks)
- Documentation:
  - Comprehensive guides (configuration, alerting, detectors)
  - API reference for all detector types
  - Quick start guide
  - Installation instructions
- Testing:
  - 287+ unit tests
  - 87% code coverage

---

## Version Links

- [0.3.0]: https://github.com/alexeiveselov92/detectkit/releases/tag/v0.3.0
- [0.2.8]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.7...v0.2.8
- [0.2.7]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.5...v0.2.7
- [0.2.5]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.4...v0.2.5
- [0.2.4]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.3...v0.2.4
- [0.2.3]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.2...v0.2.3
- [0.2.2]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.1...v0.2.2
- [0.2.1]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.0...v0.2.1
- [0.2.0]: https://github.com/alexeiveselov92/detectkit/compare/v0.1.2...v0.2.0
- [0.1.2]: https://github.com/alexeiveselov92/detectkit/compare/v0.1.1...v0.1.2
- [0.1.1]: https://github.com/alexeiveselov92/detectkit/compare/v0.1.0...v0.1.1
- [0.1.0]: https://github.com/alexeiveselov92/detectkit/releases/tag/v0.1.0
