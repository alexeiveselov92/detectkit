# Hybrid Mode

Cloud warehouses — Snowflake, BigQuery, Redshift, and similar — typically bill
per query or per second of compute. detectkit's normal operating pattern is
the opposite of what that billing model rewards: every `dtk run` does a lot of
small, frequent writes to its own bookkeeping — `_dtk_datapoints`,
`_dtk_detections`, task locks, alert state — on top of the one query that
actually reads your metric. Pointed entirely at a warehouse, that bookkeeping
alone can rack up real cost.

**Hybrid mode** splits the two: your metric's SQL still runs against the
warehouse (the **source**), but every `_dtk_*` table — all of detectkit's own
state — lives in a separate, cheap database (the **state** profile): a local
[DuckDB](databases-duckdb.md) file, a small Postgres/MySQL instance, whatever
you already run. You get warehouse data with local-database bookkeeping costs.

Hybrid mode is entirely opt-in. Leave it unset and nothing changes — one
profile runs everything, exactly as before.

## Configuring it

`source_profile` names a `profiles.yml` profile whose database runs a
metric's SQL. Everything else — `_dtk_datapoints`, `_dtk_detections`,
`_dtk_tasks`, `_dtk_alert_states`, `_dtk_metrics` — stays in the **state**
profile: the one `dtk run` (or `dtk run --profile <name>`) is already
connected to for everything else.

**Any** profile can be a source — a full state-capable backend (ClickHouse,
PostgreSQL, MySQL/MariaDB, DuckDB) doubles as one. Some backends are
**source-only**: they can *only* be a `source_profile`, never hold state.
[Snowflake](databases-snowflake.md) (`type: snowflake`) and
[BigQuery](databases-bigquery.md) (`type: bigquery`) are the two today —
pointing `--profile` / `default_profile` at either is refused with a clear error
(see [Fail-fast below](#fail-fast-validation)).

Set it at the **project level** (`detectkit_project.yml`) when most metrics
share one warehouse, and/or at the **metric level** to override it for a
single metric. Resolution is **metric → project → unset**, the same
precedence [`loading_delay`](configuration-metrics.md#loading_delay-string-or-int-optional)
uses. Unset on both means hybrid mode is off for that metric — its SQL runs
through the state profile, like every other step.

```yaml
# profiles.yml
default_profile: state

profiles:
  state:                         # holds every _dtk_* table
    type: duckdb
    path: "./detectkit.duckdb"
    internal_schema: detectkit
    data_schema: main

  warehouse:                     # source: metric SQL runs here, nothing else
    type: clickhouse
    host: clickhouse.example.com
    port: 9000
    user: readonly
    password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"
    internal_database: detectkit   # required by the profile schema, but unused
    data_database: analytics       # in hybrid mode — see the note below
```

```yaml
# detectkit_project.yml
name: my_monitoring
default_profile: state
source_profile: warehouse        # every metric's SQL runs against `warehouse`
                                  # by default; a metric can still override it
```

```yaml
# metrics/api_errors.yml
name: api_errors
interval: 1min
query: |
  SELECT timestamp, error_count AS value
  FROM logs
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  ORDER BY timestamp
# source_profile: warehouse      # optional here — only needed to override the
                                  # project default, or to point THIS metric at
                                  # a different source than the rest
detectors:
  - type: mad
    params:
      threshold: 3.0
alerting:
  enabled: true
  channels: [mattermost_ops]
```

`dtk run --select api_errors` now reads from `warehouse` and writes
`_dtk_datapoints` (and everything else) to `state` — a single invocation, no
extra flags.

### A Snowflake source

Because [Snowflake](databases-snowflake.md) is source-only, hybrid mode is the
only way to use it: the metric's SQL runs on Snowflake while state lives in a
local DuckDB file.

```yaml
# profiles.yml
default_profile: state

profiles:
  state:                          # holds every _dtk_* table
    type: duckdb
    path: "./detectkit.duckdb"
    internal_schema: detectkit
    data_schema: main

  snowflake_wh:                   # source-only: metric SQL runs here, nothing else
    type: snowflake
    account: "ab12345.eu-central-1"
    user: DETECTKIT_SVC
    private_key_path: "./keys/detectkit_rsa_key.p8"   # key-pair auth (recommended)
    private_key_passphrase: "{{ env_var('SNOWFLAKE_KEY_PASSPHRASE') }}"
    warehouse: MONITORING_WH
    database: ANALYTICS
    schema: PUBLIC
```

```yaml
# metrics/orders_per_min.yml
name: orders_per_min
interval: 1min
source_profile: snowflake_wh      # this metric's load SQL runs on Snowflake
query: |
  SELECT
    TIME_SLICE(created_at, {{ interval_seconds }}, 'SECOND') AS timestamp,
    COUNT(*) AS value
  FROM orders
  WHERE created_at >= '{{ dtk_start_time }}'
    AND created_at <  '{{ dtk_end_time }}'
  GROUP BY 1
  ORDER BY 1
detectors:
  - type: mad
    params: { threshold: 3.0 }
alerting:
  enabled: true
  channels: [mattermost_ops]
```

See the [Snowflake guide](databases-snowflake.md) for key-pair setup, the
UTC session pin, and the uppercase column-folding note.

### A BigQuery source

Because [BigQuery](databases-bigquery.md) is source-only, hybrid mode is the
only way to use it: the metric's SQL runs on BigQuery while state lives in a
local DuckDB file.

```yaml
# profiles.yml
default_profile: state

profiles:
  state:                          # holds every _dtk_* table
    type: duckdb
    path: "./detectkit.duckdb"
    internal_schema: detectkit
    data_schema: main

  bigquery_wh:                    # source-only: metric SQL runs here, nothing else
    type: bigquery
    project: my-analytics-project                        # GCP project billed for queries
    credentials_json_path: "/etc/detectkit/bq-sa.json"   # unset -> Application Default Credentials
    location: EU                                          # optional job location
    dataset: analytics                                   # optional default dataset
    settings:
      maximum_bytes_billed: 1000000000                   # optional cost guardrail
```

```yaml
# metrics/orders_per_min.yml
name: orders_per_min
interval: 1min
source_profile: bigquery_wh       # this metric's load SQL runs on BigQuery
query: |
  SELECT
    TIMESTAMP_TRUNC(created_at, MINUTE) AS timestamp,
    COUNT(*) AS value
  FROM orders
  WHERE created_at >= '{{ dtk_start_time }}'
    AND created_at <  '{{ dtk_end_time }}'
  GROUP BY 1
  ORDER BY 1
detectors:
  - type: mad
    params: { threshold: 3.0 }
alerting:
  enabled: true
  channels: [mattermost_ops]
```

See the [BigQuery guide](databases-bigquery.md) for credential setup, the
`TIMESTAMP`-vs-`DATETIME` note, and the `maximum_bytes_billed` cost guardrail.

> Don't confuse `source_profile` with the metric-level `profile:` field.
> `profile:` predates hybrid mode, is unrelated to it, and is not applied at
> runtime by `dtk run` today (it's only round-tripped by the `dtk autotune`
> config emitter). `source_profile` is the live one.

## What runs where

| Step / command | Reads/writes | Profile used |
|---|---|---|
| **load** — metric SQL query | your source tables | resolved `source_profile` (falls back to state) |
| **load** — saving `_dtk_datapoints` | detectkit state | state (always) |
| **detect** | `_dtk_datapoints` → `_dtk_detections` | state (always) |
| **alert** | `_dtk_detections` → `_dtk_alert_states` + channels | state (always) |
| `dtk run --report` | `_dtk_*` (replays stored data) | state (always) |
| `dtk autotune`, `dtk tune`, `dtk ui`, `dtk clean`, `dtk unlock` | `_dtk_*` | state (always) — none of these read `source_profile` |

Hybrid mode touches exactly one thing: the query that fetches a metric's raw
points during **load**. Every other step, and every other command, only ever
opens the state profile — so tuning, browsing reports, or cleaning stale
detector generations for a hybrid metric needs no warehouse credentials at
all, only the state profile's.

## Error semantics

A load-step failure is wrapped differently depending on which side it comes
from, so an alert (or a log line) tells you which database is actually down:

- A failure running the metric's SQL against the **source** profile raises
  `SourceDatabaseError`, whose message leads with
  `source database (profile '<name>'): <original error>` — e.g. `source
  database (profile 'warehouse'): OperationalError: connection refused`.
- A failure saving to `_dtk_datapoints` (or any other `_dtk_*` write) is a
  plain, unwrapped exception — it's the same **state** connection every other
  step already uses, so there's nothing to disambiguate.

If [project-level `error_alerting`](configuration.md#error_alerting-object-optional)
is enabled, both cases still fire the same project error alert; only the
`{error_type}` / `{error_message}` differ (`SourceDatabaseError` vs. the
original exception type), so the alert itself tells you whether to page
whoever owns the warehouse or whoever owns the state database.

### Fail-fast validation

`dtk run` also validates every selected metric's resolved `source_profile`
against `profiles.yml` **before opening any database connection**, regardless
of `--steps` — an unknown profile name fails the whole run immediately with
exit code `1` (a config typo, so it deliberately does *not* page
`error_alerting` — that channel is reserved for DB-down/DDL/runtime failures)
instead of surfacing deep inside whichever metric's load step happens to hit
it first.

Pointing `--profile` / `default_profile` (the **state** profile) at a
source-only type such as `snowflake` or `bigquery` is refused the same way, with
a clear error — a source-only backend can never hold `_dtk_*` state, so it's
rejected up front rather than failing mid-run when detectkit tries to create a
table.

## Operational notes

- **One connection per source profile, per run.** The first metric that
  resolves to a given `source_profile` opens it; every later metric sharing
  that same profile name reuses the same connection instead of opening a new
  one. All pooled source connections close when `dtk run` exits.
- **A failed source connection is not retried per metric.** If a
  `source_profile` fails to connect, that failure is cached and re-raised for
  every subsequent metric referencing it in the same run — detectkit doesn't
  hammer a down warehouse once per metric.
- **No duplicate connection when source equals state.** If a metric's
  resolved `source_profile` happens to name the same profile `dtk run` is
  already using for state (explicitly, or because both resolve to
  `default_profile`), detectkit reuses the existing connection rather than
  opening a second one to the same database.
- **detect/alert-only runs never touch the source.** `dtk run --steps
  detect,alert` (skipping `load`) never resolves or connects a
  `source_profile` at all — hybrid mode is purely a load-step concern.
- **Connecting a full-type (state-capable) profile issues `CREATE
  DATABASE`/`CREATE SCHEMA IF NOT EXISTS` for both its locations** — that is
  how every state backend manager connects, hybrid or not. So a
  clickhouse/postgres/mysql/duckdb profile used as a source still needs its
  `internal_database` / `internal_schema` field set to something the
  connecting credentials can touch, even though hybrid mode never writes a
  `_dtk_*` row there. Point it at an existing schema/database the source
  credentials are allowed to reach, or grant `CREATE`. On DuckDB, setting
  `read_only: true` on the source profile skips this DDL entirely — the
  cleanest choice for a source you only ever read from. **Source-only types
  (Snowflake, BigQuery) run no DDL at all**: they connect and read, need no
  `internal_*`/`data_*` locations, and never create anything on the
  warehouse.
- **A DuckDB source is still subject to the single-writer rule.** If the
  source profile is itself a DuckDB file, the [single-writer
  caveat](databases-duckdb.md#single-writer-one-process-at-a-time) applies to
  that file exactly as it would outside hybrid mode.

## See Also

- [Databases](databases.md) — backend overview and per-backend guides.
- [Configuration → `source_profile`](configuration.md#source_profile-string-optional) —
  the project-level field.
- [Configuring Metrics → `source_profile`](configuration-metrics.md#source_profile-string-optional) —
  the per-metric override.
- [Profiles](configuration-profiles.md) — the full `profiles.yml` field
  reference.
