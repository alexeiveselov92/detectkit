# detectkit Quick Start

Quick guide to get started with detectkit for anomaly detection and alerting.
The full version of this guide lives in
[docs/getting-started/quickstart.md](docs/getting-started/quickstart.md).

## Installation

```bash
pip install detectkit

# With a database driver
pip install detectkit[clickhouse]   # ClickHouse
pip install detectkit[postgres]     # PostgreSQL
pip install detectkit[mysql]        # MySQL
pip install detectkit[all-db]       # All databases
```

See the [Installation Guide](docs/getting-started/installation.md) for details.

## Step 1: Initialize Project

```bash
dtk init my_monitoring
cd my_monitoring
```

This creates:

```
my_monitoring/
├── detectkit_project.yml   # Project configuration
├── profiles.yml            # Database connections & alert channels
├── metrics/                # Metric definitions
└── sql/                    # SQL queries (optional)
```

## Step 2: Configure Database Connection

Edit `profiles.yml`:

```yaml
default_profile: prod

profiles:
  prod:
    type: clickhouse
    host: localhost
    port: 9000
    user: default
    password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"

    internal_database: detectkit_internal  # For _dtk_* tables
    data_database: default                 # Your metrics data

alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
    username: detectkit
```

Both `${VAR}` and `{{ env_var('VAR') }}` environment variable syntaxes are
supported, so secrets stay out of YAML:

```bash
export MATTERMOST_WEBHOOK_URL="https://mattermost.example.com/hooks/xxx"
```

## Step 3: Create Your First Metric

Create `metrics/api_response_time.yml`:

```yaml
name: api_response_time
interval: 5min

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

detectors:
  - type: mad
    params:
      threshold: 3.0        # in sigma-equivalents
      window_size: 288      # 1 day of 5-min points
      min_samples: 50

alerting:
  enabled: true
  channels:
    - mattermost_ops
  consecutive_anomalies: 3  # Require 3 anomalies in a row
  alert_cooldown: "30min"   # Recommended: without it a persisting
                            # anomaly re-alerts on every run
```

## Step 4: Run the Pipeline

```bash
# Full pipeline (load + detect + alert)
dtk run --select api_response_time

# Partial pipeline
dtk run --select api_response_time --steps load,detect

# Load data from a specific date
dtk run --select api_response_time --from "2024-01-01"

# Run all metrics with a tag
dtk run --select tag:critical

# Delete all data and reload from scratch
dtk run --select api_response_time --full-refresh
```

## Step 5: Test Alerts and Recover from Locks

```bash
# Preview the alert message without real anomalies
dtk test-alert api_response_time
```

If a run is killed without releasing its lock (e.g. the database restarts
mid-run), later runs fail with `Failed to acquire lock`. Clear it immediately:

```bash
dtk unlock --select api_response_time
```

A stuck lock also auto-expires after 1 hour, so the next normal run recovers
on its own.

## Step 6: Explore Results

Loaded data is stored in `_dtk_datapoints`, detections in `_dtk_detections`:

```sql
SELECT timestamp, value, confidence_lower, confidence_upper
FROM detectkit_internal._dtk_detections
WHERE metric_name = 'api_response_time'
  AND is_anomaly = true
ORDER BY timestamp DESC;
```

## Available Detectors

```yaml
detectors:
  - type: zscore            # mean/std interval
    params:
      threshold: 3.0        # standard deviations
      window_size: 100      # trailing window in points
      min_samples: 30

  - type: mad               # robust median/MAD interval
    params:
      threshold: 3.0        # sigma-equivalents (MAD scaled by 1.4826)
      window_size: 100

  - type: iqr               # quartile-based interval
    params:
      threshold: 1.5        # IQR multiples
      window_size: 100

  - type: manual_bounds     # fixed thresholds
    params:
      lower_bound: 0
      upper_bound: 100
```

For metrics with a gradual trend, add recency weighting and/or detrending so
the slow drift itself is not flagged:

```yaml
seasonality_columns:
  - hour                     # extracted automatically from timestamps

detectors:
  - type: mad
    params:
      window_size: 8640      # 60 days of 10-min points
      seasonality_components: ["hour"]
      window_weights: exponential
      half_life: "3d"        # adapt to the new normal over ~3 days
      detrend: linear        # optional: remove in-window linear trend
```

See the [Detectors Guide](docs/guides/detectors.md) for all parameters.

## Scheduling

```bash
# Crontab: run every 10 minutes
*/10 * * * * cd /path/to/project && dtk run --select tag:critical
```

## What's Next?

1. **Add more metrics**: create `.yml` files in `metrics/`
2. **Add seasonality**: [MAD Detector with Seasonality](docs/reference/detectors/mad.md#with-seasonality-single-component)
3. **Configure alerts**: [Alerting Guide](docs/guides/alerting.md)
4. **Full configuration reference**: [Configuration Guide](docs/guides/configuration.md)
5. **CLI reference**: [CLI Reference](docs/reference/cli.md)

## Troubleshooting

**"Connection refused"** — check the database is running and `profiles.yml`
connection settings are correct.

**"Profile not found"** — check `profiles.yml` exists in the project root and
the profile name matches `default_profile` or the `--profile` argument.

**"No metrics found"** — check metric files exist in `metrics/` and the
selector matches (metric name without `.yml`, path pattern, or `tag:<name>`).

**"Failed to acquire lock"** — a previous run crashed with the lock held; run
`dtk unlock --select <metric>` (or wait — locks auto-expire after 1 hour).

**Alerts not sending** — verify webhook URLs, environment variables, and try
`dtk test-alert <metric>`.

## Documentation

- Full docs: [docs/](docs/README.md)
- GitHub: https://github.com/alexeiveselov92/detectkit
- Issues: https://github.com/alexeiveselov92/detectkit/issues
