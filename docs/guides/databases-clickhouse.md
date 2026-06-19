# ClickHouse

ClickHouse is detectkit's original backend, ideal for large analytical event
tables. It connects over the **native protocol** (default port `9000`, not the
`8123` HTTP port).

## Install

```bash
pip install "detectkit[clickhouse]"   # driver: clickhouse-driver
```

## profiles.yml

ClickHouse uses two **databases** — there is no `database:` field:

```yaml
default_profile: dev

profiles:
  dev:
    type: clickhouse
    host: localhost
    port: 9000                 # native protocol
    user: default
    password: ""
    internal_database: detectkit   # detectkit's own _dtk_* tables
    data_database: default         # where your metric source tables live

  prod:
    type: clickhouse
    host: "{{ env_var('CLICKHOUSE_HOST') }}"
    port: 9000
    user: "{{ env_var('CLICKHOUSE_USER') }}"
    password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"
    internal_database: detectkit
    data_database: monitoring
```

| Field | Required | Notes |
|---|---|---|
| `host` / `port` | yes | `port` is the native protocol (9000), not HTTP (8123) |
| `user` / `password` | yes | |
| `internal_database` | yes | detectkit auto-creates it on first run |
| `data_database` | yes | your source tables |
| `settings` | no | passed through to the driver (e.g. `max_execution_time`) |

## Metric query dialect

Use ClickHouse SQL in your metric queries. A typical bucketed aggregate:

```sql
SELECT
  toStartOfInterval(event_time, INTERVAL {{ interval_seconds }} SECOND) AS timestamp,
  countIf(status_code >= 500) AS value
FROM http_requests
WHERE event_time >= '{{ dtk_start_time }}' AND event_time < '{{ dtk_end_time }}'
GROUP BY timestamp
ORDER BY timestamp
```

## How detectkit stores state

Internal tables use `ReplacingMergeTree`, which collapses duplicate primary keys
by a version column (`created_at` / `updated_at`) **at merge time**. detectkit
handles this for you; it only matters if you query the `_dtk_*` tables directly
for dashboards — see [Visualizing results](./visualizing-results.md) for when to
add `FINAL` and the ClickHouse-specific JSON/date functions.

See the [Databases overview](./databases.md) and [Profiles](./configuration-profiles.md)
for the full picture.
