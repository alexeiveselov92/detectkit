# Snowflake

Snowflake is a **source-only** backend. A `type: snowflake` profile works
**only** as a hybrid-mode [`source_profile`](hybrid-mode.md) — the database a
metric's load SQL reads from. detectkit's own `_dtk_*` state (datapoints,
detections, task locks, alert state) **cannot** live in Snowflake; pointing
`--profile` / `default_profile` at a Snowflake profile is refused with a clear
error. Use it to *read* your governed warehouse metrics while state stays in a
cheap local database.

## Read from Snowflake, keep state local (hybrid mode)

Snowflake bills each warehouse resume with a **60-second minimum** — so
detectkit's normal cadence of many small, frequent bookkeeping writes is
disproportionately expensive against it. That's exactly what
[hybrid mode](hybrid-mode.md) is for: run the metric's load SQL on Snowflake,
and keep every `_dtk_*` table in a cheap [DuckDB](databases-duckdb.md) file,
Postgres, or ClickHouse. You get governed warehouse data with
local-database bookkeeping cost.

This isn't optional polish — because Snowflake is source-only, hybrid mode is
the **only** way to use it. There is no "all-Snowflake" deployment; a Snowflake
profile is always paired with a state profile.

## Install

```bash
pip install "detectkit[snowflake]"   # driver: snowflake-connector-python 3.12+
```

## profiles.yml

A Snowflake profile is the metric source; a second profile (here DuckDB) holds
all state:

```yaml
default_profile: state

profiles:
  state:                          # holds every _dtk_* table
    type: duckdb
    path: "./detectkit.duckdb"
    internal_schema: detectkit
    data_schema: main

  snowflake_wh:                   # source: metric SQL runs here, nothing else
    type: snowflake
    account: "ab12345.eu-central-1"       # your Snowflake account identifier
    user: DETECTKIT_SVC
    private_key_path: "./keys/detectkit_rsa_key.p8"   # key-pair auth (recommended)
    private_key_passphrase: "{{ env_var('SNOWFLAKE_KEY_PASSPHRASE') }}"
    warehouse: MONITORING_WH      # optional
    database: ANALYTICS           # optional
    schema: PUBLIC                # optional (maps to the session schema)
    role: DETECTKIT_ROLE          # optional
```

| Field | Required | Notes |
|---|---|---|
| `account` | yes | Snowflake account identifier (e.g. `ab12345.eu-central-1`) |
| `user` | yes | login name; must be set explicitly |
| `private_key_path` | one of | path to a PEM private key for key-pair auth |
| `private_key_passphrase` | no | passphrase for the key (env-interpolatable) |
| `password` | one of | password auth; provide this **or** `private_key_path` |
| `warehouse` | no | virtual warehouse to run queries on |
| `database` | no | default database for the session |
| `schema` | no | default schema for the session (YAML key `schema`) |
| `role` | no | role to assume for the session |
| `settings` | no | extra Snowflake session parameters (merged over detectkit's) |

There is **no `host` / `port`** — Snowflake connects via the account-based
endpoint, not a host/port pair. Passwords and passphrases support the usual
`{{ env_var('...') }}` interpolation, so no secret has to be committed.

Then point a metric (or the whole project) at it with `source_profile`:

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
    params:
      threshold: 3.0
alerting:
  enabled: true
  channels: [mattermost_ops]
```

`dtk run --select orders_per_min` reads from `snowflake_wh` and writes
`_dtk_datapoints` (and everything else) to `state` — a single invocation, no
extra flags. Set `source_profile` at the project level instead to make every
metric read from Snowflake by default; see the
[Hybrid Mode guide](hybrid-mode.md).

## Key-pair authentication (recommended)

Snowflake is retiring password-only sign-in for service accounts through 2026,
so **key-pair auth is the recommended path**; a password still works as an
interim measure. To set up a key pair:

```bash
# 1. Generate an encrypted PEM private key
openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 aes-256-cbc -inform PEM \
  -out detectkit_rsa_key.p8
# (you'll be prompted for the passphrase you reference via env_var above)

# 2. Derive the matching public key
openssl rsa -in detectkit_rsa_key.p8 -pubout -out detectkit_rsa_key.pub
```

Then register the public key on the Snowflake user (strip the PEM header/footer
and newlines from the `.pub` contents first):

```sql
ALTER USER DETECTKIT_SVC SET RSA_PUBLIC_KEY='MIIBIjANBgkq...';
```

Point `private_key_path` at the `.p8` file and pass its passphrase via
`private_key_passphrase` (interpolated from an environment variable, so the
secret stays out of `profiles.yml`). To use a password instead, set `password`
and omit both key fields.

## Advanced notes

- **Session timezone is pinned to UTC.** detectkit sets the connection's
  `TIMEZONE` session parameter to `UTC`. Snowflake otherwise coerces
  `TIMESTAMP_LTZ` / `CURRENT_TIMESTAMP` through the session default
  (`America/Los_Angeles`), which would shift the timestamps your metric SQL
  returns. detectkit handles tz-aware UTC results in the loader, so the grid
  stays correct. To override, set `settings: {TIMEZONE: "..."}` — an explicit
  user choice merges over the UTC default and wins.
- **Uppercase column folding.** Snowflake uppercases unquoted identifiers, so
  `SELECT ... AS value` comes back as a column named `VALUE`. detectkit folds
  any **all-uppercase** column name to lowercase in the returned rows, so the
  loader reads `timestamp` / `value` without you quoting anything. A
  deliberately-quoted mixed-case name (e.g. `AS "myValue"`) passes through
  unchanged. Because the fold applies to every all-uppercase name (quoted or
  not), custom `query_columns` values must be written in the **folded
  lowercase** form — `query_columns: {timestamp: event_time, metric: cnt}`,
  not the uppercase names a Snowflake worksheet displays.
- **No tables are ever created on Snowflake.** The source contract is
  read-only — detectkit runs only your metric's `SELECT`. Every `_dtk_*` table
  lives in the state profile, so the Snowflake credentials need only read
  access to the tables your metrics query.
- **No `host` / `port`.** Snowflake is reached through its account-based
  endpoint; the account identifier is the whole connection target.

## See also

- [Hybrid Mode](hybrid-mode.md) — the source/state split Snowflake requires,
  the full precedence rules, error semantics, and operational notes.
- [Databases overview](databases.md) — state-capable vs. source-only backends.
- [Profiles](configuration-profiles.md) — the full `profiles.yml` field
  reference.
