# Databases

detectkit is **database-agnostic**: metrics, detectors and alerting work the
same way regardless of where your data lives. Three backends are supported as
first-class, fully working targets:

| | ClickHouse | PostgreSQL | MySQL / MariaDB |
|---|---|---|---|
| **Status** | Supported | Supported | Supported |
| **Install extra** | `detectkit[clickhouse]` | `detectkit[postgres]` | `detectkit[mysql]` / `detectkit[mariadb]` |
| **Driver** | `clickhouse-driver` | `psycopg2-binary` | `pymysql` |
| **Default port** | `9000` (native) | `5432` | `3306` |
| **Min version** | 20.3+ | 12+ | MySQL 8.0+, MariaDB 10.4+ |
| **Location model** | two **databases** | one database, two **schemas** | two **databases** |
| **`profiles.yml` location fields** | `internal_database`, `data_database` | `database` + `internal_schema`, `data_schema` | `internal_database`, `data_database` |
| **Internal dedup** | `ReplacingMergeTree` (version-collapse) | enforced PK + `ON CONFLICT` upsert | enforced PK + `ON DUPLICATE KEY UPDATE` (MariaDB: `VALUES()` form) |

The MySQL backend covers both engines: `type: mysql` and `type: mariadb` are
interchangeable aliases, and the actual vendor is auto-detected at connect —
see the [MySQL guide → MariaDB](databases-mysql.md#mariadb).

Install everything at once with `detectkit[all-db]`.

## How detectkit uses the database

detectkit keeps two kinds of tables apart:

- **Internal tables** (`_dtk_*`) — datapoints, detections, task locks, alert
  state. detectkit owns and auto-creates these in the **internal location**.
- **Your data** — the source tables your metric SQL reads from, in the **data
  location**.

The "location" is a *database* on ClickHouse and MySQL, and a *schema* on
PostgreSQL (a PostgreSQL connection targets one `database`, and the internal/data
tables live in schemas inside it).

The same logical guarantee — at most one row per primary key, newest wins — is
delivered by `ReplacingMergeTree` on ClickHouse and by an **enforced primary key
plus a version-aware upsert** on PostgreSQL/MySQL. You don't configure any of
this; detectkit picks the right strategy per backend.

## Pick your backend

- **[ClickHouse](./databases-clickhouse.md)** — the original target; ideal for
  large analytical event tables.
- **[PostgreSQL](./databases-postgres.md)** — schema-based; the database must
  already exist, detectkit creates the schemas.
- **[MySQL](./databases-mysql.md)** — database-based; requires MySQL 8.0+ or
  MariaDB 10.4+ (`type: mysql` or the `type: mariadb` alias).

Only the **connection** and the **SQL dialect of your metric queries** differ
between backends — detectors, alerting, the CLI and the project layout are
identical. See [Profiles](./configuration-profiles.md) for the full field
reference and [Installation](../getting-started/installation.md) for the driver
extras.
