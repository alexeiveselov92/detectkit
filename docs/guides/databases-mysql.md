# MySQL

MySQL (**8.0+**) is a first-class detectkit backend. Like ClickHouse it uses
**databases** (MySQL has no separate schema concept). MySQL 8.0 is required for
the row-alias upsert detectkit uses to deduplicate internal state.

## Install

```bash
pip install "detectkit[mysql]"   # driver: pymysql
```

## profiles.yml

```yaml
default_profile: dev

profiles:
  dev:
    type: mysql
    host: localhost
    port: 3306
    user: root
    password: ""
    internal_database: detectkit   # database for detectkit's own _dtk_* tables
    data_database: analytics       # database your metric source tables live in

  prod:
    type: mysql
    host: "{{ env_var('MYSQL_HOST') }}"
    port: 3306
    user: "{{ env_var('MYSQL_USER') }}"
    password: "{{ env_var('MYSQL_PASSWORD') }}"
    internal_database: detectkit
    data_database: monitoring
```

| Field | Required | Notes |
|---|---|---|
| `host` / `port` | yes | default port `3306` |
| `user` / `password` | yes | the user needs `CREATE` to auto-create the databases |
| `internal_database` | yes | detectkit auto-creates it (`CREATE DATABASE IF NOT EXISTS`) |
| `data_database` | yes | database your source tables live in |
| `database` | no | optional default database for the connection |
| `settings` | no | extra `pymysql.connect` keyword arguments |

> Requires **MySQL 8.0+**. detectkit deduplicates internal state with the row
> alias form `INSERT ... AS new ON DUPLICATE KEY UPDATE`, introduced in 8.0.19.

## MariaDB

MariaDB is **fully supported** through this same MySQL backend — same driver
(`pymysql`), same connection fields, same table/DDL layout. The one internal
difference: the row-alias upsert form above (`INSERT ... AS new ON DUPLICATE
KEY UPDATE`) isn't available on MariaDB, so detectkit **auto-detects the
server vendor** at connect (`SELECT VERSION()`) and falls back to the classic
`VALUES(col)` form there instead:

```sql
INSERT INTO t (...) VALUES (...)
ON DUPLICATE KEY UPDATE col = VALUES(col), ...
```

You don't configure this — it's picked automatically per connection.

Use the `type: mariadb` alias for clarity (identical semantics to
`type: mysql`):

```yaml
profiles:
  prod:
    type: mariadb
    host: "{{ env_var('MARIADB_HOST') }}"
    port: 3306
    user: "{{ env_var('MARIADB_USER') }}"
    password: "{{ env_var('MARIADB_PASSWORD') }}"
    internal_database: detectkit
    data_database: analytics
```

`type: mysql` against a MariaDB server works too — vendor detection is by the
live server, not the profile `type`.

```bash
pip install "detectkit[mariadb]"   # same pymysql driver as detectkit[mysql]
```

`dtk init --db-type mariadb` scaffolds a project with a `type: mariadb`
profile. Tested against **MariaDB 11.x** in the integration matrix; MariaDB
10.4+ is expected to work.

## Metric query dialect

Use MySQL SQL. The equivalent of a bucketed aggregate:

```sql
SELECT
  FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(event_time) / {{ interval_seconds }})
                * {{ interval_seconds }}) AS timestamp,
  SUM(status_code >= 500) AS value
FROM http_requests
WHERE event_time >= '{{ dtk_start_time }}' AND event_time < '{{ dtk_end_time }}'
GROUP BY 1
ORDER BY 1
```

## How detectkit stores state

Internal tables have an **enforced primary key**; detectkit deduplicates with a
version-aware `INSERT ... ON DUPLICATE KEY UPDATE` (newest row wins), reproducing
the ClickHouse `ReplacingMergeTree` guarantee. JSON columns are stored as `TEXT`;
use `JSON_EXTRACT(...)` if you query them in dashboards.

See the [Databases overview](./databases.md) and [Profiles](./configuration-profiles.md).
