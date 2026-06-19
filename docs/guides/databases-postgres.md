# PostgreSQL

PostgreSQL (12+) is a first-class detectkit backend. It uses **schemas**: a
connection targets one `database`, and detectkit's internal tables and your data
tables live in schemas inside it.

## Install

```bash
pip install "detectkit[postgres]"   # driver: psycopg2-binary
```

## profiles.yml

```yaml
default_profile: dev

profiles:
  dev:
    type: postgres
    host: localhost
    port: 5432
    user: postgres
    password: postgres
    database: detectkit            # database to connect to (must already exist)
    internal_schema: detectkit     # schema for detectkit's own _dtk_* tables
    data_schema: public            # schema your metric source tables live in

  prod:
    type: postgres
    host: "{{ env_var('POSTGRES_HOST') }}"
    port: 5432
    user: "{{ env_var('POSTGRES_USER') }}"
    password: "{{ env_var('POSTGRES_PASSWORD') }}"
    database: "{{ env_var('POSTGRES_DB') }}"
    internal_schema: detectkit
    data_schema: public
```

| Field | Required | Notes |
|---|---|---|
| `host` / `port` | yes | default port `5432` |
| `user` / `password` | yes | |
| `database` | **yes** | the database to connect to — **must already exist** |
| `internal_schema` | yes | detectkit auto-creates the schema (`CREATE SCHEMA IF NOT EXISTS`) |
| `data_schema` | yes | schema your source tables live in |
| `settings` | no | extra `psycopg2.connect` keyword arguments |

> detectkit creates **schemas**, not the database. Create the `database` once
> (`CREATE DATABASE detectkit;`) before the first run.

## Metric query dialect

Use PostgreSQL SQL. The equivalent of a bucketed aggregate:

```sql
SELECT
  to_timestamp(floor(extract(epoch from event_time) / {{ interval_seconds }})
               * {{ interval_seconds }}) AS timestamp,
  count(*) FILTER (WHERE status_code >= 500) AS value
FROM http_requests
WHERE event_time >= '{{ dtk_start_time }}' AND event_time < '{{ dtk_end_time }}'
GROUP BY 1
ORDER BY 1
```

## How detectkit stores state

Internal tables have an **enforced primary key**; detectkit deduplicates with a
version-aware `INSERT ... ON CONFLICT DO UPDATE` (newest row wins), reproducing
the ClickHouse `ReplacingMergeTree` guarantee. No `FINAL` is ever needed — a
plain `SELECT` against a uniquely-keyed table is correct. JSON columns are stored
as `TEXT`; use the `::jsonb` cast or `->>` operators if you query them in
dashboards.

See the [Databases overview](./databases.md) and [Profiles](./configuration-profiles.md).
