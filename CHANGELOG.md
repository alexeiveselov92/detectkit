# Changelog

All notable changes to detectkit will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.67.2] - 2026-08-21

### Fixed
- **A metric with `enabled: false` kept loading, detecting and alerting.** The
  metric-level flag was a silent no-op: `dtk run` never read `config.enabled`, so
  a metric disabled in its YAML stayed fully live — and the disagreement was
  documented the wrong way round, with three doc surfaces (the
  `configuration-metrics` guide and both rules `dtk init-claude` ships) promising
  "disabled metrics are skipped by `dtk run`". In production a metric was disabled
  and pushed; the next scheduled run processed it anyway and paged the on-call
  channel, with fresh `_dtk_datapoints` / `_dtk_detections` rows to prove the flag
  had simply never been consulted (#162). Its only readers were the informational
  `_dtk_metrics` registry, `dtk ui` and `dtk mcp` — display, never control.

  `enabled: false` now takes the metric out of the pipeline entirely: no load, no
  detect, no alert, no pipeline lock. `dtk autotune` skips it too (tuning a retired
  metric would persist detections and emit a `__tuned_<id>.yml` for it),
  independently of the narrower `autotune.enabled` switch.

  The skip is **loud**, because silence was the worse half of the bug: `dtk run`
  prints `• <metric>: disabled in config (enabled: false) — skipped`, and
  `dtk run --json` reports the metric with `"status": "skipped"`, zeroed counters
  and `"error": null`, counted in `totals.skipped` (the per-metric key set is
  unchanged — still `schema_version: 1`). It is also **not a failure**: the exit
  code stays `0`, and a run whose every selected metric is disabled exits `0` too
  (only a selector matching *no* metric at all remains the exit-`1` case).

  The gate sits in the runner, not in metric discovery, so a disabled metric stays
  reachable everywhere it should be: `dtk tune`, `dtk ui` (dimmed and sorted last)
  and `dtk mcp` still open it — inspecting a metric you just turned off is how you
  decide whether to fix or delete it — and `dtk clean --orphaned-metrics` still
  sees it as defined in YAML, so its stored history is never purged as orphaned.
  The one database write it still gets is its informational `_dtk_metrics` row, so
  that table's `enabled` column follows the YAML instead of reporting a
  just-disabled metric as enabled forever; a failure there is a warning, never the
  run's exit code.

  Nothing changes for an enabled metric (the default), and the narrower switches
  keep their meanings: `alerting.enabled: false` / `suppress_until` stop the
  notifications while load and detect keep the history continuous,
  `autotune.enabled: false` only opts out of `dtk autotune`.

## [0.67.1] - 2026-08-17

### Fixed
- **Recovery ("Alert cleared") messages showed the wrong detector's `Expected`
  range on a multi-detector metric.** A metric combining a MAD band with a
  `manual_bounds` floor would fire with `Expected [249.34, 418.61]` (the MAD
  band that actually tripped) and then clear with `Expected >= 30.00` — the
  floor's `lower_bound`, a detector that had nothing to do with the alert. The
  `Detectors` and `Parameters` fields in the collapsed tail were wrong the same
  way. Nothing was mis-*evaluated* — the rule, the alert config and the channel
  were all correct, and the same `Rule` chip rendered on both messages — but the
  evidence in the cleared message pointed at the wrong detector, which reads as
  if a different condition had cleared.

  Cause: the fire path builds its payload from the highest-severity record of
  the alert quorum, while the recovery path took `detections[-1]` — literally
  the last row of the latest timestamp. Since `get_recent_detections` orders by
  `ORDER BY timestamp DESC, detector_id`, that selected whichever detector's
  **id hash sorted last**, unrelated to which detector fired. Recovery now
  resolves the incident's firing detector (`_resolve_incident` already re-walks
  the quorum to compute the incident span, so it now also returns that
  quorum's primary record) and renders **that** detector's band at the
  recovered point — so the message reads "the detector that fired is back
  inside its band" and the outcome no longer depends on SQL row ordering.

  Also fixed in the same path: a **one-sided** band (a `manual_bounds` detector
  with only `lower_bound`, so `confidence_upper` is legitimately `None`) tripped
  a "no band here" fallback that jumped to an unrelated record — the check
  required *both* bounds to be present. `expected_range` renders one-sided
  bounds fine (`>= 30.00`), so the fallback now only triggers when a record
  carries no bound at all (a missing-data / insufficient-data placeholder).

  Single-detector metrics, the direct-API path and the `Rule` chip are
  unaffected. The fix rides in the shared `_build_recovery_data`, so replayed
  recovery events in `dtk run --report` and `dtk ui` are corrected too.

  Note this is a *rendering* fix, not a scoping one: detectors remain
  **metric-level**, and every `alerting:` block still forms its quorum over
  **all** of a metric's detectors (`AlertConfig` has no detector filter). On a
  metric with `min_detectors: 1` and two detectors, either detector can fire
  either alerting block — per-block detector scoping is tracked separately as
  [#160](https://github.com/alexeiveselov92/detectkit/issues/160).

## [0.67.0] - 2026-08-04

### Added
- **`dtk ui` Builder: `source_profile`, `suppress_until` and three more alerting
  fields are now real form controls.** The Builder's
  modeled-fields-plus-verbatim-passthrough invariant meant an unmodeled key was
  never *lost* — but it also could never be *added*: setting one on a metric
  created in the browser required switching to the YAML tab, and for the nested
  alerting keys the only hint it existed was an anonymous `+N fields preserved`
  chip. Now modeled:
  - **`source_profile`** — a second profile picker in Basics, right below
    `profile`, seeded from the same `form_meta.profiles` list. This is
    [hybrid mode](docs/guides/hybrid-mode.md): the metric's load SQL runs on
    another profile's database while all `_dtk_*` state stays on the state
    profile. Source-only backends (Snowflake, BigQuery) are valid *only* there,
    so a hybrid metric is now creatable start to finish in the browser.
  - **`suppress_until`** — in the alerting section proper (not behind Advanced):
    it's the operational mute you reach for during a known incident, with an
    inline format check.
  - **`links`** — a `{label: url}` pair-row editor under Advanced (add/remove
    rows), next to the existing `dashboard_url`, with the same http(s)-only
    check the server enforces.
  - **`timezone`** and **`cooldown_reset_on_recovery`** — under Advanced;
    the latter emits only an explicit `false`, so untouched configs stay
    byte-identical.

  The four `template_*` message bodies stay YAML-tab-only on purpose (multi-line
  text a form renders badly), and still round-trip verbatim. Regenerated
  `ui.js`.

### Fixed
- **A malformed `alerting.suppress_until` is now refused when the config loads,
  instead of failing the metric mid-run.** It was an unvalidated string that the
  alert step parsed with a strict `datetime.strptime(..., "%Y-%m-%d %H:%M:%S")`,
  so a typo raised a `ValueError` in the middle of the alert step — and the
  date-only form the docs' own examples use (`suppress_until: "2026-07-01"`) was
  one of those typos. Parsing now lives in one seam,
  `parse_suppress_until()` (`detectkit/config/metric_config.py`), shared by a new
  `AlertConfig` field validator and the alert step: it accepts
  `"YYYY-MM-DD HH:MM:SS"`, `"YYYY-MM-DD HH:MM"`, the ISO `T` form and a bare
  `"YYYY-MM-DD"` (midnight UTC), and rejects everything else at load — including
  at a `dtk ui` editor save, before anything is written.

## [0.66.5] - 2026-07-16

### Changed
- **`dtk ui`: the top toolbar now stays pinned while you scroll the metrics.**
  The header row — brand, window presets, refresh, **Run pipeline**, **New
  metric** and the jobs (`idle`) chip — is now `position:sticky` at the top of
  the viewport, so it stays reachable on a long, scrolled metrics table instead
  of scrolling out of view. It looks unchanged at rest; once pinned it gains a
  subtle divider + shadow (a `.stuck` class toggled on scroll) to lift it above
  the content sliding underneath. Regenerated `ui.js`.

## [0.66.4] - 2026-07-16

### Fixed
- **`dtk tune`: autoreg `min_samples` no longer silently blanks the band, and it
  now has a control.** An autotune winner sized for a large window can carry a
  `min_samples` close to the window (e.g. `window_size=911`, `min_samples≈911`+),
  which for autoreg means "needs a nearly-full gap-free window to score even one
  point." When exploring a smaller window in the cockpit the scoring path used the
  raw `min_samples` (while the emitted config clamped it to the window), so the
  chart showed **no band** — with no knob to lower it. Now:
  - the TS detector port clamps the effective `min_samples` into
    `[lags + 2, window_size]` (matching the Python constructor's validation and the
    config `dtk tune` emits), so `min_samples > window` can't wedge the preview to
    blank and the live band matches what **Apply** would write;
  - a **Min samples** control is added to the cockpit (shown for autoreg + the
    windowed detectors, hidden for `manual_bounds`), capped at the window size (its
    max tracks the Window slider) and reset to the type default on a detector
    switch — so you can lower it and get a band on a sane window.

  Regenerated `tune.js`.

## [0.66.3] - 2026-07-16

### Fixed
- **`dtk tune` cockpit now shows the confidence band wherever the detector
  scores** — the same band the pipeline persists and a dashboard displays —
  instead of hiding it over the detector's full warm-up context. The previous
  behavior clipped the band to the *effective start* (`get_context_size`), which
  for **autoreg** with its default-on `stabilization: clamp` is `2·window + lags`
  points: on an hourly metric with a 20-day window that is a **40-day** blank
  lead-in, so the chart looked bandless until an implausibly large window/view
  was selected — even though the detector had already scored hundreds of points
  (seasonality was a red herring; autoreg ignores it). The warm-up lead-in is now
  only lightly **dimmed** with a "detection at full power →" divider, never
  erased; the whole-chart "no band" overlay + inline warning now appear **only**
  when the detector genuinely scored nothing (window below `min_samples`, Points
  shown trimmed too low, or a view full of gaps), naming the concrete fixes.
  The Window-size slider's explore cap is now a uniform half-of-shown for every
  detector type (the old clamp-aware autoreg tightening is no longer needed).
  `warmupRequirement` still equals the Python `get_context_size` (the HUD warm-up
  stat and TS/Python parity are unchanged); only how the chart *renders* it
  changed. Regenerated the committed `tune.js` bundle.

## [0.66.2] - 2026-07-16

### Changed
- **The website playground is now a literal instance of the `dtk tune` cockpit**
  running on a *synthetic* metric, not a bespoke demo. It reuses the shipped
  cockpit renderer (`report/tune.ts`) verbatim via a synthetic-`TunePayload`
  adapter (the three localhost server hooks nulled — exactly the
  `dtk tune --no-serve` shape), so a visitor gets the real chart, detector
  worker, four modes (Tune / Review / Label / Autotune), HUD, mode-aware rail
  and live catch-rate/false-alert metrics — plus a small data-generator toolbar
  (rhythm / noise / trend / interval / incident / size) and a one-click autoreg
  **shape-break showcase** (a free-running pulse + a frozen-value pattern break
  the windowed detectors miss and autoreg catches). The playground now also
  honors the site's light / dark / auto theme. **No pip-package behavior
  change:** the `dtk tune` renderer gained only additive, product-inert
  extension points (an optional `onState` hook + a returned `{destroy, resize}`
  handle; the shipped HTML calls `render(payload, mount)` unchanged).

### Internal
- **New `website` CI job** regenerates the golden detector-parity vectors (from
  the real Python detectors) and every committed browser bundle (`report.js` /
  `tune.js` / `ui.js`), then fails on any stale artifact via
  `git diff --exit-code` — converting what were manual release-checklist steps
  into a code-enforced gate so the playground/report/ui bundles can't ship out
  of sync with their TypeScript. Added `build:bundles` (report + tune + ui) and
  `build:ui-bundle` npm scripts.

## [0.66.1] - 2026-07-14

### Fixed
- **`dtk tune`: the seasonality warning no longer fires under an autoreg /
  manual-bounds band** (#148). The cockpit's recompute parameters
  deliberately capture *every* control's state — including the hidden
  windowed-only knobs while `autoreg`/`manual_bounds` is selected, so a
  detector-type switch round-trips without losing the windowed slot's
  settings — which means presentational consumers must branch by detector
  type. The "Seasonality inactive at this window … this is why the band
  widened" warning didn't: with a leftover seasonality selection from a
  previously-selected windowed detector it showed under an **autoreg**
  band, wrongly implying that seasonality settings shape autoreg's
  confidence intervals (autoreg has no seasonality machinery at all — v1
  rejects `seasonality_components`; the band math, warm-up, and the Apply
  write-back were never affected, matching the Python detector). The
  warning now hides for the non-windowed detector types.
- **`dtk tune` / landing chart: leftover smoothing no longer draws a false
  processed-vs-ghost line split under autoreg / manual bounds** (#149).
  Same leak class, found while adversarially verifying #148: the chart
  keyed the metric-line rendering on `smoothing != none` alone, so a stale
  `ema`/`sma` selection drew a ghost raw series plus a duplicate
  "processed" line under detectors that never smooth. The split now also
  requires a windowed detector type.
- **`dtk tune`: a stray `seasonality_components` key on a hand-edited
  autoreg/manual config no longer seeds the cockpit's shared seasonality
  group selector** — `seed_detector_params` forces it to `None` for the
  non-windowed types (the running pipeline rejects or ignores such a key
  anyway). Cockpit bundle (`detectkit/tuning/assets/tune.js`) regenerated.

## [0.66.0] - 2026-07-13

### Added
- **MotherDuck support via the DuckDB backend** (#143). The existing
  `type: duckdb` profile learns cloud paths: `path: "md:<database>"`
  attaches a MotherDuck database through the same `duckdb` client (the
  `motherduck` core extension autoloads on first use), authenticated by
  the new optional `motherduck_token` profile field (env-interpolated;
  unset → the extension falls back to the `motherduck_token` environment
  variable; an explicit `settings` key wins on collision). Unlike the
  source-only warehouses, this is a **full state-capable backend** — the
  `_dtk_*` tables can live on MotherDuck with the same `ON CONFLICT`
  upsert — and the local-file single-writer caveats do **not** apply to
  `md:` paths (a served database: `dtk ui` and a concurrently spawned
  `dtk run` coexist). MotherDuck has no read-only attach, so `read_only`
  is a local-files-only knob and the MCP server's strict connect probe
  skips the forced read-only for `md:` paths (it still runs no DDL — the
  forcing exists to stop a missing local *file* being created on connect,
  which cannot happen on a served database). No new extra — rides
  `detectkit[duckdb]`. Covered by connect-seam unit tests plus an
  env-gated real-account smoke test (`MOTHERDUCK_TOKEN`).

## [0.65.0] - 2026-07-12

### Added
- **BigQuery as a source-only backend** (#142). `type: bigquery` joins
  `snowflake` in `SOURCE_ONLY_TYPES`: valid only as a hybrid-mode
  `source_profile` (the metric's load SQL runs on BigQuery, all `_dtk_*`
  state stays in the state profile), refused as a state profile /
  `--profile` with the same clear error. The profile takes `project`
  (required — the GCP project billed for queries), `credentials_json_path`
  (a service-account JSON key file; unset → **Application Default
  Credentials**: gcloud ADC, an attached service account, or Workload
  Identity), optional `location`, `dataset` (a default dataset so
  unqualified table names resolve), `api_endpoint` (the BigQuery emulator
  or a private/regional endpoint — a plain-`http://` endpoint without a key
  file switches to anonymous credentials, `https://` endpoints authenticate
  normally), and `settings` mapping to `QueryJobConfig` attributes
  (e.g. `maximum_bytes_billed` as a cost guardrail; unknown keys are
  rejected instead of silently ignored). Because constructing the client
  performs no network I/O, the manager runs a free `SELECT 1` probe at
  hybrid-pool build — with **bounded retries** (the client library's
  defaults would retry connection errors for 10+ minutes; the probe caps
  at 30s and load queries at 120s/600s), so a bad project, credentials or
  an unreachable endpoint fails fast instead of stalling the run. `TIMESTAMP` results come back tz-aware UTC (handled
  by the loader since v0.62.0); column aliases keep their case (no
  Snowflake-style folding). New `[bigquery]` extra
  (`google-cloud-bigquery>=3.15`, pyarrow-free core), also in `all-db` /
  `all`. Covered by unit tests plus an integration test against the real
  goccy/bigquery-emulator Docker image — the same no-GCP-account path the
  docs describe. See the [BigQuery guide](docs/guides/databases-bigquery.md).

## [0.64.0] - 2026-07-12

### Added
- **Source-only backend seam + Snowflake as the first source-only backend**
  (#141). Profile types now split into two classes: **state-capable**
  (`clickhouse`, `postgres`, `mysql`, `mariadb`, `duckdb` — hold `_dtk_*` state
  and can also run metric SQL) and **source-only** (`snowflake`), which may be
  referenced only as a hybrid-mode `source_profile` and never store state. A
  new `ProfileConfig.create_source_manager()` builds the minimal
  `SourceDatabaseManager` contract (`execute_query` + `close`) — full backends
  double as sources, while `create_manager()` **refuses** a source-only type as
  a state profile with a clear error, and `dtk run` rejects a source-only
  `--profile` / `default_profile` up front. Snowflake connects via the
  `snowflake-connector-python` driver (the new `[snowflake]` extra, also in
  `all-db` / `all`) with **key-pair authentication** (PEM `private_key_path` +
  optional `private_key_passphrase`, the recommended path as Snowflake retires
  password-only service-account sign-in through 2026) or a password; the session
  `TIMEZONE` is pinned to **UTC** (a user `settings: {TIMEZONE: ...}` merges over
  it) so `TIMESTAMP_LTZ` / `CURRENT_TIMESTAMP` don't shift through the account
  default, and all-uppercase result column names are folded to lowercase so
  `SELECT ... AS value` works without quoting. No tables are ever created on
  Snowflake — the source contract is read-only. Covered by fakesnow-backed CI
  tests. See the [Snowflake guide](docs/guides/databases-snowflake.md).

## [0.63.0] - 2026-07-12

### Added
- **Loader warning on a fully grid-misaligned batch** (#136). Gap-filling
  matches source rows to the metric's time grid by exact timestamp, so a
  query whose timestamps sit on a different grid *phase* (e.g. rows at `:28`
  against a `10min` grid phased at `:00` by `loading_start_time`) used to
  load 100% NULL silently — reading as "my data is gone". The loader now
  emits a one-time warning per metric per run when a batch returned rows but
  **none** landed on the grid, naming the interval, the grid phase and the
  observed source phase, a concrete source-row-vs-nearest-grid-slot example,
  and the fix (bucket the query's timestamps with
  `toStartOfInterval`/`time_bucket`/`date_trunc`, or align
  `loading_start_time` with the source phase). Partial alignment, empty
  results, and `fill_gaps=False` never warn; what gets loaded is unchanged.
  The query contract note in the metrics guide now spells out the
  grid-bucketing requirement.
- **Landing: all four wave-1 channels joined the alert-preview selector**
  (#130) — the "same alert on every channel" demo now renders Discord
  (status-colored embed with the inline field grid), Microsoft Teams
  (Adaptive Card posted under the flow's identity — no branding, honestly),
  Google Chat (Cards v2 with the brand header) and ntfy (a push notification
  with the tag-emoji status cue and per-kind priority) alongside
  Slack/Mattermost/Telegram/Email, in both anomaly and recovery states,
  mirroring the real channel modules' default output. Website-only change.

## [0.62.1] - 2026-07-12

### Fixed
- **Documentation refresh across every surface** — closed the gaps left by the
  v0.58–v0.62 feature wave:
  - Corrected the documented **DuckDB version floor to 1.1+** (was wrongly
    "0.10+" in the databases overview, the DuckDB guide, and the installation
    page — duckdb < 1.1 breaks the alert step's list-parameter query).
  - Installation page now documents the **`[mcp]` extra** and the `[all]`
    extra's real contents (all DB drivers + Prophet/TimesFM + OSI interop +
    MCP SDK).
  - The internal-tables reference now describes all **five** backends
    (MariaDB and DuckDB were missing from its backend/dedup notes).
  - CLI reference: `dtk init --db-type` (clickhouse/postgres/mysql/mariadb)
    is now documented with an example.
  - Docs index: the Guides list gained the missing **Databases** and
    **Hybrid mode** entries, and hybrid mode is now introduced in the
    Database Support section.
  - README: `detectkit[duckdb]` install example; the `dtk init-claude` bullet
    now says **five** skills (was "three").
  - `dtk init-claude` assets: the overview rule now names all five backends;
    the CLI rule's Scheduling section now surfaces the composite
    **GitHub Action**.
  - Contributor rules: project-layout tree gained the `ui/` and `mcp/`
    packages and the MariaDB/DuckDB backends; dev-setup extras list now
    includes `mariadb`, `duckdb`, `osi`, `mcp`.
  - Landing page: the hero "Works with" badges now include **MariaDB** and
    **DuckDB**, and the "Alerts to" badges now include **Discord, Microsoft
    Teams, Google Chat and ntfy** (the icon set was never extended when the
    wave-1 channels shipped in v0.59.0).
  - GitHub Action guide examples pin to the current release tag.

## [0.62.0] - 2026-07-12

### Added
- **MCP server** (`dtk mcp`, `pip install detectkit[mcp]`) — a strictly
  **read-only** [Model Context Protocol](https://modelcontextprotocol.io)
  stdio server over the project's `_dtk_*` state, so an AI assistant
  (Claude Code / Claude Desktop / any MCP client) can answer "which metrics
  fired this week and why" against real pipeline data. Ten tools:
  `list_metrics` (dtk selectors work), `get_metric` (config incl. SQL and
  `ai_context`; channel *names* only — never channel params/secrets),
  `get_metric_status` / `get_project_status` (the same overview rows
  `dtk ui` shows), `query_datapoints` / `query_detections` (newest-first,
  bounded fetch with hard caps), `replay_alerts` (the same pure replay seam
  reports use — never `_dtk_alert_states`), `get_autotune_history`,
  `get_incidents`, `get_server_info`. Read-only is enforced, not promised:
  managers are constructed with the new `ensure_locations=False` (no
  `CREATE DATABASE/SCHEMA` on connect), `ensure_tables()` is never called,
  and the server contains no write/DDL/subprocess code paths. Project
  resolution: `--project-dir` → `DETECTKIT_PROJECT_DIR` → cwd; a `--select`
  given at startup scopes which metrics every tool may see. Isolated like
  the OSI layer: the pipeline never imports `detectkit/mcp/`, and the `mcp`
  SDK (pinned `>=1.27,<2`) is a lazy, guarded import. New guide:
  `docs/guides/mcp.md`.
- **GitHub Action** — a composite action at the repo root wrapping the CLI:
  `uses: alexeiveselov92/detectkit@v0.62.0` installs detectkit from PyPI and
  runs `dtk run`/`autotune`/`clean` in your project directory, preserving
  the 0/1/2 exit-code contract as the job outcome and exposing the
  `dtk run --json` summary as an action output for downstream gating. Ships
  with a self-contained DuckDB example (`examples/action-smoke/`) and a
  smoke workflow. New guide: `docs/guides/github-action.md`.
- `ProfileConfig.create_manager(ensure_locations=False)` — construct any
  backend manager without its connect-time `CREATE DATABASE`/`CREATE SCHEMA`
  side effects (DuckDB opens read-only), for read-only consumers.

### Fixed
- **Loader crash on tz-aware source timestamps** (#135): a metric whose SQL
  returns timezone-aware timestamps (DuckDB `now()`/`TIMESTAMPTZ`,
  PostgreSQL `timestamptz`) crashed the load step with "can't compare
  offset-naive and offset-aware datetimes". Timestamps are now converted to
  the naive-UTC convention at the loader boundary. As part of this,
  `to_naive_utc` now genuinely converts an aware datetime to UTC (a no-op
  for already-UTC values) instead of just stripping tzinfo — a non-UTC
  aware timestamp previously kept its local wall-clock time silently.

## [0.61.0] - 2026-07-12

### Added
- **Hybrid mode (`source_profile`)** — read metric SQL from one database,
  keep detectkit's state in another. A new optional `source_profile` field on
  the metric (overriding a project-wide default; resolution
  metric → project → unset, like `loading_delay`) names the `profiles.yml`
  profile whose database runs that metric's **load** query, while every
  `_dtk_*` table — datapoints, detections, task locks, alert state — stays in
  the **state** profile (the one `dtk run --profile` / `default_profile`
  selects; its meaning is unchanged, and a project with no `source_profile`
  anywhere behaves exactly as before). This is the warehouse unlock:
  warehouses bill in ways that punish detectkit's frequent small state writes,
  so point the load at the warehouse and keep state in a cheap local database
  (e.g. DuckDB or PostgreSQL). Implementation notes: one lazily-opened
  connection per source profile per run (shared across metrics, closed on
  exit; a failed source connection is cached, not retried per metric);
  detect/alert-only runs never open source connections; a source-side failure
  raises `SourceDatabaseError` with a message leading with
  `source database (profile '<name>')`, so an error alert distinguishes a
  warehouse outage from a state-DB outage; `dtk run` fail-fast validates every
  resolved `source_profile` name before opening any connection (a typo exits 1
  without paging `error_alerting`). `dtk autotune` / `tune` / `ui` / `clean` /
  `unlock` are state-only and unaffected. New guide:
  `docs/guides/hybrid-mode.md`.

## [0.60.0] - 2026-07-12

### Added
- **DuckDB backend** (`type: duckdb`, `pip install detectkit[duckdb]`,
  duckdb >= 1.1). An in-process, single-file analytical database — no server,
  no credentials; the fastest way to run detectkit locally, in CI, or on a
  laptop. The profile takes `path` (the database file; `:memory:` works for
  one-off tests but breaks resume between runs) plus optional
  `internal_schema` / `data_schema` / `read_only`. Implemented as a
  `SQLDatabaseManager` subclass behind a small DB-API adapter (DuckDB's
  Python API takes `$name`/`?` placeholders and autocommits, so the adapter
  translates `%(name)s` and manages lazy explicit transactions), with the
  PostgreSQL-shaped version-aware `ON CONFLICT` upsert mirroring
  `ReplacingMergeTree` last-writer-wins semantics. The version floor is 1.1
  because the alert step's `IN`-list parameter query only parses from
  duckdb 1.1 (verified against real 0.10 / 1.0 / 1.1 engines). Operational
  model, documented in the new DuckDB guide: the file is held **read-write by
  one process at a time** (readers coexist only with `read_only: true`), so
  a long-lived `dtk ui` and a concurrently spawned `dtk run` against the same
  file conflict — run-then-look. Real-engine tests run in the unit suite (no
  Docker) including an end-to-end internal-tables round trip.

### Changed
- `ProfileConfig.port` is now optional and enforced **per backend type**: the
  server backends (clickhouse/postgres/mysql/mariadb) still require it (with a
  clearer "port is required for database type 'x'" error), while DuckDB
  profiles omit it entirely.

## [0.59.0] - 2026-07-12

### Added
- **Discord alert channel** (`type: discord`). Native incoming-webhook
  rendering: one status-colored embed (integer color) per alert, the same
  `description → Rule → Value/Expected → links` order as every other channel,
  and — since Discord has no "Show more" fold — the verbose evidence tail as a
  compact inline **field grid** (Quorum / Severity / the anomalous span /
  Detectors; the incident timeline on recovery). Brand `username`/`avatar_url`
  by default, branded footer + timestamp, clickable title via `dashboard_url`.
  Mentions ride in top-level `content` with `allowed_mentions`: `all` /
  `everyone` / `channel` → `@everyone`, `here` → `@here`, and a literal
  `<@id>` / `<@&id>` passes through and really pings (bare names render but
  don't ping). Discord's per-part limits and the 6000-character embed-total
  budget are enforced defensively, truncating on line boundaries so a markdown
  link is never sliced mid-URL.
- **Microsoft Teams alert channel** (`type: teams`) via the **Power Automate
  Workflows webhook** ("When a Teams webhook request is received") posting an
  **Adaptive Card 1.4** — the only path that still works after Microsoft
  retired Office 365 connectors (legacy MessageCard tutorials no longer
  apply). Status-colored TextBlock headline (Attention/Good/Warning/Accent), a
  monospace Rule chip, a FactSet evidence tail, `Action.OpenUrl` buttons for
  dashboard/links/help. Honest caveats, documented: the message posts under
  the flow's identity (no bot branding on this path) and mentions render as
  plain text (an Adaptive Card ping needs AAD user ids).
- **Google Chat alert channel** (`type: googlechat`). Space incoming webhook,
  **Cards v2** (Cards v1 is deprecated): brand avatar + `detectkit · <project>`
  in the card header, HTML-escaped `decoratedText` evidence rows, action
  buttons for dashboard/links/help. Mentions ride in top-level text — `all` /
  `everyone` / `channel` / `here` collapse to one `<users/all>`, a literal
  `<users/USER_ID>` passes through and pings; card content never pings.
- **ntfy alert channel** (`type: ntfy`). Publishes push notifications via
  ntfy's JSON endpoint (server root, so UTF-8 titles/bodies survive — headers
  can't carry them) to `server` (default `https://ntfy.sh`) + `topic`, with
  Bearer-token or user/password auth. Per-kind priority (anomaly/error 4,
  recovery/no-data 3; an explicit `priority` overrides only anomaly/error) and
  a per-kind tag emoji as the status cue (the title's status dot is stripped
  so the glyph isn't doubled); `dashboard_url` becomes the notification's
  `click` action, extra links + the help link become view actions (ntfy's max
  3); message capped under ntfy's ~4 KB limit.
- **Rocket.Chat — documented recipe** through the existing generic `webhook`
  channel: a script-less Rocket.Chat incoming webhook accepts the same
  Slack-style attachments payload (verified against current Rocket.Chat docs),
  so no dedicated type is needed. Covered in the alerting-channels guide.
- A **factory-registry test** pins every config-facing channel type string
  (`discord`/`teams`/`googlechat`/`ntfy` plus the five existing ones) to its
  channel class, and each new channel joins the send-contract suite; `dtk init`
  scaffolds commented profile examples for all four new types.

### Changed
- The **Rule chip** now renders only on anomaly/recovery across all channels —
  no-data and error alerts don't fire on the quorum rule, so the new channels
  never show it there (the existing five already didn't).

## [0.58.0] - 2026-07-11

### Added
- **`dtk run --json` — a machine-readable run summary.** One JSON document
  (`schema_version: 1`) on stdout with per-metric status/steps/counters,
  run-level totals, timing, and the exit code; every human-readable line
  (including the pipeline's own progress tree) moves to stderr, so stdout can
  be piped straight into `jq` or a file. The document is emitted even when the
  run dies unexpectedly (status `error`/`failed` with the error message), so a
  consumer parsing stdout never sees an empty stream.
- **Webhook payload formats: `format: json` and `format: alertmanager`.** The
  generic `type: webhook` channel (Slack/Mattermost are unaffected) can now
  post, instead of the chat-style attachment card: a **versioned structured
  event** (`format: json`, `schema_version: 1` — kind/status, raw
  value/expected bounds, the resolved alert rule and quorum, incident
  onset/streak/duration, links, and the same display strings the human
  channels render), or a **Prometheus Alertmanager webhook-receiver payload**
  (`format: alertmanager`, version `"4"`), so any tool that already ingests
  Alertmanager webhooks can take detectkit alerts with no new integration — a
  recovery reuses the firing alert's labels and `fingerprint` (anomaly
  `direction` deliberately rides as an annotation, since a recovery carries no
  direction and a direction label would break trigger/resolve pairing). Both
  structured formats add an `X-Detectkit-Event` header and ignore a custom
  `template`.
- **Webhook HMAC signing (`secret`).** When set on a webhook channel, every
  request (any format) carries a GitHub-style
  `X-Detectkit-Signature-256: sha256=<hex>` header — HMAC-SHA256 over the
  exact request body bytes — so a receiver can verify the payload really came
  from detectkit before acting on it.
- **MariaDB support.** The MySQL backend now detects the server vendor at
  connect time (`SELECT VERSION()`) and, on MariaDB, renders upserts in the
  classic `VALUES()` form — the MySQL 8.0.19+ row-alias form the backend uses
  on stock MySQL was never adopted by MariaDB, so dedup/last-writer-wins now
  works there instead of failing with a syntax error. `type: mariadb` is a new
  profile alias (identical fields; plain `type: mysql` against a MariaDB
  server also works — detection is by the live server, not the profile),
  `pip install detectkit[mariadb]` names the extra, `dtk init --db-type
  mariadb` scaffolds it, and the Docker integration matrix now runs MariaDB
  11.x alongside ClickHouse/PostgreSQL/MySQL.
- **Orchestrator recipes.** The CLI reference's Scheduling section gains an
  "Orchestrators & CI" part with Airflow (`BashOperator`), Dagster, Prefect,
  and GitHub Actions recipes, all gating on the new exit codes and `--json`.

### Changed
- **`dtk run`, `dtk autotune`, and `dtk clean` now exit non-zero on failure.**
  Previously every failure — a failed metric, a dead database, a missing
  `profiles.yml`, a selector matching nothing — printed an error and exited
  `0`, so cron/Airflow/CI gates never saw it (the docs told you not to trust
  the exit code). Now: `0` success, `1` failure (any metric failed, the run
  aborted after a project error alert, a startup/config/DB error, or the
  selector matched no metrics — a typo'd selector in cron must not look
  healthy), `2` usage error (for `dtk clean`, that includes being called with
  both or neither of `--select`/`--orphaned-metrics`). `dtk autotune` counts a
  metric with autotuning disabled as skipped (not failed); answering "no" to
  `dtk clean`'s confirmation prompt stays `0`. `dtk ui`'s job panel picks the
  codes up automatically — a failed spawned run now shows as failed instead of
  done.
- **Webhook channels serialize the request body themselves.** The payload is
  now `json.dumps`-ed in the channel (UTF-8, `ensure_ascii=False`) and posted
  as raw bytes so the HMAC signature covers the exact bytes sent. The only
  receiver-visible difference from the previous `requests` behavior: non-ASCII
  text (e.g. a metric description in Russian) arrives as raw UTF-8 instead of
  `\uXXXX` escapes — byte-identical JSON semantics either way.

## [0.57.0] - 2026-07-11

### Added
- **`dtk tune`: a `min_samples_per_group` knob in the cockpit.** The manual
  tuner already exposed the seasonality *grouping*, but the per-group fill
  threshold — how many same-key points the window must hold before a seasonal
  group earns its **own** band — was pinned to the per-detector default and could
  not be tuned. It is now a slider (shown only for a metric that has seasonality
  columns, hidden for `autoreg` / `manual_bounds` like the other windowed-only
  knobs), clamped to the active detector's floor (IQR's is 4) and reset to the
  type default on a detector switch, just like the threshold knob. This matters
  because a seasonal group engages only when
  `window_size ≳ min_samples_per_group × distinct_keys`, so **shrinking Window
  size / Points shown can silently push a group below the threshold** — the band
  falls back to the global statistics and *widens for a reason that isn't the
  smaller window itself*, which reads like the window shrink "broke" the band.
  The under-window warning now names lowering this knob as the alternative to
  widening the window, so the trade-off is legible instead of a mystery. This is
  a manual lever only: `dtk autotune` still holds `min_samples_per_group` at the
  class default and steers group-fill through `window_size` /
  `seasonal_fill_window` (unchanged).

### Fixed
- **`dtk tune`: a metric's configured `min_samples_per_group` is now honored in
  the live preview.** The cockpit's recompute always read the per-detector
  *default* (MAD 10 / Z-Score 3 / IQR 4), silently discarding a non-default
  `min_samples_per_group` set in the metric YAML — so the previewed band, the
  effective-config echo and Apply could all disagree with the metric's real
  config. The live read now honors the seeded value (and the new knob when
  present). Purely a `dtk tune` preview/write-back fix — the pipeline detectors
  always read the configured value.

## [0.56.2] - 2026-07-11

### Fixed
- **No more false no-data alerts when `loading_start_time` isn't aligned to the
  epoch interval grid.** The load step anchors a metric's datapoint grid on
  `loading_start_time` (or the resume cursor descended from it), so a start that
  isn't a multiple of the interval — e.g. `loading_start_time: "2024-06-01
  00:07:00"` on a `10min` metric — persists points at `:07 / :17 / :27 / …`. But
  the alert step's no-data check floored **plain epoch wall-clock time** to find
  "the last complete interval" (`:00 / :10 / :20 / …`) and then did an
  **exact-timestamp** lookup at that boundary — a grid point the loader *never*
  writes. The result was a permanent false no-data alert that re-fired every
  cooldown cycle while the metric was perfectly healthy (the two grid phases only
  coincided when the start happened to be epoch-aligned, which round values like
  `2024-01-01 00:00:00` guarantee — so most configs never hit it). The no-data
  expectation now floors onto the metric's **own** interval grid: the phase
  (`loading_start_time_epoch % interval`) rides as orchestrator constructor state
  — the mirror of the `loading_delay` maturity shift added in 0.54.0, and
  composed with it (subtract the delay, then floor on the metric's phase) — so
  the exact-timestamp lookup asks for a boundary the loader actually persisted.
  Resolved through one seam (`resolve_grid_phase_seconds`), shared by the load
  and alert steps so the two grid phases can't drift. Epoch-aligned metrics and
  direct-API callers are unchanged (phase 0 = the previous behaviour); the
  anomaly / recovery / report-replay paths were never affected (their fetches are
  `<=`-bounded, not exact-match). No config change or migration needed — an
  existing misaligned metric is fixed on upgrade. (#114)

## [0.56.1] - 2026-07-11

### Fixed
- **`dtk ui`: the overview table's columns line up across blocks and the action
  buttons stay on screen.** Each `metrics/<dir>/` block renders as its own
  `<table>`, and the columns were auto-sized to each block's own content: a long
  metric name (e.g. `league_group_assigned_users_pct_to_5_league_not_ru`) widened
  that block's Name column and pushed the **Open / Tune / Run / Edit** buttons past
  the right edge — where the `overflow:hidden` wrapper clipped them out of reach —
  while every block sized its Name column to a different width, so the blocks didn't
  align. The table is now `table-layout: fixed` with a shared `<colgroup>` pinning
  identical column widths in every block (Name is the one flexible column, absorbing
  the leftover): the blocks line up regardless of their longest name, the actions
  column is a fixed width so all four buttons always fit, a long name wraps inside
  its column instead of shoving the layout, and the wrapper scrolls horizontally on
  a narrow viewport instead of clipping the buttons away. UI-bundle only — no
  pipeline or config behavior changes.

### Added
- **`dtk ui`: clean stale detector data from the cockpit.** Every retune /
  autotune / detector-param edit changes the `detector_id`, and the superseded
  generation's rows stay in `_dtk_detections` forever — visible in the metric
  detail (which deliberately shows *what actually ran*) but mixed in with the
  current config's series, with no way to prune them short of leaving for a
  terminal. The detail overlay now carries a **Clean stale** action: a
  read-only preview (`GET /api/clean-preview/<name>` — the `dtk clean` dry-run
  as JSON: exact superseded detector ids, row counts, stale alert states, and
  the CLI's "config defines no detectors" warning) feeds an inline confirm
  strip, and confirming spawns the real `dtk clean --select <metric>
  --execute` as a pipeline job (`POST /api/clean`, a new `clean` job kind
  sharing run/autotune/unlock's one-at-a-time gate) — the UI stays a
  superstructure over the CLI, no new mutation path. Both the preview and the
  execute refuse while a `dtk tune` session for that metric is open (its Apply
  rewrites the YAML the spawned `dtk clean` re-reads), the same guard metric
  edit/delete carry. On success the report reloads showing only the current
  config's detectors and the metric's stats row refreshes.
- **`dtk ui`: stale-generation count on the overview row.** Each metric's row
  now carries `stale_detectors` (stored detector ids the current config no
  longer produces; `null` when unknown) and the table shows an amber `N stale`
  chip next to the metric name, so leftover generations are visible before
  opening the detail. Underivable configs stay `null` — never presented as
  "everything is stale".
- **`DetectorFactory.detector_id_for_config`** — the one shared derivation of
  a configured detector's `detector_id` (params + seasonality → factory →
  hash), now used by the overview's current-config filter, `dtk clean`'s
  drift diff and the new clean preview instead of three private copies.

## [0.55.2] - 2026-07-11

### Fixed
- **`dtk ui`: a blank metric name no longer surfaces as a raw pydantic error on
  the YAML tab.** In the create editor, clearing the starter name and touching
  any Builder control (e.g. picking another detector type), then switching to
  the YAML tab, re-emitted a config with no `name:` — the live-validation chip
  showed the server's truncated `invalid metric config: 1 validation error for
  MetricConfig`, which then "disappeared" back on the Builder tab (it showed
  its own soft "name is required" instead), reading as a tab-sync bug. Now,
  while the YAML tab still holds the form's own re-emit (nothing hand-typed
  since the two views last agreed), the chip **and** Save reuse the Builder's
  friendly client-side checks — the same "name is required" warn in both tabs,
  with no doomed parse round-trip. Genuinely hand-edited YAML still gets the
  server verdict, now summarized to one readable `field — reason` line
  (`invalid metric config: name — Field required`) with the full error text in
  the chip's tooltip. The Builder's client-side name check now mirrors the
  server rule exactly (unicode-aware `isalnum` plus `_`/`-`; it was
  ASCII-only), so the client checks can never block a config the server would
  accept.

## [0.55.1] - 2026-07-11

### Fixed
- **`dtk ui`: the Builder's create flow could trap you on the YAML tab.** A new
  metric's Builder opened with a *blank* name (the YAML tab's template has
  `name: my_metric`), so touching any control and switching to YAML emitted a
  config with no `name:` — the live-validation chip then 400-ed on every
  keystroke (`[ui] 400 /api/metric-parse: … 1 validation error`) and, once the
  YAML was edited, the way back to the Builder was hard-blocked on a valid
  parse, leaving the editor apparently frozen. Three fixes: the Builder now
  seeds the same starter name as the YAML template (an OSI compile still
  overrides it); switching YAML → Builder with an invalid draft now offers to
  return anyway, discarding the YAML edits (the Builder keeps its own state),
  instead of hard-blocking; and `/api/metric-parse` 400s are no longer echoed
  to the `dtk ui` terminal — draft rejection is that route's routine outcome,
  surfaced in the page's validation chip, and echoing it spammed the terminal
  while someone simply typed. Other routes' 400s still echo.

## [0.55.0] - 2026-07-11

### Added
- **`dtk ui`: a Builder form for the metric editor, next to the raw YAML.**
  Creating or editing a metric used to mean a bare textarea over the whole
  file; the editor now opens two tabs sharing one draft — **Builder** (a
  structured form) and **YAML** (the existing raw editor, kept for experts who
  paste whole configs). The last-edited tab wins, never silently: switching
  away from a dirty YAML tab first validates it server-side
  (`POST /api/metric-parse`, a new pure-CPU route with no filesystem/DB access)
  and blocks the switch on error, while switching away from a dirty Builder
  re-emits the YAML deterministically. A debounced live-validation chip (quick
  client checks, then the same `/api/metric-parse`) shows valid/invalid while
  typing; **Save** still posts through the unchanged create/update endpoints
  and surfaces their authoritative errors.
  - The SQL query gets a dedicated syntax-highlighted code pane (keywords,
    strings, comments, numbers, Jinja `{{ … }}` variables — a hand-rolled
    highlighter, no new runtime dependency). A metric using `query_file` shows
    the path read-only; the Builder never silently converts it to an inline
    `query:`.
  - The query source has a second sub-tab, **From OSI**: paste an OSI semantic
    model, inspect it server-side (`POST /api/osi-inspect`), pick a metric and
    a target (`clickhouse` or `cube`), and **Compile**
    (`POST /api/osi-import`) — the exact same `import_osi_metric` code path
    `dtk osi import` uses, so the Builder and the CLI produce identical output.
    The compiled SQL, description and `ai_context` seed the form, and the
    sql-fingerprint lands in a YAML header comment exactly like the CLI
    command. The `clickhouse` target still needs the optional `[osi]` extra
    (sqlglot) — the error message says so; `cube` doesn't.
  - Every other parameter gets a form control: basics (name, description,
    tags, profile, enabled), schedule & loading (interval with presets,
    `loading_start_time`; advanced: `loading_delay`, `loading_batch_size`,
    `query_columns`), seasonality checkboxes, minimal detector rows (type plus
    1-2 key params — threshold/window_size, lags for `autoreg`, lower/upper
    for `manual_bounds` — with a hint that fine-tuning belongs in `dtk tune`),
    alerting (a channel multi-select seeded from `profiles.yml`, plus
    consecutive/direction/no-data/recovery/cooldown and, under advanced,
    `min_detectors`, the `anomaly_window` + `min_anomaly_share` pair,
    mentions, `dashboard_url`), and `ai_context`. The boot payload carries a
    new `form_meta` (channel **names and types only** — never configs or
    secrets — plus profile names and the default profile), built by
    `build_form_meta()` in `ui/server.py`.
  - **Nothing modeled is lost.** Config keys the form doesn't render
    (`autotune:`, `tables:`, a custom `template`, an unrecognized detector
    param like `smoothing`, an unlisted detector type like `prophet`, a
    multi-entry `alerting` list) round-trip verbatim and are listed in a
    "Preserved fields" section. Saving from the **Builder** re-emits the whole
    YAML — hand-written comments are dropped (the previous file is still
    archived to `metrics/.history/<metric>/` first, exactly like a `dtk tune`
    Apply); saving from the **YAML** tab writes the text verbatim, unchanged
    from before. Edit mode opens on Builder when the file parses; a file
    hand-edited into a broken state opens YAML-only, with the parse error on
    the disabled Builder tab. `GET /api/metric-source` now also returns the
    parsed mapping (`data`) and `parse_error` alongside the raw text.
  - **The full create-to-tune loop is now one flow.** After creating a metric,
    a next-steps strip offers **Load & detect**, which spawns
    `dtk run --steps load,detect` for just that metric (deliberately no
    `alert` step, so a rough starter config can't spam a real channel); once
    that job succeeds, **Open tune** unlocks and opens the `dtk tune` cockpit
    on the freshly loaded series — create with rough defaults, load real
    data, then tune the detector against it.
  - New backend seams: `metric_files.parse_metric_mapping()` (validated
    config plus the raw unwrapped mapping), `semantic.parse_osi_models(text)`
    (the text-in seam `load_osi_models` now delegates to, so the server can
    parse a pasted model with no temp file), and `build_form_meta()`. The new
    routes are token-guarded like every other `dtk ui` route. Committed bundle
    `detectkit/ui/assets/ui.js` regenerated.

## [0.54.0] - 2026-07-11

### Added
- **`loading_delay` — data-maturity delay for late upstream ETL** (per-metric
  + project-wide default). When the source table (e.g. a dbt model) finishes
  writing minutes *after* an interval closes, a `dtk run` scheduled right
  after the boundary used to load the still-partial bucket — and because load
  resumes strictly after the last persisted timestamp, that wrong value stayed
  in `_dtk_datapoints` forever, feeding false "drop"/no-data alerts and
  skewing every later trailing window. With `loading_delay: "10min"` the
  loader treats `[t, t+interval)` as complete only once
  `now >= t + interval + loading_delay` (the delay is subtracted **before**
  the interval snap, so a delay that isn't a multiple of the interval still
  lands the bound on the metric's grid), and the alert step's
  `get_last_complete_point` shifts in lockstep — no false no-data alert for
  the deliberately-withheld newest interval (previously the no-data check
  floored wall-clock time with no notion of maturity, so a lagged metric
  would have mis-fired every cooldown cycle). Resolution: metric → project →
  0; a per-metric `loading_delay: 0` opts out of the project default. An
  explicit `dtk run --to` is trusted verbatim (no delay applied). Anomaly /
  recovery message timestamps are data-time and stay correct by construction;
  new **opt-in** template variables `{data_delay_display}` /
  `{data_delay_line}` let a custom template disclose the delay (default
  rendering is byte-identical). The `dtk ui` overview nets the resolved delay
  out of `lag_seconds`, so a delayed metric no longer reads as perpetually
  stale (freshness dot + "Stale metrics" tile; the hover title shows the
  excluded delay). Trade-offs (documented): every second of delay adds the
  same to real-outage detection latency — size it to the upstream job's
  observed worst case; an upstream run that overshoots the delay can still
  persist a partial bucket — repair with `dtk run --from <date>`, which
  re-loads and overwrites via the version-aware upsert. Deliberately **not**
  added as a `_dtk_metrics` column (no schema-migration mechanism exists;
  the informational table keeps its schema).

## [0.53.3] - 2026-07-10

### Added
- **Playground: `autoreg` + `manual_bounds` in the detector switcher** (issue
  #105; website-only). The interactive playground now exposes all five shipped
  detector types, closing the gap the v0.53.1 notes tracked: `autoreg` gains a
  **lags** slider and hides the windowed-only knobs (weighting, detrend,
  smoothing, seasonality grouping), exactly like the `dtk tune` cockpit;
  `manual` swaps in **lower/upper bound** sliders ranged over the data domain
  and seeded at the series p5/p95 (re-seeded when the data-shaping controls
  change). Two new synth pieces tell the prediction-based story: a **`pulse`
  rhythm** — a free-running ~7 h cycle that deliberately doesn't align with
  the calendar, so hour/day-of-week conditioning can't capture it — and a
  **`pattern break` incident** that freezes the value mid-rhythm: normal in
  level, wrong in shape. On the page defaults (medium noise, hourly grid)
  autoreg catches the frozen span and fires the alert preview while
  hour-conditioned `mad` sees nothing — the "normal in absolute terms, wrong
  for the shape" showcase. The playground's series-grow heuristic now sizes
  the regenerated series from the **un-clamped** warm-up requirement, so a
  warm-up larger than the interval's base length (autoreg on the 1d grid) no
  longer leaves the whole chart in the warm-up dimming. Landing teaser
  sub-line updated in lockstep (`mad / zscore / iqr / autoreg / manual`).

### Changed
- **Split the tune-cockpit renderer into focused modules** (issue #109; no
  behavior change). `website/src/scripts/report/tune.ts` (~2.6K lines) now
  keeps only the composition root; the payload/contract types, the DOM control
  builders (`segControl`/`rangeControl`), the config-text serialization, the
  formatters, the injected styles, the detector-worker client (blob spawn /
  kill-in-flight / 130 ms debounce) and the quality-metrics block
  (recall/FDR/reviewed) live in `website/src/scripts/report/tune/` — the same
  package shape as `ui/`. The tune.ts ⇄ tune.worker.ts message contract is now
  one shared `protocol.ts` imported by both sides instead of two hand-synced
  copies. `detectkit/tuning/assets/tune.js` regenerated from the split
  sources; verified behavior-identical (the parity + tune-worker gates pass,
  and a headless render of the same payload is pixel-identical to the
  pre-split bundle across tune/review/label/autotune mode switches and a
  threshold recompute).

## [0.53.2] - 2026-07-10

### Fixed
- **`dtk tune`: the cockpit now explains an all-warm-up view instead of
  silently going blank.** With `stabilization: clamp` the detector needs an
  extra full window of warm-up before its band matches what an incremental
  pipeline run would compute (autoreg: `2·window_size + lags` — e.g. 405
  points at the default `window_size: 200`), and the chart deliberately hides
  the band/dots over that lead-in. But when the warm-up swallowed the *whole*
  view (a low **Points shown** trim, or a raised window), the chart clipped
  away every band segment and anomaly dot **and** skipped the warm-up
  dimming/label too — a bare metric line with no cue, reading as "the band
  disappeared". Now: (a) the chart dims the whole plot with a centered
  *"all shown points are detector warm-up — nothing to score yet"* label;
  (b) the cockpit shows an inline warning with the **un-clamped** requirement
  and concrete fixes ("needs 405 pts (window 200 + lags 5 + window 200 for
  stabilization) … raise Points shown above 405, or lower the Window size, or
  turn Stabilization off") — the worker now reports that true requirement
  (the HUD's `warm-up N pts` previously showed a value clamped to the shown
  length, so it could read "warm-up 400 pts" while showing 400); (c) the
  window slider's explore cap is clamp-aware for autoreg (a third of the
  shown points instead of half, recomputed on trim/type switch), so the
  "always a scored region" invariant holds under the doubled warm-up. The
  band itself is *computed* for every scored point regardless — the real
  pipeline and `dtk run --report` always show it; the clip is display-only
  parity with what a fresh incremental run could reproduce.
- **`dtk tune`: the windowed detectors' preview now honors the clamp warm-up
  too.** Python's `WindowedStatDetector.get_context_size()` has always added
  an extra `window_size` of warm-up under `stabilization: clamp` (v0.51.0),
  but the TS port's effective-start estimate never did — so the cockpit (and
  the band's visible start) treated clamp asymmetrically: honest for autoreg,
  optimistic for mad/zscore/iqr, showing an early-window clamp band a real
  incremental run wouldn't reproduce. The windowed branch now carries the
  same `+window_size` term (display-only; detection math and the parity gate
  are untouched — the landing playground never sets stabilization).
- **`dtk tune`: a bare `type: autoreg` config now opens the cockpit at
  autoreg's real default window (200).** The seed previously fell back to the
  windowed template's `window_size` default (100) for every type, so the
  preview ran a different window than the next `dtk run` would.
- **`benchmarks/README.md`: recorded the MEDIFF decline rationale** (the
  Yandex-article follow-ups' one undocumented decision): the windowed
  detectors' per-group seasonality multipliers already provide the
  conditioned-baseline mechanism, so a MEDIFF port would duplicate an
  existing autotunable feature.

## [0.53.1] - 2026-07-10

### Changed
- **Landing-page refresh — the marketing site catches up with v0.51–0.53**
  (website-only; no library behavior changes — this release stamps the
  refresh). The detectors showcase gains a fifth `autoreg` tab (a patterned
  wave whose anomaly sits mid-range — normal in absolute terms, outside the
  AR forecast corridor `ŷ ± 3 × σ_residual`) and a stabilization footnote;
  the hero "Works with" strip gains an "Alerts to" row of channel badges
  (Slack / Mattermost / Telegram / Email / Webhook — the webhook channel was
  previously absent from the landing entirely); the labeling teaser becomes a
  full `dtk tune` cockpit showcase (Tune / Review / Label / Autotune mode
  switch, live catch-rate / false-alert / reviewed HUD, knob rail with
  Apply). Accuracy fixes from a section-by-section audit: the `dtk run` mock
  output regains the second blank line before `┌─ LOAD`; the alert previews
  now share the hero YAML's scenario (5min interval, `direction=up`,
  consistent onset/fired/recovered timestamps) instead of a conflicting
  10min/`direction=same` variant; the alerting section names the v0.52
  fraction rule (`anomaly_window` + `min_anomaly_share`) and the generic
  webhook channel; nav gains Playground, the footer gains the Tuning-cockpit
  and Project-UI guides. Exposing `autoreg`/`manual_bounds` in the
  interactive playground is tracked as #105.

## [0.53.0] - 2026-07-10

### Added
- **`autoreg` joins `dtk autotune` — per-type axis-spec seam (issue #97
  Phase 2).** The grid search no longer hardcodes the windowed detectors'
  axes: a small `AxisSpec` keyed by detector type
  (`detectkit/autotune/axis_spec.py`) declares which axes apply — the
  windowed types keep exactly the previous sweep (behavior-identical), while
  `autoreg` sweeps threshold / **lags** (new `TuneSettings.lags_grid`,
  default `(2, 3, 5, 8)`) / stabilization / window only, never receives
  `seasonality_components` (v1 rejects them), and its `min_samples` floor
  tracks `lags + 2`. `detector_select` now ranks `autoreg` too (an advisory
  suitability vote — ordering only, never exclusion), so a supervised or
  unsupervised tune can genuinely pick the prediction-based detector when
  cross-validation says it wins.
- **`autoreg` is tunable in the `dtk tune` cockpit (issue #97 Phase 3).**
  The parity-checked TS detector port gains a `runAutoreg` branch —
  centered/scaled AR fit, strict NaN lag policy, default-on clamp
  stabilization with the same capped substitution as the Python detector —
  so the cockpit recomputes the autoreg band live. The picker offers
  **Autoreg** with a **Lags** knob (windowed-only knobs hide; seasonality /
  weighting / detrend / smoothing don't apply), Apply writes a valid autoreg
  block back (explicit `min_samples`; turning stabilization off lands as an
  explicit `null` — an absent key means default-on), and the server-side
  Autotune mode re-seeds the autoreg knobs like any other winner. Golden
  parity fixtures cover base / NaN-gap / changes-input / ~1e9-magnitude
  autoreg runs.
- **Fraction alert window in autotune + the tune cockpit (issue #101, the
  v0.52.0 follow-up).** Supervised `dtk autotune` now runs a 2-D
  (window × share) sweep of the fraction rule **OR-ed with the chosen
  consecutive rule** — scoring exactly the composite the pipeline deploys —
  and adopts the pair only on a strictly greater score, so existing tunes
  are byte-stable when the fraction rule doesn't help. The tuned config
  emits `anomaly_window` as an exact-seconds duration (lossless grid-points
  round-trip) + `min_anomaly_share`; both ride the decision log, the RESULT
  echo and the cockpit reseed. The `dtk tune` cockpit gains always-visible
  **Alert: anomaly window** / **min share** rail controls (off state = the
  legacy consecutive-only rule): the worker replays the share rule with
  pipeline semantics (latest-point gate, missing slots in the denominator
  only, fires OR-merged with the consecutive rule and deduped per point),
  the recall/FDR bar scores the merged fires, and Apply writes the pair into
  the first alerting block (or removes both — never a half-pair). A new
  `npm run check:tune-worker` behavior gate locks the worker semantics.
- **First published NAB numbers in `benchmarks/README.md`** (58 series,
  event_f1_best): `zscore+clamp 0.244 > autoreg 0.235 > mad+clamp 0.234 >
  iqr+clamp 0.224` — stabilization improves every windowed detector on real
  data, and the hardened autoreg (below) is the best single un-stabilized
  detector.

### Fixed
- **`autoreg` numerical hardening (issue #97 Phase 0; measured on NAB).**
  On large-valued real series (~1e9) the AR normal equations mixed an
  intercept column of ones with lag columns of ~1e18 — a conditioning gap
  beyond float64 — producing garbage fits that the stabilization clamp then
  amplified into `inf`. Each fit window is now **centered/scaled** before
  the normal equations (affine-equivariant: same model, fixed conditioning)
  and the clamp substitution is **capped to the observed window range**, so
  a degenerate fit can never write an astronomic value into later history.
  `ALGORITHM_VERSION` bumps to 2 — autoreg detector ids change and
  detections recompute on the next run. Detection flags are now invariant
  under affine rescaling of the series (regression-tested), and the fix
  lifts autoreg's NAB event_f1_best from 0.203 to 0.235.
- **Autotune CV folds no longer under-reserve context.** The CV plan
  reserved only the raw max window; a stabilized detector needs an extra
  window of warm-up and autoreg needs `+ lags`, so folds silently scored
  points where `detect()` returns `insufficient_data`/`missing_lags`
  (degrading the CV signal without erroring). The plan now reserves the
  true worst-case context across every candidate type the search can build.

## [0.52.1] - 2026-07-10

### Fixed
- **Docs accuracy pass after v0.52.0** (no behavior changes). The new
  `autoreg` reference page is now actually published on the docs site (it was
  missing from the sync manifest and the sidebar); every detector enumeration
  across the docs (index, installation, See-Also lists, visualization guide)
  includes `autoreg`; installation.md no longer claims only
  mad/zscore/iqr/manual_bounds exist. The shipped `dtk init-claude` assets are
  corrected: the assistant overview rule now lists `autoreg` and the fraction
  alert rule, and the alerting rule's template-variable table no longer
  describes the pre-release recovery-chip behavior (a share-configured
  metric's recovery echoes the same combined rule chip as the firing alert).
  The benchmarks README no longer calls `autoreg` "planned".

## [0.52.0] - 2026-07-10

### Added
- **Fraction-based alert window — `anomaly_window` + `min_anomaly_share` on
  `alerting:` blocks.** A new, opt-in rule pair OR-ed with
  `consecutive_anomalies`: the alert also fires when the share of points
  meeting the direction-aware quorum over a trailing window (e.g. "30min",
  resolved to grid points via the metric interval; must span at least 2
  intervals) reaches the threshold
  (e.g. `0.3` = 30%) **and** the latest point itself meets the quorum — so a
  flapping incident whose single normal points keep breaking the consecutive
  chain still alerts, while a stale window whose newest point is already
  clean never does. Missing/no-data grid slots count in the denominator only
  (an outage makes the rule *harder* to fire; the no-data alert covers
  outages). Recovery (with `notify_on_recovery`) gains hysteresis: besides a
  clean latest point, the window share must fall below **half** the firing
  threshold, so an alert can't flap around the boundary. The live path and
  `AlertOrchestrator.replay()` share one decision seam, so HTML reports and
  the `dtk ui` overview replay the rule automatically. Messages: share-fired
  alerts lead with the window story ("14 of the last 30 10min intervals were
  anomalous (47%) — at or above the 30% share threshold over 5h.") and the
  Rule chip now renders through a shared `{rule_display}` template variable —
  consecutive-only configs render **byte-identically** to before and keep
  their `alert_config_id` (the new fields join the hash only when set).
  Adapted from Yandex's Monium/Taxi write-up, where the anomaly window was
  the single most effective false-positive fix
  (https://habr.com/ru/companies/yandex/articles/1035520/). The `dtk tune`
  cockpit and autotune's alert-window sweep still tune
  `consecutive_anomalies` only — fraction-rule support there is a tracked
  follow-up.
- **`event_f1` — segment-aware (point-adjusted) autotune scoring metric.**
  The engine's pointwise metrics punish a detector that flags 1 of 50 points
  inside a long labeled incident with 49 false negatives, even though for
  alerting purposes that incident was *caught* — so autotune could prefer
  configs the `dtk tune` cockpit's incident-overlap recall/FDR bar rates
  worse. `event_f1` counts contiguous labeled runs as single incidents
  (Revised-Point-Adjusted convention: ≥1 flagged point inside → 1 TP, none →
  1 FN, flags outside any incident → pointwise FPs), aligning the engine
  with the alert pipeline and the cockpit. Opt-in via
  `autotune.scoring_metric: event_f1` or `dtk autotune --scoring event_f1`;
  MCC stays the default. Segments are recomputed fold-locally in
  cross-validation, and incidents the detector could not score anywhere (no
  confidence band) are excluded rather than counted missed; the supervised
  `consecutive_anomalies` sweep honors the metric too.
- **`autoreg` — a prediction-based autoregression detector with built-in
  stabilization (Phase 1).** detectkit's first dynamics detector: per point
  it fits AR(`lags`) on a trailing `window_size` window via numpy-only
  normal equations, predicts ŷ from the previous `lags` values and flags
  `|y − ŷ| > threshold·σ_r`, with the natural band `ŷ ± threshold·σ_r` — so
  it catches "the value is normal in absolute terms but wrong given the last
  few points" (shape anomalies) and adapts fast on non-seasonal metrics.
  `stabilization: clamp` is **on by default** (the article's key novation):
  flagged points enter later fits clamped to the violated bound — clamping
  rather than substituting the prediction itself, because zero-residual
  substitution collapses σ_r and cascades into false flags (the same
  center-substitution failure measured and rejected for the windowed
  detectors in v0.51.0). Deliberately its own `BaseDetector` subclass (the
  windowed template's NaN-gap window splicing would fabricate lag pairs);
  v1 scope: no seasonality/smoothing/weighting, strict NaN policy (a gap in
  the lag view yields no score rather than an imputed one). Not autotunable
  yet (Phase 2); rides read-only in the `dtk tune` cockpit like
  prophet/timesfm and is preserved verbatim on Apply. Registered as
  `type: autoreg`; every result-affecting param is hashed into
  `detector_id` as usual.
- **`benchmarks/` — an offline public-dataset benchmark harness (dev
  tooling, not shipped in the wheel).** Runs the real detectors
  (`DetectorFactory`) over NAB (downloader included), Yahoo S5
  (license-gated, user-supplied directory) and a deterministic synthetic
  suite; scores F1-best / AUC-PR / point-adjusted (event) F1 per detector
  variant (mad/zscore/iqr ± `stabilization: clamp`, `autoreg`) and emits
  markdown + JSON result tables. Includes a benchmark-local pure-numpy
  **spectral residual** implementation (Ren et al., KDD 2019) evaluated
  *before* any decision to ship it in the library — on the synthetic suite
  it trails the windowed detectors on event-F1/AUC-PR, supporting the
  measure-first gate. First measured numbers: `stabilization: clamp`
  improves every windowed detector's event-F1-best / AUC-PR on the synthetic
  suite (e.g. mad 0.617→0.636 event-F1-best, 0.624→0.696 AUC-PR).

### Changed
- The alert-rule chip on every channel (webhook/Slack/Mattermost, Telegram,
  email, plain-text templates) is now built from the single shared
  `{rule_display}` context variable instead of three hardcoded placeholders.
  Consecutive-only configs render byte-identically; share-configured configs
  name both OR-ed rules; share-fired alerts lead with the share rule.
  Custom templates gain `{rule_display}`, `{window_points}` and
  `{window_matched}`.

## [0.51.0] - 2026-07-10

### Added
- **A new `stabilization: clamp` param on the windowed statistical detectors
  (mad / zscore / iqr) stops a sustained incident from poisoning its own
  baseline.** Without it, the anomalous points a long incident produces enter
  the trailing window and inflate the spread while dragging the center toward
  the incident, so the band widens and the detector stops flagging the
  incident's own tail — "the incident becomes the new normal." Z-Score
  (mean/std) is the most vulnerable: on a synthetic 30-point incident inside a
  100-point window it flags only ~10/30 points without stabilization and
  30/30 with it; MAD/IQR (median/quartile-based) resist short incidents but a
  long one still bends them (IQR: 25/30 → 30/30). Enabling it makes a flagged
  point's substitute in *later* windows a **clamp** to the confidence bound it
  violated (a winsorized value) rather than the observed value — the scored
  and persisted value is unchanged, only the statistics windows (global and
  per-seasonality-group) read the substituted history. Clamping was chosen
  over substituting the band center specifically because feeding
  zero-deviation points back into the spread statistics collapses the band
  after a long incident and cascades into false flags once the incident ends
  (measured: 34-44 false flags for MAD/IQR with center-substitution vs. 0 with
  clamp) — clamping bounds an anomaly's influence at exactly the threshold
  without destroying the spread estimate. It composes with detrend, recency
  weighting (`window_weights`/`half_life` — where it matters most, since
  recency weighting gives an ongoing incident's points *more* weight),
  smoothing, `input_type` and seasonality groups. The idea is adapted from
  Yandex's production anomaly-detection write-up on Monium/Taxi
  (`autoreg_stable`; see
  https://habr.com/ru/companies/yandex/articles/1035520/). The param is
  **opt-in and hashed into `detector_id` like every result-affecting param**,
  so enabling it produces a new id and detections recompute under it on the
  next run, while existing configs that don't set it keep their ids and
  recompute nothing. `get_context_size()` adds one extra `window_size` of
  warm-up history when it's enabled, so incremental batches reproduce the
  same substitution history a continuous run would see. The `dtk tune`
  cockpit gains a **Stabilization** control (none / clamp) alongside the
  other windowed knobs, seeded from and written back to the metric YAML the
  same way as every other detector param, backed by the parity-checked TS
  detector port; `dtk autotune`'s grid search gained a stabilization axis,
  swept after detrend and before window size and adopted only when it clears
  the same score-margin bar as `window_weights`/detrend.

## [0.50.0] - 2026-07-09

### Added
- **`dtk ui` now manages metric configs — create, edit and delete metric
  YAMLs from the browser, full cycle.** The cockpit header gains a **New
  metric** button (an editor overlay seeded with a starter template, plus an
  optional subfolder under `metrics/`) and every row gains an **Edit** action
  that opens the metric's raw YAML in the same editor. Save validates
  server-side **before any write** — YAML syntax → full `MetricConfig`
  validation → deep detector-params check (each factory-known detector is
  actually constructed) — and an invalid config lands in the editor's error
  pane with nothing written. Edits **archive the previous file verbatim** to
  `metrics/.history/<metric>/` (the same archive `dtk tune`'s Apply writes,
  excluded from metric discovery) and then overwrite in place, so the text
  you typed is what lands on disk, comments intact (normalized only to end
  with a newline). Saves are **conflict-checked** via an
  optimistic-concurrency digest: an editor opened before a `dtk tune` Apply
  or another tab's save is refused with a clear message instead of silently
  overwriting the newer config. **Delete** sits
  behind an explicit confirmation step in the editor — and the server
  additionally requires the request to echo the metric name — then archives
  the file (`…-deleted.yml`) before removing it, so a delete is reversible by
  hand. Renames are allowed (name uniqueness is enforced project-wide);
  rows under an old or deleted name stay in the `_dtk_*` tables until
  `dtk clean`. While a `dtk tune` session for a metric is running, Save and
  Delete for that metric are refused (its Apply would race the edit).
  New token-guarded routes: `GET /api/metrics`, `GET /api/metric-source/<name>`,
  `POST /api/metric-create`, `POST /api/metric/<name>/update`,
  `POST /api/metric/<name>/delete`; the mutation seam is the new
  `detectkit/ui/metric_files.py`. `dtk ui` still takes no pipeline lock and
  the CRUD routes never touch the database — they only manage metric YAML
  files.

### Changed
- **The metric-YAML seams are shared, not parallel** (`config/metric_io.py`):
  the `metrics/.history/<metric>/` archive convention (now **collision-safe
  within one UTC second** — a `dtk tune` Apply and a UI save landing together
  keep both snapshots; previously the tune Apply could silently overwrite
  one), the nested `metric: {...}` unwrap, and the sanitized filename stem are
  one implementation used by `MetricConfig.from_yaml_file`, `dtk tune`'s
  write-back and the `dtk ui` editor alike.
- **Cockpit overlays trap keyboard focus** (shared `overlay.ts` chrome for
  the detail report and the metric editor): Tab can no longer walk onto the
  covered page's buttons and fire them blind, and programmatic navigation
  away from a dirty editor goes through the same discard-confirm as
  Esc/backdrop/close.
- **Saving an in-place metric edit refreshes only that row** — the overview
  no longer flashes every metric back to pending and re-fetches the whole
  project's stats after a one-line YAML change (create/rename/delete still
  reload the list, whose shape actually changed).

### Documentation
- The CLI reference's overview command listing now includes `dtk ui` and
  `dtk osi` (both were missing since their releases), the Project UI guide is
  indexed in the docs table of contents, the quickstart's next steps point at
  `dtk ui`, and the tuning/autotuning guides link back to the Project UI
  guide. The `dtk init-claude` assistant assets document the new metric
  management (and `rules/overview.md` now mentions `dtk ui` alongside HTML
  reports), so a freshly-run `dtk init-claude` teaches the assistant the full
  cockpit. The website landing gains a `dtk ui` showcase section.

## [0.49.2] - 2026-07-09

### Fixed
- **Alert replay is now linear — a wide report window builds in under a
  second instead of minutes.** `AlertOrchestrator.replay` rebuilt its causal
  view (a dict comprehension + a full re-sort of every timestamp) **per grid
  point** — O(n² log n). A 30-day window of a 1-minute metric (43k points)
  took upwards of half an hour to build, which surfaced as `dtk ui`'s detail
  view hanging on a white screen; the same cost applied to `dtk run --report`
  over wide `--from` windows and autotune's alert-window sweep. The causal
  view is now maintained incrementally across the walk (one up-front sort,
  O(1) admission per step): 43k points now replay in ~0.8s (measured ~80×
  faster at 3k points). Semantics unchanged — same events, verified by the
  existing replay/report/overview suites.
- **The detail overlay shows a loading state while the report builds.** The
  iframe used to be a blank white pane until the server-side report landed —
  it now stays hidden behind a spinner ("Building the report for <metric>…")
  until its document loads, so build time no longer reads as "nothing is
  happening".
- `dtk ui` now echoes non-403 request errors (e.g. a 400 from a failing
  report build) to the terminal as one compact line, so a stuck page is
  diagnosable without opening the browser's devtools.

## [0.49.1] - 2026-07-09

### Fixed
- **`dtk ui` overview no longer hangs (or over-counts) on a production
  project.** Two compounding causes:
  - The stats read pulled **every historical detector generation's rows**:
    each retune/autotune changes a detector's identity and the superseded
    ids' rows stay in `_dtk_detections` forever, so a heavily-tuned metric's
    window read returned N× the rows — and the alert replay mixed live and
    dead configs into one quorum, inflating alert counts a real `dtk run`
    would never have produced. The overview now derives the **currently
    configured** detector ids exactly the way the detect step does and reads
    only those; the counts answer "how does the metric behave as configured
    today". (The per-metric report keeps its "what actually ran" semantics.)
  - The page fetched one monolithic `/api/overview` computing all metrics in
    a single request — minutes on a real project, which the browser aborts
    ("Failed to fetch") while the page shows an endless spinner. The overview
    now loads **incrementally**: the table renders instantly from the metric
    list and each row's stats stream in via per-metric `GET /api/stats/<name>`
    (an `n/N` progress chip while loading); one slow or failing metric marks
    its own row instead of sinking the page. `/api/overview` remains for
    programmatic use.
- **Quiet shutdown.** Ctrl-C (or a browser aborting a slow request) no longer
  dumps handler-thread tracebacks into the terminal: client disconnects are
  swallowed, other request errors echo as one compact line, and the command
  prints a clean "Stopping… / Stopped." while terminating any jobs the UI
  spawned.

## [0.49.0] - 2026-07-09

### Fixed
- **Timestamp cursor reads now always return naive UTC.** On ClickHouse the
  driver hands back the last/first datapoint (and last detection) timestamps
  as *timezone-aware* datetimes, while everything in-memory in detectkit is
  naive UTC — any code doing arithmetic between the two raised
  ``TypeError: can't subtract offset-naive and offset-aware datetimes``. The
  pipeline defended itself at each call site, but newer read paths (the
  `dtk ui` overview, a report window pinned with an explicit start) hit the
  mix. The normalization now happens once, at the shared reader seam
  (`_normalize_max_timestamp`), so every consumer gets the documented
  naive-UTC convention.
- **`dtk run --report` / `dtk autotune --report` pages failed to render** since
  the y = 0 toggle shipped: the report chart read the toggle's `let showZero`
  binding before its declaration ran (a temporal-dead-zone `ReferenceError` in
  the bundled renderer), so every report page showed "Failed to render report:
  ReferenceError …" instead of the chart. The declaration now precedes the
  first value-domain computation and the committed `report.js` bundle is
  regenerated. Found by the new `dtk ui` end-to-end check, which embeds the
  same report page in its detail view.

### Added
- **`dtk ui` — a project-level monitoring cockpit.** One CLI command serves an
  interactive localhost page over the already-persisted `_dtk_*` tables for the
  **whole project**: every metric — grouped by its `metrics/` folder, filterable
  by tag — with alert-frequency stats over a selectable window (24h / 7d / 30d /
  90d / all): alerts in window and per-day rate, last alert, no-data events,
  anomaly rate, data freshness, and a sparkline. Alert counts are **replayed**
  from the stored detections through the same pure replay seam as
  `dtk run --report`, so the numbers match what the pipeline would actually have
  alerted — no event log is required. Labeling stays optional: when
  `incidents/<metric>/` labels exist (from `dtk tune`), per-metric **recall /
  false-alert rate / reviewed** chips appear (matched on streak-span overlap,
  with the `false_alert_budget` flagging an over-budget metric); without labels
  the overview still quantifies "how often do alerts come" and the user can eyeball
  each metric's chart. Clicking a metric opens the existing self-contained HTML
  report in an overlay (same renderer as `dtk run --report`). A **pipeline
  panel** drives the real CLI commands as subprocesses — `dtk run` (select,
  steps, from/to, force, full-refresh), `dtk autotune`, `dtk unlock` — streaming
  their terminal output live into the page (one pipeline job at a time); a
  **Tune** button launches `dtk tune` for the metric and opens its cockpit in a
  new tab. The UI server itself takes **no pipeline lock** and never mutates
  anything — spawned commands behave exactly as if run from the terminal
  (locking included). Flags: `-s/--select` (default `*`), `--window` (initial
  preset, default `30d`), `--profile` (also forwarded to spawned commands),
  `--no-open`. The server binds to `127.0.0.1` with a per-session token checked
  on every route. Ships a committed `detectkit/ui/assets/ui.js` renderer bundle
  (built by `website/scripts/gen-ui-bundle.mjs`, same generated-asset pattern as
  the report/tune bundles).

## [0.48.0] - 2026-07-01

### Fixed
- **`dtk tune` no longer silently drops a metric's other detectors on Apply.**
  Previously **Apply** overwrote a metric's entire `detectors:` list with the
  single detector shown in the cockpit — so a metric configured with, say, a `mad`
  pattern detector **plus** a `manual_bounds` hard floor (the documented robust
  combo) lost all but one after a routine retune. When the alert used
  `min_detectors >= 2`, the quorum became permanently unsatisfiable and the alert
  silently stopped firing. Write-back now **merges**: each tuned detector rewrites
  only its own slot and every detector the cockpit didn't touch — a `manual_bounds`
  floor, a `prophet`/`timesfm` detector, another windowed detector — is preserved
  **verbatim** (including execution params like `start_time` / `batch_size` on the
  edited detector). The re-emitted YAML header names what was updated vs preserved
  instead of the old, misleading "Only the detector block … was changed".
- **`metrics/.history/` archives are no longer discovered as live metrics.**
  `dtk tune` archives the previous metric config under `metrics/.history/<metric>/`
  before writing the tuned version in place. Those snapshots keep the original
  `name:`, and metric discovery globbed them (Python's `pathlib` glob traverses
  hidden directories, unlike shell globbing) — so `dtk run` / `dtk autotune` /
  `dtk clean` failed with `Duplicate metric name '<x>' found` after any metric had
  been tuned. Discovery now skips any hidden path component under `metrics/` (the
  `.history` archive and any editor/VCS scratch dir), across every selection path
  (`select_metrics`, tag/name search, and project validation). Autotune's
  top-level `<metric>__tuned_<id>.yml` files are unaffected.

### Added
- **Detector picker in the `dtk tune` cockpit (multi-detector metrics).** When a
  metric configures more than one detector, the Tune rail shows a **Tuning
  detector** picker to choose which one to tune (the cockpit shows one band at a
  time); switching re-seeds every knob from that detector's config, and **Apply**
  writes back every detector you tuned while preserving the rest. Non-tunable
  detectors (`prophet`/`timesfm`) and the ones you didn't touch are listed as
  "preserved on Apply". Single-detector metrics are unchanged (no picker).

### Changed
- **`dtk tune` recompute is snappier.** The live band now recomputes when a slider
  is **released** (not on every mid-drag pause while the mouse button is still
  held), and an in-flight recompute is **cancelled** when a new one is requested —
  previously the worker ran the now-stale config to completion (O(points × window),
  seconds on a large window) before starting the new one, so a fresh config waited
  behind it. The value echo still updates live while dragging.

## [0.47.0] - 2026-07-01

### Added
- **OSI-compatible `ai_context` on a metric (grounding for humans + AI).** A new
  optional `ai_context:` block on a metric mirrors the
  [Open Semantic Interchange](https://github.com/open-semantic-interchange/OSI)
  `ai_context` shape verbatim — `instructions` (business meaning), `synonyms`
  (alternative names), `examples` — so a metric's meaning is portable to and from
  an OSI semantic model. It accepts the full mapping **or** a bare string
  (lifted to `instructions`):

  ```yaml
  ai_context:
    instructions: "Revenue recognized at order completion, net of refunds (UTC)."
    synonyms: ["total revenue", "gross sales"]
  ```

  It is **purely descriptive**: it never affects load/detect/alert or the
  `detector_id`, and — importantly — it **does not change any default-rendered
  alert message**. The metric's `synonyms` are exposed to alert templates as the
  **opt-in** `{synonyms}` / `{synonyms_line}` variables (so a custom `template`
  can add an "Also known as: …" line), and the whole block is baked into the
  `dtk tune` cockpit payload as read-only grounding. A metric with no
  `ai_context` behaves exactly as before. This is the first, additive step of
  detectkit's OSI support (grounding); it adds no runtime dependency on OSI.
- **`dtk osi` — import/export between OSI models and detectkit metrics.** A new,
  fully isolated command group (the `detectkit/semantic/` package; nothing in
  load/detect/alert imports it, so it can't affect a running project):
  - `dtk osi import <model.osi.yml> --metric <name> --interval <grain>` — the
    "enhanced init": resolve a metric from a governed OSI model and **scaffold a
    normal native detectkit metric** (SQL query, interval, a starter detector,
    the metric's `ai_context` carried over). Two targets: `--target clickhouse`
    compiles a direct `toStartOfInterval(...) GROUP BY` query from the dataset's
    physical `source` (ANSI→ClickHouse via the optional **sqlglot** dependency);
    `--target cube` compiles a Cube **SQL-API** query (`MEASURE(...)`) so the
    metric runs through Cube and detectkit alerts on the **same governed number a
    Cube dashboard shows**. The output is reviewed and committed like any
    hand-written metric — no runtime dependency on OSI.
  - **Safe by allowlist, not best-effort.** Only provably per-bucket-additive
    shapes compile (`SUM`/`COUNT`/`COUNT(DISTINCT)`/`AVG`/`MIN`/`MAX` and ratios
    of them, e.g. `SUM(x)/NULLIF(COUNT(DISTINCT y),0)`); window functions,
    non-aggregate expressions and unsupported aggregates are **hard-refused** with
    a clear message pointing at `query_file:` — a wrong monitored series is worse
    than no integration.
  - `dtk osi compile` prints just the generated SQL for review; `dtk osi export`
    publishes detectkit metrics into an OSI fragment, carrying a lossless snapshot
    of the detect/alert config in a `custom_extensions[detectkit]` block (a JSON
    string, per the OSI spec) plus the metric's `ai_context` — a **one-way
    carrier** (`dtk osi import` does not reconstruct from it; the metric YAML stays
    the source of truth).
  - **Positioning.** OSI adoption is still early, so the immediately useful piece
    for most projects is `ai_context` (grounding on any metric, no OSI model or
    extra install needed); the `dtk osi` converters are a forward bridge for teams
    that already run a governed semantic layer (Cube, dbt MetricFlow, Snowflake…).
    The whole layer is isolated and additive — remove it and detectkit is unchanged.
  - sqlglot is an **optional** dependency — the `[osi]` extra
    (`pip install 'detectkit[osi]'`), needed only for the ClickHouse target. The
    core library and the rest of the CLI never import it.

## [0.46.0] - 2026-06-29

### Changed
- **Slack / Mattermost alerts are now one collapsible card, not two.** The
  v0.41.0 "fold the long tail" change split the webhook message into a **base
  card** plus a neutral **detail card** — but in practice that read as *two*
  blocks (the second with its own grey accent bar, looking like a separate,
  differently-colored alert), and the detail card's short `text` usually never
  reached the height that trips the platform fold, so nothing collapsed. The
  webhook message is now a **single status-colored attachment** whose whole body
  rides in one markdown `text` block, ordered **most-important-first** (lead +
  Rule → Value / Expected → the action **Links** line → then the verbose tail:
  Quorum / Severity / the anomalous span / Detectors / Parameters). Because Slack
  and Mattermost fold **only** an attachment's `text` (Mattermost wraps it in a
  200px `<ShowMore>`; the `title`, the color bar and the `footer` render
  *outside* the fold), a long anomaly now collapses its tail behind **"Show
  more"** as **one block with one color** — exactly like a reference AlertManager
  alert — while the essentials stay in view. No wording changed; no-data / error
  alerts stay short, single un-folded cards (a long anomaly, or a full recovery
  timeline, folds its tail). Webhook-only; no config.

### Fixed
- **The brand logo now stays visible when an alert is collapsed.** The branded
  footer + footer icon (the detectkit logo) ride on the single attachment, and
  since a chat client renders an attachment's footer *outside* the "Show more"
  text fold, the logo is now always visible at the bottom of the message — even
  when the body is collapsed. Previously it sat on the foldable second card.

## [0.45.1] - 2026-06-28

### Fixed
- **`dtk tune`: deleting an incident on the chart no longer "turns it into" a
  confirmed alert.** In **Label** mode, deleting a marked incident via the chart's
  ✕ handle (or the **Delete** key) removed the hand-marked span but left behind any
  confirmed-valid alert verdict it overlapped — so that verdict, which the
  Marked-incidents list had been hiding *behind* the incident (overlap-dedup),
  **resurfaced as its own "✓ confirmed alert" row**. The incident appeared to become
  a confirmed alert instead of being deleted, and the catch-rate/false-alert metrics
  stayed wrong. This bit hardest on **seeded** sessions: **Save** writes each
  confirmed alert as *both* an incident *and* an `alert_reviews:` entry, so on reopen
  every incident is backed by a verdict and *every* chart-✕ delete resurfaced one.
  Deleting an incident now also **retracts** any confirmed-valid verdict overlapping
  it (clearing it to un-reviewed, the same effect as the list's "un-confirm" ✕), so
  the incident is fully removed and the chart ✕ and list ✕ behave identically.
  Explicit *false-alarm* verdicts and confirmed alerts that don't overlap the deleted
  span are untouched; confirming alerts (Review mode, **Confirm all**) is unchanged.
  The committed `assets/tune.js` bundle is regenerated.

## [0.45.0] - 2026-06-28

### Added
- **`dtk init-claude` now ships a `dtk-tune` skill** so the user's AI assistant can
  actively *guide* metric configuration instead of only scaffolding files. The
  cockpit (`dtk tune`) is the hands-on **umbrella** for tuning — it contains the
  autotune engine (its **Autotune** mode), manual knobs, and Label/Review — but the
  assistant had no procedure for driving it: `dtk tune` was documented only in the
  `cli.md` reference and framed mainly as a labeling sub-step of `dtk-autotune`. The
  new skill walks the assistant through the full hands-on path: stand up a **sandbox**
  (scaffold a robust starter + load history), open the cockpit (with `--no-open` +
  shared URL on a remote machine), guide the user through the four modes —
  emphasising that **autotune is built in** and runs over the window shown — then
  safe **Apply** and the `dtk run` / `dtk clean` follow-up.

### Changed
- **The assistant now presents tuning as a hands-on-vs-automatic choice, with the
  interactive cockpit preferred when the user wants to be in the loop.** The
  shipped context (`CLAUDE.section.md`) and the `dtk-new-metric` / `dtk-autotune`
  skills are reworded so a scaffolded metric is framed as a **sandbox** the user
  refines, branching to **`dtk-tune`** (hands-on cockpit, autotune built in) or
  **`dtk-autotune`** (fully-automatic CLI search) — the same engine, picked by
  whether the user wants hands-on or hands-off. Previously `dtk-new-metric` handed
  off only to `dtk-autotune` and never mentioned the interactive cockpit.

### Documentation
- **Corrected stale skill lists in the user guides.** The installation, quickstart
  and `dtk init-claude` CLI reference pages (in `docs/` and the website mirror)
  still said detectkit ships **three** skills and omitted `dtk-autotune` entirely;
  they now list all **five** (`dtk-setup-project`, `dtk-new-metric`, `dtk-tune`,
  `dtk-autotune`, `dtk-feedback`). The landing page's `dtk init-claude` terminal
  block and "skills" prose are updated to match (now `13 created`).

### Documentation
- **`dtk init-claude` assistant context is now strictly user-perspective.** The
  AI-assistant docs shipped into a user's own project
  (`detectkit/cli/assets/claude/`) described some behaviors by naming the
  internal Python symbols that implement them — `BaseAlertChannel.build_context`,
  `ProjectConfig.resolve_alert_help_url`, `WebhookChannel` — which belong to the
  **library-development** role, not someone *using* detectkit. Those references
  are rephrased to the observable behavior + the YAML/CLI knobs a user actually
  controls. The overview also pointed at "the `docs/` directory in the repo" —
  which a pip-installed user does not have — and now points at the docs site and
  the changelog. The contributor-facing rules (`.claude/rules/architecture.md`,
  `contributing.md`) and the website's `development/` pages keep those internal
  symbols on purpose: that is where the central-development perspective belongs.
- **Removed hardcoded version markers from the user guides.** The guides and
  reference pages (in `docs/` and the website mirror) sprinkled `(v0.5.0)`,
  `Since v0.15.0`, `New in v0.5.0`, `since v0.16.1`, `pre-0.7.0` and a stale
  "prior to v0.5.0 this was broken" migration note through descriptions of
  **current** behavior. Those documents describe the installed version, so the
  inline version stamps were noise; the version history lives in this changelog.
  The behavior wording is unchanged — only the version markers were dropped.
  (Dependency constraints, the MySQL 8.0+ runtime requirement, and the
  `127.0.0.1` localhost references are not detectkit versions and were kept.)

## [0.44.0] - 2026-06-28

### Changed
- **`dtk tune` Autotune mode tunes on the window you're looking at, not the full
  history.** When you click **Run autotune** in the cockpit, the page now posts the
  window currently shown — the **Points shown** trim — and the server runs the engine
  over **exactly that slice**. Previously it reloaded the metric's full history, so
  the search optimized a different series than the one the cockpit displays and scores
  recall/FDR on — illogical when you've deliberately trimmed to a recent period. Trim
  **Points shown** to focus the search; what you see is now what's optimized. (An
  older page that posts no window still falls back to full history.)

### Added
- **The cockpit's Autotune mode streams a structured run-log to the terminal.** A
  user watching the terminal beside `dtk tune` now sees each **Run autotune** click as
  a clean, blocked log — a cyan banner (metric · window · ground truth · scoring) then
  the engine's `LABELS → SEASONALITY → DETECTOR SELECT → GRID SEARCH → WINDOW →
  RESULT` blocks — using the **same** renderer (`StageLogRenderer`, now shared in
  `cli/_output.py`) the `dtk autotune` command uses, so it matches `dtk run`'s
  load/detect/alert format. Previously the server-side run streamed nothing
  structured; the terminal showed only a wall of repeated detector warnings.

### Fixed
- **No more per-candidate warning flood during tuning.** The grid search builds dozens
  of throwaway candidate detectors, each of which emitted the windowed detectors'
  one-time "seasonality group can't fill this window → falls back to global" warning —
  flooding the terminal (in both `dtk autotune` and the cockpit's Autotune mode) and
  burying the decision log. The engine now quiets that per-candidate warning for the
  duration of a tune; the under-fill of the **chosen** seasonality is still surfaced
  as a structured `window` advisory in the decision log, and a real `dtk run` (which
  builds one detector and wants the warning) is unaffected.

## [0.43.0] - 2026-06-28

### Added
- **`dtk tune` gains an Autotune mode — run the autotune engine in the cockpit.**
  A fourth mode joins Tune / Review / Label: switch to **Autotune** and click
  **Run autotune**, and the **same** `dtk autotune` engine (seasonality → detector
  → grid → window search, cross-validated) runs **server-side** over the metric's
  full history — not a browser re-implementation — using the incidents you've marked
  (and confirmed-valid alerts) as ground truth. When it finishes it **re-seeds every
  knob** with the winning detector, recomputes the live band, and shows the winner,
  the score and the **decision log** in the rail. Review the band, then **Apply** in
  place (in Autotune or Tune mode). This completes folding autotune into the
  `dtk tune` cockpit (Phase 2 of the merge begun in 0.42.0): the loop is now
  **Label → Autotune → Tune → Apply**, all on one screen.
  - It honours the metric's `autotune:` config block (`scoring_metric`, `folds`,
    `detector_types`, `force_seasonality`, …), runs **supervised** when incidents are
    marked (also choosing `consecutive_anomalies`) else **unsupervised**, exactly
    like the CLI.
  - It is **advisory**: nothing is written until you **Apply**. Unlike
    `dtk autotune`, it does **not** persist a run record, emit a `__tuned_<id>.yml`,
    or write detections — so `dtk tune` keeps taking **no pipeline lock**. The
    re-seeded band is the TS approximation; the next `dtk run` recomputes detections
    under the applied config and is the source of truth. Reach for `dtk autotune`
    when you want the audited run + tuned file + persisted winner detections.
  - Served over a new repeatable `POST /autotune` localhost endpoint (token-guarded,
    keeps serving like `/labels`); unavailable under `--no-serve` (no live server)
    and refused for a metric with `autotune: { enabled: false }`.

### Changed
- **The autotune `AutoTuneConfig` → engine plumbing is factored into
  `detectkit/autotune/runner.py`** (`autotune_from_data`: cap history → resolve
  scoring → project ground truth → build settings → run engine), shared verbatim by
  the `dtk autotune` command and the new `dtk tune` Autotune mode. No behavior change
  to `dtk autotune`.

### Fixed
- **`dtk tune` server error responses no longer crash on a unicode message.** The
  localhost tuning server now returns the error detail in the (UTF-8) response body
  instead of the HTTP status line — a validation/engine message carrying a unicode
  dash or `≈` (e.g. the "no datapoints" hint, a pydantic error) previously raised a
  `UnicodeEncodeError` instead of a clean 400. Applies to the **Apply**, **Save
  incidents** and new **Autotune** endpoints.

## [0.42.0] - 2026-06-28

### Removed
- **The standalone `dtk autotune` incident labeler is retired — label in `dtk tune`
  instead.** The `dtk autotune --label` / `--no-serve` / `--no-open` flags and the
  local labeler server are gone, along with the `html_labeler.py` / `label_server.py`
  modules and the static `autotune-labeler.html` demo. Their entire feature set
  already lives in `dtk tune`: open `dtk tune --select <metric>`, use **Label** mode
  (drag spans, Threshold capture, Lasso the anomaly cloud) or **Review** mode (confirm
  fired alerts as incidents), then **Save incidents** — which writes versioned files
  into `incidents/<metric>/`, the same store autotune reads. This is the first step of
  folding autotune into the `dtk tune` cockpit.

### Added
- **`dtk autotune` auto-discovers labels in `incidents/<metric>/`.** After marking
  incidents in `dtk tune`, just run `dtk autotune --select <metric>` — it now picks up
  the newest labels file in `incidents/<metric>/` with no `--incidents` flag, so the
  retired one-command `--label` flow becomes a seamless two-command flow. Full
  precedence: `--incidents` flag > config `labels_file` > inline config `incidents` >
  auto-discovered `incidents/<metric>/` > interactive prompt > none (unsupervised).
  `--incidents` still accepts a file or a directory explicitly.

## [0.41.0] - 2026-06-28

### Changed
- **Slack / Mattermost alerts now fold their long tail behind "Show more".** Long
  anomaly notifications no longer fill the channel: the webhook message is split
  into an always-visible **base card** (the lead + Rule, **Value / Expected**, and
  a compact always-visible **Links** field — dashboard / extra links / "how to read
  this alert") and a neutral **detail card** carrying the verbose tail (Quorum /
  Severity / the anomalous span / Detectors / Parameters) as one markdown text
  block. Both Slack and Mattermost natively collapse only an attachment's *text*
  block (Slack above 700 characters / 5 line breaks; Mattermost above ~200px of
  height) and never the fields grid, so routing the bulk into the detail card lets
  the platform fold it behind a **"Show more"** toggle while the value, the expected
  band and the action links stay in view. No wording changed — same content, just a
  layout that collapses. No-data / error alerts stay a single card; the branded
  footer rides the last attachment; a custom `template` is unchanged (single
  text-only attachment). Telegram and email are unaffected (no native fold). This is
  webhook-only and needs no config.

### Added
- **`dtk tune`: confirmed alerts now show up as incidents, and an optional
  false-alert budget.** Two connected changes to the manual-tuning cockpit:
  - **Confirming an alert *is* marking an incident.** A **valid** alert (the green
    markers from Review mode) is now a first-class entry in the **Marked incidents**
    list — a "✓ confirmed alert" row you can focus or remove (removing it un-confirms
    the alert). The list, the live **recall / false-alert** metrics, and **Save
    incidents** all read one ground-truth set (hand-marked spans **plus**
    confirmed-valid alerts, deduped by overlap so neither is counted twice), so
    "validate the alerts" is simply a fast way to label incidents — no hand-drawn span
    needed, and what you confirmed is exactly what gets saved. Confirmed-valid spans
    are now derived from the **stored verdict** rather than the current fire, so a
    confirmed incident stays in the ground truth (and correctly registers as a recall
    *miss*) even if you then tune the detector so it no longer fires there. Fixes a
    latent double-count after a Save→reopen (the same incident was seeded as both an
    incident and a review).
  - **Optional false-alert-rate (FDR) budget.** New `false_alert_budget` config (a
    fraction in `(0, 1]`, e.g. `0.3` = 30%) on a **metric** (priority) and the
    **project** (default); unset → a built-in default of `0.5`. The quality bar
    flags — gently, non-intrusively — when your false-alert rate exceeds the budget
    (the "false alerts" chip turns and reads `▲ over 30% budget`). Labeling stays
    entirely optional and the budget never affects the load/detect/alert pipeline — it
    only colours an already-computed number, so you can ignore it or label a short
    window to put a number on your error. Regenerated `detectkit/tuning/assets/tune.js`.

## [0.39.2] - 2026-06-27

### Changed
- **`dtk tune` colour legend moved to the top, visible in every mode.** The chart
  colour key (alert markers — **red** fired / **green** confirmed valid / **slate**
  false alarm — plus anomaly dot, metric line, expected range and band centre) was
  in the stage footer below the chart, where it was easy to miss. It is now a pinned
  legend bar **directly under the HUD, above the chart**, leading with the three
  alert colours, so the marker colours are decoded almost immediately — and because
  it lives in the stage (not the mode-aware rail) it stays put across **Tune /
  Review / Label**. Regenerated `detectkit/tuning/assets/tune.js`.

## [0.39.1] - 2026-06-27

### Changed
- **`dtk tune` rail refinements.** The **"effective config" readout** in the rail
  footer is now **collapsed by default** (a one-line clickable header — click to
  expand) so the knob column gets more vertical room; it stays up to date while
  hidden, so it shows the current config the moment it's opened.
- **Controls that aren't detector-specific now stay visible in every mode** instead
  of only in Tune: the **Points shown** data-window trim at the top of the rail, and
  the alert rule (**Direction** — which way the alert fires — and **consecutive
  anomalies** — how many in a row) plus the **Show y = 0 line** view toggle at the
  bottom. They frame the band, the alerts you review, and the recall/FDR you watch
  while labeling, so they apply to all three modes; only the detector knobs / verdict
  actions / capture tools swap with the mode.

## [0.39.0] - 2026-06-27

### Changed
- **`dtk tune` cockpit reworked into a chart-windshield + a mode-aware control
  rail.** The controls no longer sit in a dock below the chart (where reaching a
  knob meant scrolling down, then scrolling back up to watch the band). Now the
  chart fills the screen as the windshield, the live **metrics ride pinned in a
  HUD over the chart** (the speedometer — always in view across every mode), and
  every control lives in an **always-visible side rail** beside the chart with its
  own scroll — so you turn a knob and watch the band change without scrolling or
  dropping your gaze. Collapse the rail (⟩) to hand the chart the whole width; a
  slim tab brings it back (the chart re-fits via a `ResizeObserver`).
- **The control rail is mode-aware** — it shows only the panel the current mode
  needs instead of every control at once: the detector knobs + the effective-config
  echo + **Apply** in **Tune**, the verdict actions in **Review**, and the
  **Threshold capture / Lasso anomalies** tools + the incident list + the **Save
  incidents** field in **Label** (previously the capture tools were easy to miss and
  the effective-config / Save controls hung around in every mode). The rail header
  renames to the active mode's panel.

## [0.38.0] - 2026-06-27

### Added
- **`dtk tune` is now a chart-first cockpit on ONE chart with three modes.** The
  detector and labeler charts are merged into a single windshield that fills the
  screen; every control lives in a collapsible **dock under the chart**, and the
  live metrics sit right beneath it (no more scrolling past the chart to reach the
  knobs). A **mode switch** drives which layers lead and which interactions are
  armed: **Tune** (the band leads; incidents recede to read-only context; hover a
  point for its window), **Review** (the fired alerts lead; the band ghosts), and
  **Label** (the band hides; incidents are editable; threshold/lasso capture
  armed). The non-active layers dim to context instead of competing for pixels, so
  one canvas does the job two stacked half-charts used to.
- **Validate fired alerts right on the chart.** Click an alert marker to cycle its
  verdict **un-reviewed (red) → valid (green) → false alarm (slate)** — on the one
  chart, in Tune or Review mode; **Confirm all unreviewed valid** does the lot. A
  confirmed alert is the user asserting a real incident happened there: it counts
  as caught (recall) and correct (FDR) — so a clean metric whose alerts are all
  good can be validated in a few clicks **without hand-drawing incident spans** —
  and it is **written as a normal incident on Save**, so confirming alerts also
  feeds the next supervised `dtk autotune`. The metrics bar gains a **reviewed
  N/M** chip. Verdicts persist as an `alert_reviews:` metadata block (re-bound to
  the moved alerts by streak-span overlap on reopen; autotune ignores the block).

### Changed
- The two synced `dtk tune` charts are replaced by the single mode-driven chart
  (less vertical budget, no cross-chart sync machinery). The shared chart engine
  gains a `mode` (`tune`/`review`/`label`) with a per-layer full/dim/hidden model;
  the landing playground (no `mode`/`labeling`) renders exactly as before.

## [0.37.0] - 2026-06-27

### Added
- **Lasso capture in the incident labelers — turn a cloud of anomalies into proper
  incidents in one gesture.** In `dtk tune`, the labeler chart now **mirrors the
  detector's anomaly dots**, and a new **Lasso anomalies** tool lets you draw a
  freeform loop around a cluster: each **run of consecutive anomalies** (small gaps
  bridged, up to your `consecutive_anomalies`) collapses into **one incident span**
  sized to the run — not a point — while a separate burst inside the loop becomes
  its own incident. This is the intended tuning loop: tighten the band, lasso the
  real anomalies it surfaces, watch the metrics update. The standalone autotune
  labeler (`dtk autotune --label`) gains the same **Lasso capture** over raw points
  (no detector there), grouping consecutive points into interval incidents.

### Fixed
- **`dtk tune` undercounted the incident catch rate (recall).** An incident was
  scored as *caught* only when an alert's single **fire timestamp** landed within
  ±½ interval of its span — but an alert fires `consecutive_anomalies − 1` intervals
  *into* the anomaly streak, so a streak that visibly covered an incident was
  marked missed (e.g. 27% recall shown while almost every incident was caught).
  Recall/FDR now match an incident against each alert's **whole anomaly-streak
  span** by overlap (the worker returns `fireSpans` alongside `fires`), so a streak
  covering an incident counts as caught.
- **Threshold capture produced near-zero-width "point" incidents** that the fired
  alert landed just outside of. Each captured span is now **widened to a full grid
  interval** (half each side), so a single matching point becomes a real incident.
- **The "≈1 in N false" false-alert readout rounded a mostly-false rate down to a
  misleading "1 in 1".** It now keeps one decimal below 10 (e.g. a 73%-false rate
  reads "≈1 in 1.4 false") so the framing matches the percentage beside it.

## [0.36.2] - 2026-06-25

### Fixed
- **`dtk tune` loaded the entire history (and hung the recompute) when a metric
  had many saved incidents.** The 0.36.0 window-widening pulled the loaded window
  back to the *earliest* seeded incident, so a single old outlier among the
  incidents dragged in the whole series (e.g. 33k points instead of the budgeted
  ~9k) and the client-side recompute — O(points × window) — never finished. The
  window is now kept **budget-sized** (`default_window_points`) and **anchored on
  the incident region**: it ends just past the *latest* incident (with a few
  windows of recovery context) rather than at the last datapoint, so recent
  incidents still render and score while the load stays bounded. Incidents older
  than the loaded window remain in the list (and are excluded from the live
  metrics); use `--from`/`--to` to tune against a specific older window. Removes
  the now-unreachable `_TUNE_INCIDENT_MAX_POINTS` ceiling.

## [0.36.1] - 2026-06-25

### Fixed
- **`dtk tune` crashed with `TypeError: can't compare offset-naive and
  offset-aware datetimes` when widening the window to seeded incidents on a
  backend that returns tz-aware timestamps.** The 0.36.0 window-widening compared
  the DB's last-datapoint timestamp (tz-aware on some backends) against an
  incident start parsed from a naive-UTC display string. The earliest incident is
  now aligned to the DB timestamp's awareness (both represent UTC) before the
  comparison, so `dtk tune` opens for metrics with saved incidents regardless of
  backend.

## [0.36.0] - 2026-06-25

### Fixed
- **`dtk tune`: seeded incidents now render on the chart and count toward the live
  metrics.** Previously `dtk tune` only loaded the most-recent slice of the series,
  so any incident from `incidents/<metric>/` older than that slice showed in the
  **Marked incidents** list but never on the chart — and dragged the recall metric
  down because it could never be caught. The loaded window is now **widened back to
  cover the seeded incidents** (with leading context for the detector's window,
  clamped to the first datapoint and a `_TUNE_INCIDENT_MAX_POINTS` ceiling), and the
  catch-rate / false-alert metrics **only score incidents that overlap the loaded
  (possibly trimmed) window** so an out-of-range label can't mechanically skew them.

### Added
- **`dtk tune`: Threshold capture in the incident labeler.** The labeler chart gains
  the same productivity tool as the autotune `html_labeler`: toggle **Threshold
  capture**, set a horizontal line (click the chart or type a value), choose
  **above**/**below**, optionally **bridge gaps** of a few intervals, and optionally
  **drag across the chart** to limit the capture to a time window — then **Add N
  spans** marks every contiguous run past the line in one click (overlapping spans
  merge into existing incidents). The painted window is persisted as
  `capture_windows` in the saved labels file and restored when `dtk tune` reopens
  (pure metadata — `dtk autotune` ignores it). Implemented in the shared
  `demo/chart.ts` `labeling` mode (`setThresholdMode` + an `onThresholdChange`
  callback); the landing playground is untouched (the tool is off by default). The
  committed `detectkit/tuning/assets/tune.js` bundle is regenerated.

## [0.35.0] - 2026-06-25

### Changed
- **Alert timing fields renamed so the onset can't be mistaken for the alert
  time, and recovery now shows the full timeline.** The previously ambiguous
  **Started** / **Latest** / **Cleared** labels are now self-describing:
  - anomaly alerts show **Anomaly began** (the resolved onset — the *first*
    anomalous point) and **Latest reading** (the most recent point);
  - recovery alerts show the full **Anomaly began → Alert fired → Recovered**
    timeline, where **Alert fired** is the on-grid moment the rule first tripped
    (`onset + (consecutive_required − 1) × interval`).

  This fixes the confusion where "Started" could read as *when the alert fired*
  rather than *when the metric first went bad* — the two differ whenever the
  rule waits for several consecutive intervals. Applies to every channel
  (Slack/Mattermost/webhook, Telegram, email) and the plain-text `{window_line}`.
  A new `{fired_display}` template variable exposes the alert-fire moment (empty
  when the run predates the lookback window or no interval is wired in). Purely a
  rendering change — no detector-ID resets and no stored-data changes.

## [0.34.0] - 2026-06-25

### Added
- **`dtk tune` is now a full config cockpit: mark real incidents and see alert
  quality live.** Beneath the detector chart there is a **synced incident-labeler
  chart** — drag to mark a real incident span, drag its edges to adjust / its
  middle to move, click its ✕ (or select + Delete) to remove. The two charts share
  x-zoom/pan, y-scale and the "Points shown" trim, and the detector chart overlays
  the same spans (read-only) so alerts vs incidents read together. A prominent
  metrics bar updates as you tune, with two operator-facing numbers:
  - **incident catch rate (recall)** — what share of the marked incidents your
    current config actually catches; and
  - **false-alert rate (FDR / type-I control)** — what share of fired alerts fall
    outside any real incident, shown as a percentage and "≈1 in N false".

  **Save incidents** writes a versioned `incidents/<metric>/<…>.yml` (the **same**
  store `dtk autotune` reads), so a labeling round in `dtk tune` also feeds the next
  supervised autotune — one source of truth. `dtk tune` seeds the labeler from the
  newest file in that directory on open. Saving labels does not end the session
  (only **Apply** does); `dtk tune --no-serve` downloads the labels file instead.
  The labels schema, validation and versioned filenames are shared with the
  autotune labeler.
- **`y = 0` reference line on the `dtk tune` and `dtk run --report` charts.** A
  toggle draws a horizontal line at zero and folds 0 into the vertical scale, so a
  real-valued metric can be read **relative to zero**. Off by default; the landing
  playground is unchanged.

## [0.33.0] - 2026-06-25

### Fixed
- **`dtk tune`: the window slider now reflects (and preserves) the metric's real
  `window_size`.** It was clamped to `min(2000, points_shown / 2)` and snapped to a
  step of 5, so any metric with a larger window (common for sub-hourly metrics —
  e.g. 4320 or 8640) showed a smaller, wrong value the slider couldn't even reach,
  and **Apply could silently shrink the metric's window** to the clamp. The slider
  now seeds the exact configured value (step 1) and raises its maximum to at least
  that value, so the preview computes — and Apply writes — the metric's actual
  window.
- **`dtk tune`: turning the Threshold slider now visibly widens/narrows the
  band.** The chart fitted its y-axis to the confidence band, so a wider band grew
  the axis in lockstep and the corridor looked unchanged. The tuning chart now fits
  the y-axis to the **data** (new opt-in `yFit: 'data'` chart option; the read-only
  report keeps the band-inclusive fit), so threshold changes read at a glance. The
  landing playground is unchanged.
- **`dtk tune`: a large metric window is now actually exercised in the preview.**
  The default shown-point count is floored at a few windows' worth of history
  (instead of collapsing toward the minimum for big windows), so the band reaches
  its real width instead of leaving almost no scored region.

### Added
- **Detectors warn when the window is too small to fill a seasonality group.**
  A per-group correction engages only when the trailing window holds
  `min_samples_per_group` points sharing the current point's seasonal key, which
  recur once per *cardinality* — so it needs `window_size ≳ min_samples_per_group ×
  distinct_keys` (hourly `hour` ⇒ ≳ 240). Below that the group **silently falls
  back to the global band and the seasonality has no effect** — easy to hit with
  the default `window_size = 100`. The windowed detectors (MAD / Z-Score / IQR) now
  log a one-time warning naming the group, its key count and the required window.
- **`dtk autotune` offers a seasonality-fill window candidate.** The window grid
  now includes `min_samples_per_group × cardinality` when the data carries
  seasonality columns (capped to the fold budget), so cross-validation can actually
  evaluate a window where a chosen seasonal grouping engages instead of one where it
  silently falls back to global. When even the largest fold-feasible window can't
  fill the groups, the decision log says so.

## [0.32.0] - 2026-06-25

### Added
- **`dtk tune`: a Manual-bounds detector option.** The detector picker now offers
  **Manual** alongside MAD / Z-Score / IQR. Selecting it swaps the windowed knobs
  for **Lower bound** / **Upper bound** sliders (seeded from the metric's bounds,
  or the data's p5/p95 band) so you can drag fixed thresholds against the real
  series and watch the flagged points — and the resulting alert count — update
  live. **Apply** writes a stateless `manual_bounds` detector back into the metric
  YAML (validated, previous version archived). The browser port is parity-checked
  against the Python `ManualBoundsDetector` (golden vectors).
- **`dtk tune`: a Direction filter.** A **both / up / down** control restricts
  which anomalies are shown and counted toward alerts — only spikes above the
  band (up), only drops below it (down), or both. It is a preview filter (seeded
  from the metric's alerting `direction`, with `same` reading as `any`) that
  mirrors the alert direction policy without changing the band.

### Fixed
- **`dtk tune` chart + autotune incident labeler: overlapping x-axis date
  labels.** For spans of roughly 3–6 months the adaptive time-tick picker fell
  into a gap (no sub-monthly step met the target count) and packed ~13 biweekly
  labels onto the axis, overlapping. The picker now escalates to calendar
  months/years at the right span, and both the main axis and the navigator strip
  thin any labels that would still collide (gridlines are unaffected).

## [0.31.1] - 2026-06-25

### Added
- **`dtk tune`: window size and half-life echo their wall-clock span.** The
  **Window size** and **Half-life** sliders — both measured in points — now show
  the equivalent duration on the metric grid next to the point count (e.g.
  `2000 · 83d 8h` on a 1h metric), so "how much history is this window" and "how
  far back does the decay reach" read at a glance. Mirrors the existing
  "Points shown" trim echo. Display only — what **Apply** writes is unchanged.

## [0.31.0] - 2026-06-25

### Added
- **`dtk tune`: zoom, pan and a navigator on the chart.** The interactive tuning
  chart is now navigable — scroll to zoom where you point, drag to pan,
  double-click to reset, and drag the **navigator strip** below the chart (the
  whole series in miniature, with the current-view window, the **alert firings as
  red ticks**, and a time axis). On a long, dense metric you can now zoom into a
  region to inspect alert quality instead of reading the whole series at once.
  Adaptive **time gridlines** now label both the chart and the strip.
- **`dtk tune`: a "Points shown" trim slider.** Above the chart, it shortens the
  active sample to the most-recent N points. Live recompute cost grows with
  *points × window*, so trimming a long series (e.g. 10k → 2k points) makes every
  knob-drag several times faster and the period easier to read. Trimming only
  affects the live view — it never changes what **Apply** writes.
- **`dtk tune`: flexible seasonality groups.** Each seasonality column is now
  assigned to a group (Off / G1 / G2 / …): columns in the **same** group are
  conjoined into one seasonal key, **separate** groups apply independent
  corrections. You can now express the full `seasonality_components` grouping
  (e.g. one `dow`×`hour` group plus a standalone `is_holiday`), not only
  "all-separate" or "all-in-one".
- **`dtk tune`: chart legend, control tooltips and a recompute spinner.** A legend
  labels the metric line / expected-range band / band center / anomalies / alert
  markers; every control carries an **ⓘ** tooltip explaining it; and a
  **computing…** spinner shows while a recompute is in flight (replacing the bare
  status text).
- **Autotune incident labeler: marked incidents now show on the navigator.** The
  red incident bands you mark are drawn on the bottom navigator strip too — at a
  minimum width so even a single-point incident stays visible on a long span — and
  the strip gained a **time axis**. The main chart gained adaptive vertical **time
  gridlines**, so a point's place in real time reads off the grid instead of only
  by chasing the cursor.

### Fixed
- **Labeler x-axis date labels on high-DPR displays.** The labeler's bottom time
  labels were positioned with a doubled `devicePixelRatio` factor, pushing them
  off-canvas on retina / 2× screens; they now sit correctly under the chart at any
  DPR.

## [0.30.1] - 2026-06-24

### Fixed
- **`dtk tune` is now responsive on large metrics.** It previously baked a
  metric's *entire* history into the page and re-ran the client-side detector
  over **all** points on every knob change — on a metric with tens of thousands
  of points that made the page slow to load and froze the UI on every slider
  drag. Three changes fix it:
  - **The detector now runs in a Web Worker** (off the UI thread), so dragging a
    slider never freezes the page no matter the point count or window size; a
    `computing…` hint shows while a recompute is in flight and stale results are
    dropped. The worker runs the *same* parity-checked detector port, so results
    are unchanged.
  - **Smart default point count** — instead of a flat cap, the shown window is
    sized **inversely to the detector's window** (recompute cost is
    `points × window`): small windows show up to ~15k points, large windows fewer,
    clamped to a render-comfortable range. A `--from` / `--to` span is still
    honored in full.
  - The window-size slider is capped at half the shown points, the live recompute
    is **debounced**, and the CLI reports how many points it is tuning on.
- **`dtk tune` no longer spews `xdg-open` errors** when launching the browser on
  a headless / WSL box: the best-effort browser launch now silences its stderr,
  and the printed hint tells you to open the URL manually if no browser appears.

## [0.30.0] - 2026-06-24

### Added
- **`dtk tune` — interactive manual tuning that writes the config back into the
  metric.** The human-in-the-loop sibling of `dtk autotune`. It opens an
  interactive browser view of the metric's **real** persisted series and lets you
  turn the detector's knobs — type (MAD / Z-Score / IQR), threshold, window,
  recency weighting + half-life, detrend, smoothing, seasonality conditioning,
  and the alert `consecutive_anomalies` — while the confidence band, flagged
  anomalies and would-fire alerts **recompute live in the browser** (the same
  faithful TypeScript detector port that powers the landing playground, fed the
  real series instead of synthetic data). Clicking **Apply to metric** writes the
  chosen config back into the metric YAML. Where `dtk autotune` searches
  automatically and writes a *new* `__tuned_<id>.yml`, `dtk tune` is manual and
  edits the metric **in place** — the two are complementary paths to optimizing a
  metric. Delivery mirrors the autotune incident labeler: a localhost-only server
  with a one-shot token; nothing is exposed off the machine and nothing is written
  until you click Apply.
- **Safe write-back with a versioned config history.** On Apply, the chosen
  detector + params are validated through `MetricConfig` **and** the
  `DetectorFactory` *before anything is written* (a broken or untunable config
  never lands, returning a 400 so you can fix the knobs and retry); the previous
  metric YAML is then archived verbatim under `metrics/.history/<metric>/<stamp>.yml`
  (so the history of chosen parameters is trackable and the original — including
  its comments — is always recoverable); only then is the metric file re-emitted
  with the tuned detector. `dtk tune` takes **no pipeline lock** (it only edits a
  config file); re-run `dtk run` afterwards to recompute detections under the new
  config (the live preview is the TS approximation, the next real run is the
  source of truth). `dtk tune --no-serve` writes a static, read-only preview HTML
  (sliders recompute live, no write-back). New top-level `detectkit/tuning/`
  package (`build_tune_payload`, `render_tune_html`, `apply_tuned_config`,
  `serve_tuner`); the renderer bundle `detectkit/tuning/assets/tune.js` is built
  from the shared chart/detector core (`website/scripts/gen-tune-bundle.mjs`) and
  ships in the wheel.

## [0.29.0] - 2026-06-24

### Added
- **`dtk run --report` / `dtk autotune --report` emit a self-contained HTML
  report.** Each writes one offline HTML file per metric — values + per-detector
  confidence bands + flagged anomalies + the alerts that fired (anomaly /
  recovery / no-data) + a summary, with client-side period selection (24h / 7d /
  30d / All, plus zoom/pan) and an alerts list (rule that fired, severity,
  duration). Nothing leaves the browser (inline JS, baked payload), so a user can
  see how a metric actually performed without standing up BI / SQL / a 3rd-party
  charting tool. `--report` is dual-mode: bare `--report` → default path
  (`reports/<metric>.html`; autotune: `reports/<metric>__tuned_<id>.html`),
  `--report <dir>` → `<dir>/<metric>.html`, `--report file.html` → that file.
  The report reads the persisted `_dtk_*` tables, so even a `--steps load` run can
  produce one from whatever is stored. New top-level `detectkit/reporting/` package
  (`build_report_payload` reads `_dtk_datapoints` + `_dtk_detections` and replays
  alerts into a JSON payload; `render_report_html` inlines the pre-built renderer
  bundle `detectkit/reporting/assets/report.js` + the payload into one HTML file).
- **Alert replay reconstructs the alert/recovery/no-data timeline from persisted
  detections.** A new pure `AlertOrchestrator.replay(detections, value_at, start,
  end)` (`detectkit/alerting/orchestrator/_replay.py`, `ReplayedEvent`) re-walks
  the **real** decision logic (quorum / consecutive / cooldown / recovery /
  no-data) over a historical period — no channel dispatch, no `_dtk_alert_states`
  writes, no wall-clock. This is how the report surfaces alerts, because
  `_dtk_alert_states` is last-writer-wins state, not an event log. It reuses the
  existing decision/builder functions verbatim; `_resolve_incident` gained an
  optional in-memory `records=` parameter so recovery resolution stays DB-free
  during replay (the production path is unchanged).
- **`InternalTablesManager.load_detections(...)`** — a new reader returning flat
  per-(detector, timestamp) detection rows (`detector_id` / `from_timestamp` /
  `to_timestamp` filters, `final_modifier` for correct `ReplacingMergeTree`
  dedup), parallel to `load_datapoints`. The report builder reads through it.
- **An interactive landing playground.** The website (`website/`) ships a
  client-side island where a visitor shapes a synthetic metric
  (seasonality/noise/trend/incident) and tunes the real detector
  (MAD/zscore/iqr, threshold, window, recency, detrend, smoothing, seasonality
  grouping, `consecutive_anomalies`) live — seeing the corridor, flagged points,
  the trailing window used to score each point, and whether an alert would fire,
  all in-browser with zero server compute. Its chart renderer is the **same**
  framework-free TypeScript core (`website/src/scripts/core/canvas.ts`) the HTML
  report uses; the report bundle is built from it by
  `website/scripts/gen-report-bundle.mjs` (esbuild) into
  `detectkit/reporting/assets/report.js` (a committed generated asset). The
  playground's detector math is a TS port verified to exact parity against the
  Python detectors (`website/scripts/check-demo-parity.mjs`, golden vectors from
  `website/scripts/gen-demo-golden.py`).

## [0.28.0] - 2026-06-24

### Added
- **Autotune searches the recency half-life.** The grid search previously only
  toggled recency weighting on/off at a fixed half-life; it now sweeps the
  half-life (in points, as fractions of the window, floored at `min_samples/2`)
  whenever exponential weighting is adopted. This lets the search pick a
  faster-forgetting baseline that tracks the **current** regime — the knob that
  matters on a metric that shifted level — instead of leaving it at the default.
- **The regime advisory names a concrete `--from` date.** The `REGIME` advisory
  (0.27.0) now maps the detected level-shift index to the actual grid timestamp
  and suggests `--from <YYYY-MM-DD>` verbatim (e.g. `--from 2026-05-22`), instead
  of a generic "after the shift". The scan runs NaN-aware on the raw grid so the
  index aligns with the timestamps. The boundary date is recorded as `shift_at`
  in the decision log.
- **The labeler persists its threshold-capture time window.** The painted capture
  window (the regime scope you drag on the chart) is now written to the saved
  labels file as an optional `capture_windows:` block and **restored when you
  reopen** the set — so the regime boundary you reasoned about is auditable and no
  longer lost between sessions. It is pure metadata: it never affects ground truth.

### Changed
- **The cross-fold stability penalty is now downside-only.** Candidate scoring was
  `mean(folds) - λ·std(folds)`; `std` penalized *upside* spread too, biasing the
  search against a regime-adaptive config that simply scores **better** on the
  recent regime than on stale history. It is now `mean - λ·downside_deviation`
  (shortfalls below the mean only, averaged over all folds — always ≤ the old
  penalty), so an adaptive config is no longer punished for fold-to-fold variance
  that is actually improvement. The weight is exposed as `autotune.stability_lambda`
  (default `0.5`; set `0.0` to disable) for a metric whose behavior differs across
  a regime shift. Tuning scores shift slightly and some winners may change
  (detector identity is unaffected).

## [0.27.0] - 2026-06-24

### Added
- **Autotune flags a hidden regime shift in the decision log.** The trend gate
  that drives window selection and the detrend toggle is a single midpoint-median
  test, so it silently misses a level shift that sits **off-center** (both halves
  straddle it, so their medians barely differ) or one large enough to **inflate
  the very MAD it is measured against** — and then treats the series as
  stationary, prefers the largest window, and lets the baseline quietly average
  two regimes. A new scan (`detect_level_shift`) checks every split point against
  the **within-segment** scale (which a true step does not inflate, unlike a
  smooth ramp); when the series reads stationary yet a large (≥3σ within-regime)
  level shift is present, the run emits a `REGIME` advisory — streamed live and
  rendered in the annotated config header and `_dtk_autotune_runs.decision_log_json`
  — pointing at where the shift sits and suggesting you narrow the window with
  `--from` (or `autotune.max_history`) and re-tune. **Advisory only:** it changes
  no chosen parameters. It detects *level* shifts, not pure variance/shape changes
  (those still need labeled incidents). See the autotune reference's
  "Non-stationary metrics & regime shifts" note.

## [0.26.1] - 2026-06-24

### Changed
- **Made the threshold-capture time window discoverable.** The per-period window
  (added in 0.26.0) was only reachable by dragging the chart, with no visible cue
  — the reset button appeared only after a window existed. The threshold bar now
  always shows the current scope (`period: current view — drag the chart to limit
  it`, or `period: <span>` once set), and the on-chart readout prompts `drag the
  chart to pick a period` before a line is set. No behavior change.

## [0.26.0] - 2026-06-24

### Added
- **Threshold capture can be scoped to a time window.** Previously the labeler's
  threshold capture scanned the whole series, so one boundary had to fit every
  period. Now it captures within the **current view** by default, and you can
  **drag horizontally across the chart** to paint a narrower capture window — the
  area outside dims, the dashed line spans only the window, and the readout shows
  its span. This lets a metric that behaved differently across history take a
  different above/below boundary per period. **↺ whole view** clears the window;
  the existing flow is unchanged (a click sets the line, a horizontal drag sets
  the window).

## [0.25.0] - 2026-06-24

### Added
- **The incident labeler can now open and edit an existing labels file.**
  `dtk autotune --select <m> --label` **seeds the page from the metric's newest
  saved set** in `incidents/<m>/` (or from `--incidents <file-or-dir>` when given),
  so labeling can grow across sessions — open, mark a few more, **Save & tune**
  writes the next version (history is still kept; nothing is overwritten). The
  static `--no-serve` page also gains an **Import file…** button that loads any
  labels file (YAML/JSON) you pick. The seed preserves each incident's
  `label:` description.
- **Threshold capture.** When many outliers are obvious, set a horizontal line on
  the chart (hover, or type an exact **line value**), choose **above / below**,
  optionally **bridge gaps ≤ N intervals**, and **Add N spans** marks every
  qualifying contiguous span at once — instead of zooming in and dragging each.
  The normal click-drag flow is unchanged; threshold capture is a toggled mode.
- **On-chart incident deletion.** Each incident band carries a **✕** handle
  (top-right); the selected band also responds to the **Delete**/**Backspace**
  key, and **Escape** deselects. No more scrolling the list to find the one row to
  remove. Selecting a band highlights and scrolls to its list row; **focus** on a
  row jumps the chart to that incident (the list ↔ chart now highlight together).
- **Favicon** — the labeler page now uses the detectkit brand mark as its tab icon
  (inline SVG data URI, still fully self-contained).

### Changed
- `IncidentInterval` / `IncidentPoint` (`detectkit/autotune/labels.py`) now carry
  an optional `label`, so parsing a labels file round-trips its descriptions; new
  `incidents_to_display` / `load_incidents_for_display` helpers render a file as
  labeler-seed dicts. `render_labeler_html` / `build_label_server` /
  `serve_labeler` gain an `incidents` / `preload` argument.

## [0.24.2] - 2026-06-24

### Fixed
- **`dtk run` now detects on the first run of a detector that has no
  `start_time` — every `dtk autotune`-generated config.** `DETECT` builds its
  lower bound from `--from`, the resume point (last persisted detection), and the
  detector's `start_time` param. When all three were absent — exactly the case
  for a freshly-created tuned metric (no `--from`, no prior detections, and the
  emitter never wrote `start_time`) — the lower bound was left unset and the step
  mistook "no lower bound" for "nothing to do", printing **"Nothing to detect
  (already up to date)"** and writing **zero detections**. The alert step then
  reported "No recent detections found" and dashboards showed an empty detections
  chart, while loading worked normally. `DETECT` now falls back to the metric's
  `loading_start_time` (then its earliest stored datapoint) so the first run
  detects across all loaded history. Hand-written metrics that set `start_time`
  were unaffected, which is why this only bit autotuned configs.

### Changed
- **`dtk autotune` now writes `start_time` into the generated detector's
  params** (pinned to `loading_start_time`), so the emitted
  `metrics/<name>__tuned_<id>.yml` is explicit and self-sufficient — it detects
  correctly even on an older detectkit that lacks the `DETECT` fallback above.
  `start_time` is execution-level and excluded from the detector-id hash, so it
  never changes detector identity or forces recomputation.

## [0.24.1] - 2026-06-24

### Changed
- **`dtk init-claude`'s managed `CLAUDE.md` block is now version-less.** The
  `<!-- BEGIN detectkit … -->` marker no longer embeds the detectkit version, so
  re-running after an upgrade is a true no-op unless the shipped guidance actually
  changed. Previously every release rewrote the marker (the version moved), which
  reported the block as `updated` and nudged users to re-run for nothing. Existing
  versioned markers (e.g. `<!-- BEGIN detectkit v0.23.2 … -->`) are still matched
  and refreshed in place, so upgrades stay seamless.

### Fixed
- **Corrected the shipped `dtk init-claude` AI-assistant reference.** The `cli.md`
  rule described metric-name selection as "searches the root `metrics/` dir only";
  it actually resolves `metrics/<name>.yml` at the root and then falls back to a
  recursive search by the YAML `name:` field in any subdirectory. It also called
  `--steps` a "subset/order" of stages — the steps always execute in
  `load → detect → alert` order regardless of how they are listed. The
  `dtk-autotune` skill suggested an invalid `--scoring recall`; the valid scoring
  metrics are `mcc`, `f1`, `f_beta`, `balanced_accuracy`, `roc_auc`, `pr_auc`.

## [0.24.0] - 2026-06-24

### Fixed
- **`dtk autotune` no longer emits an invalid config for metrics whose seasonality
  comes from the query.** When a metric sources seasonality via
  `query_columns.seasonality` (custom columns such as `league_day`), the tuner could
  pick a grouping over those columns and then duplicate them into the top-level
  `seasonality_columns` field — which is validated against the built-in allowlist
  (`hour`, `day_of_week`, …) and is *ignored* by the loader in that mode. The result
  was a `MetricConfig` validation error and no tuned config written (`0 succeeded`).
  The emitter now keeps query-provided seasonality columns in `query_columns` only;
  the chosen grouping still rides in the detector's `seasonality_components`, so
  detection behavior is unchanged.

### Changed
- **The labeler names exported/saved files after the metric**, with the optional set
  name folded in as a suffix: `<metric>[-<set>]-<UTC>.yml` (e.g.
  `api_error_rate-outage-20260624T010252Z.yml`, or `api_error_rate-<UTC>.yml` with no
  set name). Previously a typed set name *replaced* the metric name in the filename;
  now it is always appended, so every labeling round stays grouped under the metric.

## [0.23.2] - 2026-06-24

### Added
- **The labeler shows the metric's sampling interval** as a highlighted chip next
  to the metric name (e.g. `interval 1h`) — the point spacing, taken straight from
  the metric (inferred from the series when not provided).

## [0.23.1] - 2026-06-24

### Added
- **Live time readout while editing an incident in the labeler.** Dragging an
  incident's edge now shows `start/end: <old> → <new>`, and creating or moving a
  band shows the resulting `<start> → <end>`, so you can place a boundary on an
  exact timestamp.

## [0.23.0] - 2026-06-24

### Added
- **One-command interactive labeling → tuning.** `dtk autotune --select <m> --label`
  now launches a small **local labeler server** (127.0.0.1, one-shot token), opens
  the browser, and on **Save & tune** writes a versioned labels file straight into
  `incidents/<m>/` and **continues into the tuning run on it** — no manual file
  shuffling. `--no-serve` keeps the old static-HTML-download behavior; `--no-open`
  prints the URL instead of launching a browser.
- **Per-incident descriptions and named label sets** in the labeler — the
  description exports as the canonical `label:`; the set name becomes the
  versioned filename `<name>-<UTC>.yml`.
- **Edit existing incidents on the chart** — drag an incident's edges to adjust
  its bounds, or its middle to move it (visible edge handles + resize cursor).
- **Choose among saved label sets at tune time.** When `--incidents` points at a
  directory with multiple versions and the terminal is interactive, you're
  prompted to pick one (default: newest); non-interactive runs use the newest.

### Changed
- **Examples no longer use a real production metric name.** The labeler demo (and
  shipped example) now uses a generic `api_error_rate` with realistic error-rate
  numbers instead of `sessions_per_visitor_avg`.

## [0.22.0] - 2026-06-24

### Changed
- **Interactive incident labeler (`dtk autotune --label`) overhauled.** The
  self-contained HTML chart is now zoomable/pannable so narrow incidents are
  markable even on a long span with a small step: scroll to zoom at the cursor,
  double-click to reset, and a navigator strip below the chart to move the view
  (drag the window to pan, drag its edges to stretch/squeeze). Large series stay
  fast and spike-faithful via min/max decimation. Each incident now takes an
  optional **description**, exported as the canonical `label:` field. Restyled on
  the detectkit brand (palette/fonts/logo, axes, hover tooltip, live summary).
- **Versioned, never-overwriting exports.** Export downloads a timestamped file
  `<metric>-<UTC>.yml` (a browser can't write to the project), so keep every
  labeling round under `incidents/<metric>/`.

### Added
- **Directory-aware label resolution.** `--incidents` (and `autotune.labels_file`)
  may point at a directory; the newest versioned file in it is used —
  `dtk autotune --select <m> --incidents incidents/<m>/` always tunes on the
  latest labels while the full history stays on disk.
- **Landing + docs** showcase the labeler with a live, embedded demo generated
  from the real template (`website/scripts/gen-labeler-example.py`).

## [0.21.0] - 2026-06-24

### Changed
- **`dtk autotune` now works well out of the box without labels — every stage of
  the unsupervised pipeline was reworked so the no-label baseline is good on its
  own (labels remain a bonus that further improves it).** This recomputes tuned
  configs; per detectkit's policy that is acceptable. Specifically:
  - **Seasonality selection is decoupled from the flag-objective.** The old probe
    scored a candidate grouping with the same low-flag-rate objective used for
    detection, which is structurally biased *against* seasonality (finer groups →
    tighter bands → more flags → worse score), so genuinely seasonal metrics were
    rejected with "chose none". It now uses a leak-free, walk-forward,
    **band-width-aware** Gaussian-NLL probe (`oof_residual_reduction`) that
    measures how much conditioning on a seasonal key tightens the per-group
    center/scale the detector actually applies, evaluated on *held-out* folds.
    Over-fragmented groupings fall back to global and can't win mechanically; the
    no-seasonality baseline scores 0; a move is accepted only on a margin **and**
    an improvement in the majority of folds.
  - **The unsupervised detector objective now rewards a tight confidence
    interval.** `unsupervised_objective` is now `0.4·budget + 0.3·sharpness +
    0.3·separation`: a smooth flag-rate **budget** (no flat cliff; one-sided so a
    clean metric isn't pushed to flag), **sharpness** (rewards a narrow,
    well-calibrated band — the old ratio-only objective was scale-invariant and
    blind to band width), and **separation**. All-suppress no longer sits at a
    timid `0.6` plateau — it scores only `w_budget`, so a tight band that isolates
    real extremes strictly beats doing nothing.
  - **Detector selection no longer excludes a type by heuristic.** The
    distribution suitability vote is now advisory (it only orders the candidates);
    the grid search evaluates **all** windowed statistical detectors and lets
    cross-validation pick the winner.
  - **Grid search fixes the threshold↔window coupling** with a final threshold
    re-sweep at the chosen window, and the threshold grid gained high
    "near-suppress" rungs (5/6σ, 4/6 Tukey) so a heavy-tailed metric can widen the
    band under the budget instead of being trapped flagging its tail.
  - **Window selection is trend-gated**: stationary series still prefer the larger
    window, but under a trend / regime shift the tie-break now prefers the
    *smaller* window (a fresher baseline) instead of averaging in stale history.
- **Honest unsupervised header.** Emitted tuned configs (and the CLI log) no
  longer label an unsupervised run's score as `mcc = …` (it never computed MCC);
  they read `Objective : unsupervised (band-fit + flag-budget) = …`.

### Added
- **`autotune.force_seasonality`** — pin the seasonality grouping (a column or a
  conjunctive `[col, col]` group) and skip the search, for experts who already
  know a metric's seasonality. Complements `seasonality_candidates`, which only
  *restricts* the search.
- **Per-candidate transparency in the seasonality decision log** — each tested
  component now records its held-out residual reduction (e.g.
  `hour:5.70, day_of_week:-0.00`), so a "chose none" is never opaque.

## [0.20.0] - 2026-06-23

### Added
- **`dtk init` now scaffolds an `incidents/` directory** beside `metrics/`, with
  a commented example labels file (`incidents/example_cpu_usage.yml`) and a
  commented `autotune:` block in the example metric. This makes the documented
  `incidents/<metric>.yml` convention for supervised `dtk autotune` ready to fill
  in on a fresh project.
- **Inline incidents on the `autotune:` block.** Labeled incidents can now be
  declared directly in a metric config via `autotune.incidents` (the same
  `{start, end}` / `{at}` entries as a labels file) plus an optional
  `autotune.incidents_timezone`, as an alternative to `autotune.labels_file` —
  handy for a metric with one or two known incidents. `incidents` and
  `labels_file` are mutually exclusive (validated at config load). Label
  resolution precedence is now: `--incidents` flag → `labels_file` → inline
  `incidents` → interactive prompt → none (unsupervised).

### Changed
- **`dtk init-claude` context** now recommends (optionally) giving the assistant
  read access to the database — e.g. a database MCP — so it can inspect series,
  find incidents to label, and verify queries itself. Made explicit that
  detectkit's pipeline never needs an MCP (it connects via its DB drivers); the
  access is an assistant convenience, not a runtime requirement.

## [0.19.0] - 2026-06-22

### Added
- **`dtk autotune` — automatic detector configuration.** A new pipeline that,
  given a metric's loaded datapoints (and optionally labeled incidents),
  automatically chooses the seasonality grouping, detector type,
  hyperparameters and history window, cross-validates the choice, and writes a
  ready-to-run, fully annotated config named `<metric>__tuned_<id>`. The comment
  header walks every decision (seasonality, detector votes, grid-search winner +
  CV score, window). It reads `_dtk_datapoints`, never edits the original config
  and never sends alerts.
  - **Seasonality** is greedily searched over the metric's columns; the
    **detector type** is chosen by a distribution decision tree that votes per
    seasonality group (Gaussian → `zscore`, heavy-tailed/outliers → `mad`,
    skewed → `iqr`); **hyperparameters** come from a bounded coordinate grid
    search; the **history window** prefers more context on near-ties.
  - **Supervised** tuning scores against a labels file (`--incidents`, YAML/JSON
    of incident intervals/points); with no labels it falls back to an
    **unsupervised** objective (low false-positive rate + cross-fold stability).
    Cross-validation is automatic walk-forward folds — no split ratios to set.
  - **Scoring metric** defaults to **MCC** (uses the whole confusion matrix,
    robust to rare anomalies); configurable via `--scoring`
    (`f1`/`f_beta`/`balanced_accuracy`/`roc_auc`/`pr_auc`).
  - **`--label`** emits a self-contained HTML chart to mark incidents visually
    and export a labels file. **`--dry-run`** searches without writing anything.
- **`_dtk_autotune_runs` internal table.** One row per autotune run (inputs +
  outputs: training period, labels, scoring metric, chosen seasonality/detector/
  params, CV score, decision log, generated config). An audit trail — created by
  `ensure_tables()`, never read by the pipeline and never pruned by
  `dtk clean --orphaned-metrics`.
- **Optional `autotune:` block on a metric config.** Lets experts constrain the
  search (restrict detector types / seasonality columns, pin hyperparameters,
  set the scoring metric, point at a labels file, cap history/folds). Fully
  optional — absent means fully automatic.
- **`dtk init-claude` ships a `dtk-autotune` skill + `autotune.md` rule.** The
  skill drives the whole flow conversationally — seasonality interview, writing
  the labels file from the user's words, running `dtk autotune`, presenting the
  annotated result, and generating a per-backend DB query to inspect the tuned
  detector's behavior — including the "build a working alert from a request"
  hand-off to `dtk-new-metric`.

## [0.18.0] - 2026-06-21

### Changed
- **Default `half_life` is now floored at `min_samples / 2`** (windowed
  detectors: mad/zscore/iqr). When `window_weights: exponential` is set with
  `half_life` unset, the default was `window_size / 20` unconditionally. On the
  default 100-point window that resolved to `5` points — an effective (Kish)
  sample size of ~14, **more aggressive** than the legacy `weight_decay=0.95`
  default (~13.5 points, ESS ~38) that this very feature was redesigned to
  avoid. The default is now `max(window_size / 20, min_samples / 2, 1)`:
  - It keeps the `window/20` adaptation horizon the large-window trending recipe
    is tuned for (window `8640` → `432` points ≈ `"3d"`).
  - On small/default windows the `min_samples / 2` floor keeps the effective
    weighted sample size at parity with the raw `min_samples` gate (window `100`,
    `min_samples=30` → `15` points, ESS ~42), instead of silently honoring only
    half of it.
  - Only affects detectors that set `window_weights: exponential` **and** leave
    `half_life` unset; an explicit `half_life` (or `weight_decay`) is unchanged.
- **`ALGORITHM_VERSION` of the windowed detectors bumped to v3.** Because the
  resolved default changes the confidence bounds for the same config, the
  detector IDs change so affected detections recompute cleanly under the new id
  rather than mixing two regimes in `_dtk_detections` (same mechanism as the
  v1→v2 bump). Detections for all windowed detectors recompute on the next run.

## [0.17.0] - 2026-06-21

### Added
- **Alert messages now answer "how long has this been going on?"** Every
  default-rendered anomaly leads with a plain-language sentence —
  `Anomalous for 2h 30m — 15 consecutive 10min intervals.` — surfacing the
  metric **interval**, the **true consecutive streak length**, and the
  wall-clock **duration**. New `Started` / `Latest` fields bound the
  problematic span. Recovery alerts are symmetric:
  `Incident lasted 2h 30m (…)` with `Started` / `Cleared`.
  - The true streak length and onset are resolved **only when an alert
    fires/clears** — `_decision.py` (`_resolve_streak`) and `_recovery.py`
    (`_resolve_incident`) look back over the detection history (bounded by
    `STREAK_LOOKBACK_POINTS`, default 1000) and re-walk the same
    direction-aware quorum logic. A run older than the window renders as
    `over …`. The hot no-alert path issues no extra query.
  - New `AlertData` fields `interval_seconds` / `onset_timestamp` /
    `streak_capped`; `consecutive_count` now carries the **true** streak
    length (no longer capped at the rule threshold). New template variables:
    `{anomaly_lead}` / `{recovery_lead}` / `{interval_display}` /
    `{duration_display}` / `{onset_display}` / `{started_display}` /
    `{window_line}`. New `detectkit.utils.datetime_utils.format_duration`.

### Changed
- **Uniform message order: `description → Rule → Value/Expected`** on every
  channel and for both anomaly and recovery. Previously the anomaly message
  led with the **Rule** chip (description below it) while recovery led with the
  description; now both lead with the description and place the Rule chip right
  above the value/expected evidence it explains.
- The default anomaly/recovery text templates and the webhook / Telegram /
  email native layouts were reworked to the new lead + `Started`/`Latest`
  fields and now also show **Quorum** on Telegram and email (previously
  webhook-only). The webhook/email **Detected at** field is replaced by the
  `Started` → `Latest` (or `Cleared`) pair.
- `dtk test-alert` previews now carry the incident-timing fields, so the mock
  matches what a real firing renders.

### Notes
- Custom templates keep working unchanged; the new placeholders are additive.
  Direct-API callers that don't set `interval_seconds` fall back to the
  previous `Latest X/Y consecutive points met the quorum.` lead.

## [0.16.4] - 2026-06-20

### Fixed
- Sync the user-facing docs (`docs/`) and the README with the 0.15–0.16
  alerting changes — **docs only, no code or behavior change**:
  - **`docs/guides/configuration.md`** — corrected the `alert_help_url`
    per-channel rendering. The webhook "How to read this alert" link was still
    described as a bottom attachment field showing the **bare URL**; since
    0.16.1 it renders as a compact clickable **label** in the shared `Links`
    field (Slack `<url|label>` / Mattermost-generic markdown), never a raw URL.
  - **`docs/guides/alerting-no-data-errors.md`** — the no-data
    template-variable table now lists `{project_name}` / `{project_name_prefix}`
    (0.15.0) and `{help_url}` / `{help_line}` (0.16.0), matching the error-alert
    table; the **Visual Distinction** note now leads with the 🟡 status circle
    instead of only the amber accent color.
  - **`docs/guides/reading-alerts.md`** — the stakeholder "Anatomy of an alert"
    table gains a **Rule** row describing the rule chip set apart on every
    anomaly and recovery since 0.16.3.
  - **`docs/guides/configuration-metrics.md`** — `links` now notes the
    compact-label webhook rendering (0.16.1), and the `{help_url}` / `{help_line}`
    template variables are documented (set project-wide via `alert_help_url`).
  - **`README.md`** — added the new *Reading Alerts* stakeholder guide to the
    documentation list.

  The `dtk init-claude` assets and dev rules were already current; this only
  brings the docs site and README in line.

## [0.16.3] - 2026-06-20

### Changed
- **The firing rule is set apart consistently in every channel.** On anomaly and
  recovery alerts the configured rule now renders as a bold **Rule** label
  followed by an inline-code chip (`min_detectors=… · direction=… ·
  consecutive=…`), with the quorum explanation on its own line — so the rule
  reads as "this is the config that fired" at a glance instead of running into
  the surrounding prose. Applied across **all** default-rendered channels and to
  both alert kinds:
  - **Slack / Mattermost / generic webhook** — bold label is platform-aware
    (`*Rule*` on Slack mrkdwn, `**Rule**` on Mattermost/generic CommonMark, via
    the new `WebhookChannel._bold`); the backtick code chip renders identically
    on both.
  - **Telegram** — the rule line changed from italic (`<i>Rule: …</i>`) to
    `<b>Rule</b> <code>…</code>`.
  - **Email** — previously had **no** explicit rule line (the rule was buried in
    prose); it now renders the same bold-label + monospace chip (`_rule_html`),
    matching the other channels.
  - The landing-page channel previews were updated to match.
  Custom templates and the plain-text fallback bodies are unchanged.

## [0.16.2] - 2026-06-20

### Fixed
- **`dtk test-alert` preview now matches a real firing.** The preview was built
  without the project-name `[name]` prefix that `dtk run` stamps on every alert
  (since 0.15.0), so a preview on a shared multi-project channel read
  `🔴 Alert: <metric>` while the real alert read `🔴 [Kiss 1] Alert: <metric>`.
  `create_mock_alert_data()` now threads `project_name` from
  `detectkit_project.yml` onto the mock `AlertData`, matching the run pipeline
  (`_alert_step.py`).
- **`dtk test-alert` resolves the metrics directory from `paths.metrics`.** It
  read the deprecated top-level `metrics_path` key (ignored by `ProjectConfig`),
  so a project that customized `paths.metrics` couldn't find its metrics from
  `test-alert` — it only worked when the dir happened to be the default
  `metrics`. Closes #13.

## [0.16.1] - 2026-06-20

### Changed
- **Webhook links render as compact clickable labels, not raw URLs.** On
  Slack / Mattermost / generic webhook, `dashboard_url`, `links`, and the
  "How to read this alert" guide now share **one compact `Links` field** of
  clickable labels (`Dashboard · Runbook · How to read this alert`) instead of
  printing full URLs on their own lines. A real dashboard URL (e.g. Grafana with
  many template variables) can be a paragraph long; hiding it behind its label
  keeps the alert readable. Links use each platform's native syntax — Slack
  `<url|label>`, Mattermost/generic markdown links (detected from the webhook
  host) — via the new `WebhookChannel._link_markup`. The clickable attachment
  title (`title_link` → `dashboard_url`) and the Telegram/email link rendering
  are unchanged. The landing-page channel previews were updated to match.

## [0.16.0] - 2026-06-20

### Added
- **"How to read this alert" link on every alert.** Every default-rendered alert
  (anomaly, recovery, no-data, error) on **every** channel now carries a link to
  a plain-language guide explaining what the alert is and how to interpret it —
  so non-operator stakeholders (PMs, analysts, on-call) who see a notification
  can self-serve instead of asking what it means. It points at the new
  [Reading an alert](https://dtk.pipelab.dev/guides/reading-alerts/) docs page by
  default.
  - **New stakeholder docs page** (`docs/guides/reading-alerts.md`, rendered at
    `/guides/reading-alerts/`): a 10-second TL;DR and status-color key for
    non-technical readers, then an alert anatomy (value vs expected, severity,
    quorum, consecutive) for analysts who want the detail.
  - **Per-channel rendering:** Slack / Mattermost / webhook get a bottom
    "How to read this alert" attachment field (bare URL, auto-linkified);
    Telegram appends it to the links line; email adds a clay footer link
    (`Sent by detectkit · <project> · How to read this alert →`).
  - **Configurable per project** via `alert_help_url` in `detectkit_project.yml`
    (tri-state): unset → the official guide (default); a URL → your own
    runbook/wiki; `false` → hide the link. Resolved by
    `ProjectConfig.resolve_alert_help_url()` and stamped onto `AlertData.help_url`
    by the orchestrator (and the project-level error-alert path).
  - **Templates:** exposed as `{help_url}` (raw URL, empty when unset) and
    `{help_line}` (`How to read this alert: <url>`), mirroring the existing
    `{dashboard_url}` / `{dashboard_line}`. Direct library/API callers that don't
    set `help_url` render unchanged.

## [0.15.0] - 2026-06-20

### Added
- **Project name on every alert.** The project name (`detectkit_project.yml` →
  `name`) is now stamped onto every alert the pipeline sends and shown by
  default, so two detectkit projects pointed at the **same** channel stay
  distinguishable while both keep the default brand bot name + avatar (users no
  longer have to override `username`/`icon_url` just to tell projects apart).
  - **Title / headline / subject** of every alert kind (anomaly, recovery,
    no-data, error) leads with a `[name] ` prefix:
    `🔴 [payments] Alert: api_error_rate`.
  - **Slack / Mattermost / webhook** also pair it in the attachment footer
    (`detectkit · payments`).
  - **Telegram** carries it in the bold headline (it has no footer or
    per-message avatar to brand).
  - **Email** prefixes the subject, adds a small project eyebrow above the
    metric, and pairs it in the footer (`Sent by detectkit · payments`).
  - Exposed to custom templates everywhere as `{project_name}` and
    `{project_name_prefix}` (previously only populated for project-level error
    alerts). `AlertData.project_name` is threaded from `ProjectConfig.name`
    through the orchestrator (`_alert_step` → `AlertOrchestrator`); direct
    library/API callers that don't set it render unchanged.
  - The project `name` remains **informational only** — it keys no `_dtk_*`
    table — so it can be renamed freely (spaces allowed for a prettier label
    like `name: "Payments API"`).

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
