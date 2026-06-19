# Quickstart Guide

This guide will walk you through creating your first detectkit project and monitoring a metric.

## Prerequisites

- detectkit installed ([Installation Guide](installation.md))
- Database connection (ClickHouse, PostgreSQL, or MySQL)
- Basic SQL knowledge

## Step 1: Initialize Project

Create a new detectkit project:

```bash
dtk init my_monitoring
cd my_monitoring
```

This creates the following structure:

```
my_monitoring/
├── detectkit_project.yml      # Project configuration
├── profiles.yml               # Database connections
├── README.md                  # Project readme with quick commands
├── metrics/                   # Metric definitions
│   └── example_cpu_usage.yml  # Working starter metric (mad + zscore, alerting)
└── sql/                       # SQL queries
    └── .gitkeep
```

`metrics/example_cpu_usage.yml` is a complete, runnable example — use it as a
template for your own metrics.

> **Tip — set up an AI assistant.** If you use [Claude
> Code](https://claude.com/claude-code), run `dtk init-claude` in this folder.
> It writes a `CLAUDE.md` and `.claude/rules/detectkit/` reference plus two
> skills — **`dtk-setup-project`** (walk through `profiles.yml` interactively)
> and **`dtk-new-metric`** (scaffold a metric) — so the assistant can do the
> setup below for you and help you write metrics, tune detectors and configure
> alerts. Re-run it after upgrading detectkit to refresh the context. See
> [`dtk init-claude`](../reference/cli.md#dtk-init-claude).

## Step 2: Configure Database Connection

> **Shortcut — let the assistant do it.** If you ran `dtk init-claude` (see the
> tip above), just ask Claude Code to run the **`dtk-setup-project`** skill. It
> asks for your connection details, branches on the database type, fills in the
> profile fields below for you, and verifies the result. The manual steps below
> are the same thing by hand.

Edit `profiles.yml` to add your database connection:

### ClickHouse Example

```yaml
# profiles.yml
default_profile: prod

profiles:
  prod:
    type: clickhouse
    host: localhost
    port: 9000
    user: default
    password: ""

    # Internal tables location (for _dtk_* tables)
    internal_database: analytics

    # Data tables location
    data_database: default

    settings:
      max_execution_time: 600
```

> **Edit before running.** The auto-generated `profiles.yml` ships a `dev`
> profile with **example** values — `host: localhost` and the two required
> ClickHouse locations `internal_database: detectkit` (for the `_dtk_*` tables)
> and `data_database: default` (where your source tables live). Change the host,
> port, credentials and both database names to match your environment. (There is
> no `database:` field — ClickHouse needs both `internal_database` and
> `data_database`, or the run fails with `internal_database must be set for
> ClickHouse`.)

### PostgreSQL Example

> **Not yet implemented.** PostgreSQL and MySQL are planned but not wired up
> yet — selecting `type: postgres` or `type: mysql` raises
> `PostgreSQL support coming soon` / `MySQL support coming soon`. **ClickHouse
> is the only supported backend today.** The example below shows the intended
> shape for when it lands.

```yaml
profiles:
  prod:
    type: postgres
    host: localhost
    port: 5432
    user: postgres
    password: "your_password"
    database: analytics
    internal_schema: detectkit
    data_schema: public
```

## Step 3: Create Your First Metric

Create a metric configuration file:

```bash
touch metrics/api_response_time.yml
```

Edit `metrics/api_response_time.yml`:

```yaml
# Basic metric info
name: api_response_time
interval: 5min

# SQL query to load data.
# Built-in template variables: {{ dtk_start_time }}, {{ dtk_end_time }}
# (rendered as 'YYYY-MM-DD HH:MM:SS' strings) and {{ interval_seconds }}.
query: |
  SELECT
    timestamp,
    AVG(response_time_ms) AS value
  FROM api_logs
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

# Column mapping (optional if columns match defaults)
query_columns:
  timestamp: timestamp
  metric: value

# Detector configuration
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 288      # 1 day of 5-min intervals
      min_samples: 50

# Alerting configuration
alerting:
  enabled: true
  channels:
    - mattermost_ops
  consecutive_anomalies: 3  # Require 3 anomalies in a row
  alert_cooldown: "30min"   # Recommended: without it a persisting
                            # anomaly re-alerts on every run
```

## Step 4: Configure Alert Channel

Edit `profiles.yml` to add an alert channel:

```yaml
# At the end of profiles.yml
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/your_webhook_id"
    username: "detectkit"
    icon_emoji: ":warning:"
    channel: "alerts"
```

## Step 5: Run Your Metric

Run the metric for the first time:

```bash
dtk run --select api_response_time
```

Output looks like this — a header with the project root and the metric count,
then a per-metric block (config file + steps) and the load → detect → alert
pipeline rendered as a tree, ending in a success line:

```
Project root: /path/to/my_monitoring
Found 1 metric(s) to process

Processing metric: api_response_time
  Config file: metrics/api_response_time.yml
  Steps: load, detect, alert

  ┌─ LOAD
  │   ... (load progress)
  └─ ... (detect / alert progress)

✓ Pipeline completed successfully
```

The per-step detail lines are emitted by the pipeline itself, so the exact
middle of the tree depends on how much data was loaded and how many anomalies
were found.

## Step 6: Explore Results

### View Loaded Data

Data is stored in `_dtk_datapoints` table:

```sql
SELECT *
FROM analytics._dtk_datapoints
WHERE metric_name = 'api_response_time'
ORDER BY timestamp DESC
LIMIT 10;
```

### View Detections

Anomalies are stored in `_dtk_detections` table:

```sql
SELECT
  timestamp,
  value,
  confidence_lower,
  confidence_upper,
  detection_metadata
FROM analytics._dtk_detections
WHERE metric_name = 'api_response_time'
  AND is_anomaly = true
ORDER BY timestamp DESC;
```

## Common Use Cases

### 1. Error Rate Monitoring

```yaml
name: error_rate
interval: 1min

query: |
  SELECT
    toStartOfMinute(timestamp) AS timestamp,
    countIf(status >= 500) / count() AS value
  FROM http_requests
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  - type: manual_bounds
    params:
      upper_bound: 0.01  # Alert if error rate > 1%
```

### 2. CPU Usage Monitoring

```yaml
name: cpu_usage
interval: 30s

query: |
  SELECT
    timestamp,
    avg_cpu_percent AS value
  FROM system_metrics
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  ORDER BY timestamp

detectors:
  - type: zscore
    params:
      threshold: 3.0
      window_size: 120  # 1 hour
```

### 3. Daily Active Users

```yaml
name: daily_active_users
interval: 1day

query: |
  SELECT
    toDate(timestamp) AS timestamp,
    uniqExact(user_id) AS value
  FROM user_events
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 60  # 2 months
```

## CLI Commands

### Run Specific Metrics

```bash
# Run single metric
dtk run --select api_response_time

# Run multiple metrics
dtk run --select "api_*"

# Run all metrics
dtk run --select "*"
```

### Partial Pipeline

```bash
# Only load data (skip detection)
dtk run --select api_response_time --steps load

# Only detect anomalies (skip alert)
dtk run --select api_response_time --steps load,detect
```

### Full Refresh

```bash
# Delete all data and reload from scratch
dtk run --select api_response_time --full-refresh
```

### Historical Backfill

```bash
# Load data from a specific date
dtk run --select api_response_time --from "2024-01-01 00:00:00"

# Bounded backfill: pair --from with --to to load a closed window
dtk run --select api_response_time --from "2024-01-01" --to "2024-02-01"
```

### Exclude and Force

```bash
# Run everything except a subset
dtk run --select "*" --exclude "metrics/staging/*"

# Ignore a stuck lock left by a crashed run
dtk run --select api_response_time --force
```

See the [CLI Reference](../reference/cli.md#dtk-run) for the full flag list.

### Test Alert

```bash
# Preview alert message without real anomalies
dtk test-alert api_response_time
```

### Clear a Stuck Lock

```bash
# If a run was killed without releasing its lock (e.g. the database
# restarted mid-run), later runs fail with "Failed to acquire lock".
# Clear it immediately:
dtk unlock --select api_response_time
```

Stuck locks also auto-expire after 1 hour, so the next normal run recovers on
its own — `dtk unlock` just does it right away.

### Prune Stale Data After Editing Configs

```bash
# Editing a metric's detectors/alerting leaves the old results behind.
# Preview what no longer matches the config (dry-run), then delete it:
dtk clean --select api_response_time
dtk clean --select api_response_time --execute

# Renamed or deleted a metric? Purge everything left under the old name:
dtk clean --orphaned-metrics --execute
```

See the [CLI Reference](../reference/cli.md#dtk-clean) for both modes.

## Next Steps

Now that you have a working metric:

1. **Add seasonality** - [MAD Detector with Seasonality](../reference/detectors/mad.md#with-seasonality-single-component)
2. **Handle trending metrics** - `window_weights: exponential` + `half_life`, or `detrend: linear` ([Detectors Guide](../guides/detectors.md))
3. **Configure multiple detectors** - [Detectors Guide](../guides/detectors.md)
4. **Set up multiple channels** - [Alerting Guide](../guides/alerting.md)
5. **Fan out to independent alert rules** - `alerting:` can be a *list* of alert blocks, each with its own channels, conditions and template ([Multiple alert blocks](../guides/alerting-multiple-blocks.md#multiple-alert-configurations))
6. **Explore examples** - [Examples](../examples/)

## Troubleshooting

### "Table _dtk_datapoints does not exist"

**Solution**: detectkit creates internal tables automatically on first run. Check database permissions.

### "Connection refused"

**Solution**: Verify database connection in `profiles.yml`:

```bash
# Test ClickHouse connection
clickhouse-client --host=localhost --port=9000

# Test PostgreSQL connection
psql -h localhost -U postgres -d analytics
```

### "No data loaded"

**Solution**: Check your SQL query returns data:

```sql
-- Run query manually with sample dates
SELECT
  timestamp,
  AVG(response_time_ms) AS value
FROM api_logs
WHERE timestamp >= '2024-03-01 00:00:00'
  AND timestamp < '2024-03-02 00:00:00'
GROUP BY timestamp
ORDER BY timestamp;
```

### "All points marked as insufficient_data"

**Solution**: Increase historical data range or decrease `min_samples`:

```yaml
detectors:
  - type: mad
    params:
      min_samples: 10  # Reduce from default 30
```

## Getting Help

- **Documentation**: Full guides available in [docs/](../)
- **Examples**: See [examples/](../examples/) for more configurations
- **Issues**: Report bugs at https://github.com/alexeiveselov92/detectkit/issues
