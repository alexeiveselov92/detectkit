# DuckDB

DuckDB is an **in-process, single-file** analytical database — no server, no
daemon, no host/port/user/password. Point a profile at a file path (or the
special value `:memory:`) and detectkit runs directly against it, in the same
process. No server, no credentials: it's the fastest way to try detectkit
locally.

Good fits:

- **Trying detectkit** — no service to provision; write a profile and
  `dtk run` immediately.
- **Local-first monitoring** — a laptop, a personal project, or an analytics
  file you already query with DuckDB.
- **CI / automated tests** — a throwaway file (or `:memory:`) per run, torn
  down with the workspace.

It is **not** a drop-in replacement for a server-backed warehouse in a team or
always-on deployment — a DuckDB file only supports one writer at a time. See
[Single writer, one process at a time](#single-writer-one-process-at-a-time)
below before pointing a scheduled `dtk run` and `dtk ui` at the same file.

## Install

```bash
pip install "detectkit[duckdb]"   # driver: duckdb 1.1+ (bundles the engine, nothing else to install)
```

DuckDB **1.1** is the floor because the alert step's `timestamp IN
%(timestamps)s` list-parameter query only parses from duckdb 1.1 — an older
version raises a syntax error at that query.

## profiles.yml

```yaml
default_profile: dev

profiles:
  dev:
    type: duckdb
    path: "./detectkit.duckdb"     # file path (created if it doesn't exist)
    internal_schema: detectkit     # schema for detectkit's own _dtk_* tables
    data_schema: main              # schema your metric source tables live in

  ci:
    type: duckdb
    path: ":memory:"                # transient — fine for a one-shot CI smoke test
    internal_schema: detectkit
    data_schema: main
```

| Field | Required | Notes |
|---|---|---|
| `path` | yes | database file path (created if it doesn't exist), or the literal `:memory:` |
| `internal_schema` | no | default `detectkit` — schema for `_dtk_*` tables (auto-created) |
| `data_schema` | no | default `main` — schema your metric source tables live in |
| `read_only` | no | default `false` — open the file read-only; see [Single writer](#single-writer-one-process-at-a-time) |
| `settings` | no | extra `duckdb.connect(..., config=...)` options, e.g. `memory_limit` |

There is no `host` / `port` / `user` / `password` — DuckDB has no server to
authenticate against; the whole connection *is* the file at `path`.

## Schemas

Like PostgreSQL, DuckDB keeps internal (`_dtk_*`) tables and your data tables
in **schemas** inside one file — set with `internal_schema` / `data_schema`.
detectkit auto-creates `internal_schema` with `CREATE SCHEMA IF NOT EXISTS`
(DuckDB's built-in `main` schema always exists and is never explicitly
created). `data_schema` defaults to `main`, so pointing detectkit at a DuckDB
file you already query is usually just a matter of setting `internal_schema`
to something dedicated (e.g. `detectkit`) — your existing tables in `main`
are untouched.

## Metric query dialect

DuckDB's SQL is close to PostgreSQL/ANSI SQL, with its own function names for
time bucketing. The equivalent of a bucketed aggregate:

```sql
SELECT
  to_timestamp(floor(epoch(event_time) / {{ interval_seconds }})
               * {{ interval_seconds }}) AS timestamp,
  count(*) FILTER (WHERE status_code >= 500) AS value
FROM http_requests
WHERE event_time >= '{{ dtk_start_time }}' AND event_time < '{{ dtk_end_time }}'
GROUP BY 1
ORDER BY 1
```

DuckDB can also query files directly (`read_parquet(...)`, `read_csv(...)`) —
useful if your "warehouse" is a directory of Parquet files rather than
tables in the DuckDB file itself.

## How detectkit stores state

Internal tables have an **enforced primary key**; detectkit deduplicates with
a version-aware `INSERT ... ON CONFLICT (...) DO UPDATE ... WHERE <table>.<version>
<= excluded.<version>` — the same "newest row wins" guarantee `ReplacingMergeTree`
gives on ClickHouse. DuckDB's `ON CONFLICT` syntax is PostgreSQL-compatible, so
this is the identical shape used on the [PostgreSQL backend](databases-postgres.md).

## Single writer, one process at a time

This is the key operational difference from the server-backed backends: **a
DuckDB file is held read-write by one process at a time.** There's no daemon
arbitrating access, so the file itself enforces it:

- A second **process** attempting a read-write attach against the same file
  fails. (Within the single writing process DuckDB itself allows multiple
  connections via MVCC — but every detectkit entry point runs in its own
  process, so the process rule is the one that matters in practice.)
- Any number of processes can open the file as **readers** at once
  (`read_only: true`), but a reader process and the writer process can never
  coexist.

**`dtk ui` and `dtk tune` hold a connection for as long as they run.** `dtk
ui`'s localhost server opens the profile's DuckDB file once at startup and
keeps that connection open for the whole session; `dtk tune` does the same
for the metric it's tuning. So a `dtk run` / `dtk autotune` / `dtk clean`
pointed at the *same* file while `dtk ui` (or a `dtk tune` session) is open
will fail to connect — and starting `dtk ui` against a file another process
already holds read-write fails the same way, in the other direction.

The supported pattern is **run-then-look**: run the pipeline to completion —
`dtk run`, `dtk autotune`, `dtk clean` — letting it close its connection when
it exits, *then* open `dtk ui` or `dtk tune` against the resulting file.
Don't run a scheduler against the same file a `dtk ui` cockpit is currently
open on. This is a property of the storage engine, not a detectkit
limitation — it's the tradeoff for zero setup: no server process arbitrating
concurrent access on your behalf.

If you need a live pipeline and a live cockpit open at the same time, use one
of the server-backed backends ([ClickHouse](databases-clickhouse.md),
[PostgreSQL](databases-postgres.md), [MySQL](databases-mysql.md)) instead —
DuckDB is best suited to local iteration, not an always-on deployment.

## `:memory:`

`path: ":memory:"` opens a transient, in-process-only database — nothing is
written to disk, and all state is lost when the process exits. That breaks
detectkit's resume-from-last-timestamp idempotency across separate `dtk run`
invocations (there is no "last timestamp" to resume from — the next run
starts from scratch), so treat it as **tests/preview-only**: a quick smoke
test, a CI job that doesn't need to persist anything, or kicking the tires on
detectkit for the first time. Use a real file `path` for anything you intend
to run more than once.

See the [Databases overview](./databases.md) and [Profiles](./configuration-profiles.md).
