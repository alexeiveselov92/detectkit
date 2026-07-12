# BigQuery

BigQuery is a **source-only** backend. A `type: bigquery` profile works
**only** as a hybrid-mode [`source_profile`](hybrid-mode.md) — the database a
metric's load SQL reads from. detectkit's own `_dtk_*` state (datapoints,
detections, task locks, alert state) **cannot** live in BigQuery; pointing
`--profile` / `default_profile` at a BigQuery profile is refused with a clear
error. Use it to *read* your governed warehouse metrics while state stays in a
cheap local database.

## Read from BigQuery, keep state local (hybrid mode)

BigQuery's on-demand pricing bills a **10 MiB minimum** of bytes processed per
query per referenced table — so detectkit's normal cadence of many small,
frequent bookkeeping queries would be billed as if each scanned 10 MiB, which
is disproportionately expensive. That's exactly what
[hybrid mode](hybrid-mode.md) is for: run the metric's load SQL on BigQuery, and
keep every `_dtk_*` table in a cheap [DuckDB](databases-duckdb.md) file,
Postgres, or ClickHouse. You get governed warehouse data with local-database
bookkeeping cost, and only the actual load query ever touches BigQuery.

This isn't optional polish — because BigQuery is source-only, hybrid mode is the
**only** way to use it. There is no "all-BigQuery" deployment; a BigQuery
profile is always paired with a state profile.

## Install

```bash
pip install "detectkit[bigquery]"   # driver: google-cloud-bigquery 3.15+
```

The BigQuery client's core dependencies are pyarrow-free, so the extra stays
light — detectkit only ever runs your metric's `SELECT` and reads the rows back.

## profiles.yml

A BigQuery profile is the metric source; a second profile (here DuckDB) holds
all state:

```yaml
default_profile: state

profiles:
  state:                          # holds every _dtk_* table
    type: duckdb
    path: "./detectkit.duckdb"
    internal_schema: detectkit
    data_schema: main

  warehouse:                      # source: metric SQL runs here, nothing else
    type: bigquery
    project: my-analytics-project              # GCP project billed for queries
    credentials_json_path: "/etc/detectkit/bq-sa.json"   # unset -> ADC
    location: EU                  # optional
    dataset: analytics            # optional (default dataset)
    settings:                     # optional QueryJobConfig attributes
      maximum_bytes_billed: 1000000000
```

| Field | Required | Notes |
|---|---|---|
| `project` | yes | GCP project id billed for the queries (e.g. `my-analytics-project`) |
| `credentials_json_path` | no | path to a service-account JSON key file; unset → Application Default Credentials |
| `location` | no | job location (e.g. `EU`); unset → BigQuery infers it from the referenced datasets |
| `dataset` | no | default dataset, so unqualified table names in the query resolve against it |
| `api_endpoint` | no | override the API endpoint — the BigQuery emulator (plain `http://`, anonymous auth; see [Testing without a GCP account](#testing-without-a-gcp-account)) or a private/regional `https://` endpoint (authenticates normally) |
| `settings` | no | extra `QueryJobConfig` attributes applied to every query (e.g. `maximum_bytes_billed`, `labels`); unknown keys are rejected at connect |

There is **no `host` / `port` / `user` / `password`** — the client resolves the
endpoint and credentials from `project` plus the auth path below, not from a
host/port/login pair. Any of those fields are simply ignored on a BigQuery
profile.

## Authentication

BigQuery has two auth paths; detectkit picks between them by whether
`credentials_json_path` is set.

- **Service-account key file** — set `credentials_json_path` to a
  service-account JSON key downloaded from the GCP console (IAM → Service
  Accounts → Keys). The service account needs `bigquery.jobs.create` on the
  project and read access to the tables your metrics query. This is the usual
  path for a server or a scheduler.
- **Application Default Credentials (ADC)** — leave `credentials_json_path`
  unset and the client resolves credentials from the ambient environment:
  gcloud ADC on a developer machine, an attached service account on a GCE/Cloud
  Run instance, or Workload Identity in GKE. Nothing to configure in
  `profiles.yml` beyond `project`.

For local development with ADC, sign in once so the client can find your
credentials:

```bash
gcloud auth application-default login
```

## Timestamps

BigQuery `TIMESTAMP` columns come back as **tz-aware UTC** datetimes; detectkit's
loader converts tz-aware values to naive UTC (since v0.62.0), so the metric grid
stays correct with no configuration. Prefer `TIMESTAMP` (or an explicit
`TIMESTAMP(...)` cast) for the column you alias to `timestamp`.

`DATETIME` columns come back **naive** and are taken verbatim — fine only if
those values are already UTC. If your bucket expression yields a `DATETIME`, cast
it to `TIMESTAMP` so the timezone is unambiguous.

## A full hybrid-mode example

Put a BigQuery source profile and a local state profile side by side, then point
a metric at the source with `source_profile`:

```yaml
# profiles.yml
default_profile: state

profiles:
  state:
    type: duckdb
    path: "./detectkit.duckdb"

  warehouse:
    type: bigquery
    project: my-analytics-project
    credentials_json_path: "/etc/detectkit/bq-sa.json"
    location: EU
    dataset: analytics            # lets the query say `orders`, not `analytics.orders`
    settings:
      maximum_bytes_billed: 1000000000
```

```yaml
# metrics/orders_per_min.yml
name: orders_per_min
interval: 1min
source_profile: warehouse         # this metric's load SQL runs on BigQuery
query: |
  SELECT
    TIMESTAMP_SECONDS(
      UNIX_SECONDS(created_at) - MOD(UNIX_SECONDS(created_at), {{ interval_seconds }})
    ) AS timestamp,
    COUNT(*) AS value
  FROM orders
  WHERE created_at >= TIMESTAMP('{{ dtk_start_time }}')
    AND created_at <  TIMESTAMP('{{ dtk_end_time }}')
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

`dtk run --select orders_per_min` reads from `warehouse` and writes
`_dtk_datapoints` (and everything else) to `state` — a single invocation, no
extra flags. Set `source_profile` at the project level instead to make every
metric read from BigQuery by default; the metric → project → unset precedence
and the full error semantics are in the [Hybrid Mode guide](hybrid-mode.md).

## Testing without a GCP account

You don't need a live GCP project to try BigQuery hybrid mode. The
[goccy/bigquery-emulator](https://github.com/goccy/bigquery-emulator) implements
enough of the BigQuery API to run detectkit against it — it is also how this
repo's integration test runs. Start it in Docker:

```bash
docker run --rm -p 9050:9050 \
  ghcr.io/goccy/bigquery-emulator:latest \
  --project=test-project --dataset=analytics
```

`--dataset` creates an empty dataset at boot; seed tables into it with
dataset-qualified DDL/DML (`CREATE TABLE analytics.events ...` — the emulator
does not apply the profile's default `dataset` to DDL/DML, only to reads).

Then point the profile at it with `api_endpoint`:

```yaml
profiles:
  warehouse:
    type: bigquery
    project: test-project
    api_endpoint: "http://localhost:9050"
```

When the `api_endpoint` is **plain `http://`** (the emulator) and no
`credentials_json_path` is set, detectkit uses anonymous credentials and skips
the ADC lookup entirely, so it works on a machine with no gcloud auth. An
`https://` endpoint override (a regional `*.rep.googleapis.com` endpoint,
Private Service Connect) is a real, authenticated Google endpoint and
authenticates normally — key file or ADC.

A **free GCP sandbox project** (no credit card) is another no-cost path — but
sandbox projects have DML disabled, so seed test tables with `bq load` rather
than `INSERT`.

## Advanced notes

- **Fail-fast connectivity probe.** Constructing a BigQuery client alone
  performs no network I/O, so detectkit runs a free `SELECT 1` probe (0 bytes
  processed on on-demand billing) when the hybrid source pool is built. A bad
  `project`, unreadable credentials, or a typo'd `settings` key surfaces
  immediately at pool build, not mid-run.
- **`settings` is a cost guardrail.** Every key under `settings` must name a
  real `QueryJobConfig` attribute (unknown keys are rejected at connect, so a
  typo can't be silently dropped). Set `maximum_bytes_billed` to cap what a
  single load query may scan, or `labels` to tag the jobs for billing
  attribution.
- **No column-name folding.** Unlike Snowflake, BigQuery preserves the case of
  column aliases, so `SELECT ts AS timestamp` reaches the loader unchanged — no
  quoting tricks, and `query_columns` values are written exactly as your alias
  spells them.
- **No tables are ever created on BigQuery.** The source contract is read-only —
  detectkit runs only your metric's `SELECT`. Every `_dtk_*` table lives in the
  state profile, so the BigQuery credentials need only `bigquery.jobs.create`
  plus read access to the tables your metrics query.
- **No `host` / `port` / `user` / `password`.** BigQuery is reached through its
  API endpoint; `project` plus the resolved credentials are the whole connection
  target.

## See also

- [Hybrid Mode](hybrid-mode.md) — the source/state split BigQuery requires, the
  full precedence rules, error semantics, and operational notes.
- [Databases overview](databases.md) — state-capable vs. source-only backends.
- [Profiles](configuration-profiles.md) — the full `profiles.yml` field
  reference.
