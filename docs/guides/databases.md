# Databases

detectkit is **database-agnostic**: metrics, detectors and alerting work the
same way regardless of where your data lives. Four backends are supported as
first-class, fully working targets:

| | ClickHouse | PostgreSQL | MySQL / MariaDB | DuckDB |
|---|---|---|---|---|
| **Status** | Supported | Supported | Supported | Supported |
| **Install extra** | `detectkit[clickhouse]` | `detectkit[postgres]` | `detectkit[mysql]` / `detectkit[mariadb]` | `detectkit[duckdb]` |
| **Driver** | `clickhouse-driver` | `psycopg2-binary` | `pymysql` | `duckdb` |
| **Default port** | `9000` (native) | `5432` | `3306` | — (in-process, no server) |
| **Min version** | 20.3+ | 12+ | MySQL 8.0+, MariaDB 10.4+ | 1.1+ |
| **Location model** | two **databases** | one database, two **schemas** | two **databases** | one file, two **schemas** |
| **`profiles.yml` location fields** | `internal_database`, `data_database` | `database` + `internal_schema`, `data_schema` | `internal_database`, `data_database` | `path` + `internal_schema`, `data_schema` |
| **Internal dedup** | `ReplacingMergeTree` (version-collapse) | enforced PK + `ON CONFLICT` upsert | enforced PK + `ON DUPLICATE KEY UPDATE` (MariaDB: `VALUES()` form) | enforced PK + `ON CONFLICT` upsert (same shape as PostgreSQL) |

The MySQL backend covers both engines: `type: mysql` and `type: mariadb` are
interchangeable aliases, and the actual vendor is auto-detected at connect —
see the [MySQL guide → MariaDB](databases-mysql.md#mariadb).

DuckDB is the odd one out in this table: it's an **in-process, single-file**
database, not a server — there's no host/port to connect to, and it supports
only one read-write connection at a time. See the [DuckDB guide → Single
writer](databases-duckdb.md#single-writer-one-process-at-a-time) before
relying on it for anything beyond local use or CI.

Install everything at once with `detectkit[all-db]` (every state backend plus
the Snowflake and BigQuery source drivers, DuckDB included).

## Source-only backends (hybrid mode)

The four backends above are **state-capable** (five profile types — MySQL and
MariaDB share one backend): any of them can hold detectkit's
own `_dtk_*` tables *and* run your metric SQL. A second, smaller class is
**source-only** — usable only as a hybrid-mode
[`source_profile`](hybrid-mode.md) (the database a metric's load SQL reads
from), never as a place to store state:

- **[Snowflake](./databases-snowflake.md)** — a governed cloud warehouse. A
  `type: snowflake` profile can only be a metric source; detectkit refuses it as
  a state profile with a clear error. Because Snowflake bills each warehouse
  resume with a 60-second minimum, hybrid mode (read from Snowflake, keep state
  in a cheap local database) is the only way to use it — see its guide and the
  [Hybrid Mode guide](./hybrid-mode.md).
- **[BigQuery](./databases-bigquery.md)** — Google's serverless warehouse. A
  `type: bigquery` profile can only be a metric source; detectkit refuses it as
  a state profile with a clear error. Because on-demand queries bill a 10 MiB
  minimum of bytes processed per referenced table, frequent small monitoring
  queries are disproportionately expensive — hybrid mode (read from BigQuery,
  keep state in a cheap local database) is the way to use it — see its guide and
  the [Hybrid Mode guide](./hybrid-mode.md).

## How detectkit uses the database

detectkit keeps two kinds of tables apart:

- **Internal tables** (`_dtk_*`) — datapoints, detections, task locks, alert
  state. detectkit owns and auto-creates these in the **internal location**.
- **Your data** — the source tables your metric SQL reads from, in the **data
  location**.

The "location" is a *database* on ClickHouse and MySQL, and a *schema* on
PostgreSQL and DuckDB (a PostgreSQL connection targets one `database`; a
DuckDB connection targets one file at `path` — either way the internal/data
tables live in schemas inside it).

The same logical guarantee — at most one row per primary key, newest wins — is
delivered by `ReplacingMergeTree` on ClickHouse and by an **enforced primary key
plus a version-aware upsert** on PostgreSQL/MySQL/DuckDB. You don't configure
any of this; detectkit picks the right strategy per backend.

## Pick your backend

- **[ClickHouse](./databases-clickhouse.md)** — the original target; ideal for
  large analytical event tables.
- **[PostgreSQL](./databases-postgres.md)** — schema-based; the database must
  already exist, detectkit creates the schemas.
- **[MySQL](./databases-mysql.md)** — database-based; requires MySQL 8.0+ or
  MariaDB 10.4+ (`type: mysql` or the `type: mariadb` alias).
- **[DuckDB](./databases-duckdb.md)** — no server, no credentials; a single
  local file. The fastest way to try detectkit or run it in CI, but only one
  process can write to the file at a time — see its single-writer caveat
  before using it alongside a long-running `dtk ui`. A `path: "md:<database>"`
  attaches [MotherDuck](./databases-duckdb.md#motherduck) — DuckDB's serverless
  cloud — as a full state backend through the same profile type (served, so the
  single-writer caveat doesn't apply); see the DuckDB guide.
- **[Snowflake](./databases-snowflake.md)** — **source-only** (hybrid mode);
  runs a metric's load SQL, never holds detectkit state.
- **[BigQuery](./databases-bigquery.md)** — **source-only** (hybrid mode);
  runs a metric's load SQL, never holds detectkit state.

Only the **connection** and the **SQL dialect of your metric queries** differ
between backends — detectors, alerting, the CLI and the project layout are
identical. See [Profiles](./configuration-profiles.md) for the full field
reference and [Installation](../getting-started/installation.md) for the driver
extras.

## Reading from one backend, storing state in another

By default, one profile does everything: it runs your metric SQL *and* holds
every `_dtk_*` table. **Hybrid mode** splits the two — a metric's SQL runs
against one profile (the source, e.g. a billed-per-query warehouse like
[Snowflake](./databases-snowflake.md) or [BigQuery](./databases-bigquery.md))
while all `_dtk_*` state stays in a separate, cheaper profile (e.g. a local
DuckDB file). Source-only backends such as Snowflake and BigQuery can be used
*only* this way. See the [Hybrid Mode
guide](./hybrid-mode.md) for the full config, what runs where, and the
operational caveats.
