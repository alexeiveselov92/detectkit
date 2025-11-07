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
├── detectkit_project.yml   # Project configuration
├── profiles.yml            # Database connections
├── metrics/                # Metric definitions
│   └── .gitkeep
└── sql/                    # SQL queries
    └── .gitkeep
```

## Step 2: Configure Database Connection

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

### PostgreSQL Example

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

# SQL query to load data
query: |
  SELECT
    timestamp,
    AVG(response_time_ms) AS value
  FROM api_logs
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  consecutive_threshold: 3
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

Expected output:

```
[2024-03-15 10:00:00] Running metric: api_response_time
[2024-03-15 10:00:01] ✓ Load step completed: 288 points loaded
[2024-03-15 10:00:02] ✓ Detect step completed: 12 anomalies found
[2024-03-15 10:00:03] ✓ Alert step completed: 1 alert sent
[2024-03-15 10:00:03] ✓ Task completed successfully
```

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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
# Load data from specific date
dtk run --select api_response_time --from "2024-01-01 00:00:00"
```

### Test Alert

```bash
# Preview alert message without real anomalies
dtk test-alert --metric api_response_time
```

## Next Steps

Now that you have a working metric:

1. **Add seasonality** - [MAD Detector with Seasonality](../reference/detectors/mad.md#with-seasonality-single-component)
2. **Configure multiple detectors** - [Detectors Guide](../guides/detectors.md)
3. **Set up multiple channels** - [Alerting Guide](../guides/alerting.md)
4. **Explore examples** - [Examples](../examples/)

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
