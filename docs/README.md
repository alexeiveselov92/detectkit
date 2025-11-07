# detectkit Documentation

**detectkit** - Metric monitoring with automatic anomaly detection.

A Python library and CLI tool for data analysts and engineers to monitor time-series metrics with automatic anomaly detection and multi-channel alerting.

## Quick Links

- **[Installation](getting-started/installation.md)** - Install detectkit
- **[Quickstart](getting-started/quickstart.md)** - Create your first metric in 5 minutes
- **[Examples](examples/)** - Common monitoring scenarios
- **[CLI Reference](reference/cli.md)** - Complete CLI documentation

## Getting Started

### Installation

```bash
pip install detectkit[clickhouse]
```

### First Metric

```bash
# Initialize project
dtk init my_monitoring
cd my_monitoring

# Edit profiles.yml (add database connection)

# Create metric config
cat > metrics/cpu_usage.yml <<EOF
name: cpu_usage
interval: 1min
query: "SELECT timestamp, cpu_percent AS value FROM system_metrics WHERE timestamp >= %(from_date)s AND timestamp < %(to_date)s ORDER BY timestamp"

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 1440

alerting:
  enabled: true
  channels:
    - mattermost_ops
EOF

# Run
dtk run --select cpu_usage
```

## Documentation Structure

### Getting Started
- **[Installation](getting-started/installation.md)** - Install detectkit and dependencies
- **[Quickstart](getting-started/quickstart.md)** - Create your first metric

### Guides
- **[Configuration](guides/configuration.md)** - Complete configuration reference
- **[Detectors](guides/detectors.md)** - Choosing and configuring detectors
- **[Alerting](guides/alerting.md)** - Setting up alerts and notifications

### Reference
- **[CLI Reference](reference/cli.md)** - Command-line interface documentation
- **[Detectors](reference/detectors/)** - Detector-specific documentation
  - [MAD Detector](reference/detectors/mad.md)
  - [Z-Score Detector](reference/detectors/zscore.md)
  - [IQR Detector](reference/detectors/iqr.md)
  - [Manual Bounds Detector](reference/detectors/manual_bounds.md)

### Examples
- **[Examples](examples/)** - Real-world monitoring scenarios
  - Infrastructure monitoring (CPU, memory, disk)
  - Application monitoring (latency, errors, throughput)
  - Business metrics (users, revenue, conversions)
  - Advanced patterns (seasonality, multi-detector)

## Key Features

### 🎯 Statistical Detectors

Multiple detector types for different data patterns:

- **MAD** - Robust, general-purpose, supports seasonality
- **Z-Score** - Fast, sensitive on normal distributions
- **IQR** - Excellent for skewed distributions
- **Manual Bounds** - Simple threshold-based detection

[Learn more →](guides/detectors.md)

### 📅 Seasonality Support

Handle time-based patterns automatically:

```yaml
seasonality_columns:
  - name: hour_of_day
    extract: hour
  - name: day_of_week
    extract: dow

detectors:
  - type: mad
    params:
      seasonality_components:
        - ["hour_of_day", "day_of_week"]
```

[Learn more →](reference/detectors/mad.md#with-seasonality-single-component)

### 🔔 Multi-Channel Alerting

Send alerts to multiple platforms:

- **Mattermost** - Team collaboration
- **Slack** - Team notifications
- **Telegram** - Mobile alerts
- **Email** - Traditional notifications

```yaml
alerting:
  channels:
    - mattermost_ops
    - slack_critical
    - email_oncall
  consecutive_anomalies: 3  # Require confirmation
  direction: "up"             # Only alert on increases
```

[Learn more →](guides/alerting.md)

### ⚡ Efficient Processing

- **Batch processing** - Handle large datasets efficiently
- **Incremental loading** - Only load new data
- **Idempotent operations** - Safe to re-run
- **Fast detectors** - 1,400-3,000 points/second

### 🗄️ Database Support

Works with your existing data warehouse:

- **ClickHouse** (recommended)
- **PostgreSQL**
- **MySQL**

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     detectkit CLI                        │
│                       (dtk run)                          │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│                  Pipeline Orchestration                   │
│  ┌────────┐      ┌────────┐      ┌─────────┐            │
│  │  Load  │  →   │ Detect │  →   │  Alert  │            │
│  └────────┘      └────────┘      └─────────┘            │
└──────────────────────────────────────────────────────────┘
               │                │              │
               ▼                ▼              ▼
┌──────────────────┐  ┌──────────────┐  ┌──────────────┐
│   Data Source    │  │  Detectors   │  │   Channels   │
│   (ClickHouse)   │  │  (MAD, etc)  │  │  (Mattermost)│
└──────────────────┘  └──────────────┘  └──────────────┘
               │                │
               ▼                ▼
┌──────────────────────────────────────┐
│         Internal Tables              │
│  • _dtk_datapoints (loaded data)     │
│  • _dtk_detections (anomalies)       │
│  • _dtk_tasks (execution state)      │
└──────────────────────────────────────┘
```

## Use Cases

### Infrastructure Monitoring

Monitor system resources:

```yaml
# CPU, memory, disk, network
detectors:
  - type: manual_bounds
    params:
      upper_bound: 90.0
  - type: zscore
    params:
      threshold: 3.0
```

[Example →](examples/README.md#example-1-cpu-usage-monitoring)

### Application Monitoring

Track application health:

```yaml
# Response time, error rate, throughput
detectors:
  - type: iqr
    params:
      threshold: 1.5
      window_size: 1440
```

[Example →](examples/README.md#example-4-api-response-time-monitoring)

### Business Metrics

Monitor KPIs:

```yaml
# Users, revenue, conversions
detectors:
  - type: mad
    params:
      threshold: 3.0
      seasonality_components:
        - "day_of_week"
```

[Example →](examples/README.md#example-7-daily-active-users)

## Common Workflows

### Daily Monitoring

```bash
# Run all metrics (typically in cron)
dtk run --select "*"
```

### Partial Pipeline

```bash
# Load data only
dtk run --select cpu_usage --steps load

# Detect without loading new data
dtk run --select cpu_usage --steps detect
```

### Historical Backfill

```bash
# Load last 30 days
dtk run --select cpu_usage --from "2024-01-01"
```

### Testing

```bash
# Test alert channels
dtk test-alert cpu_usage
```

[Full CLI Reference →](reference/cli.md)

## Configuration Files

detectkit uses three main configuration files:

### 1. `detectkit_project.yml`

Project-level settings:

```yaml
project_name: my_monitoring
default_profile: prod
paths:
  metrics_dir: metrics
  sql_dir: sql
```

### 2. `profiles.yml`

Database connections and alert channels:

```yaml
profiles:
  prod:
    type: clickhouse
    host: localhost
    port: 9000
    internal_database: analytics
    data_database: default

alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
```

### 3. `metrics/*.yml`

Individual metric definitions:

```yaml
name: cpu_usage
interval: 1min
query: "..."

detectors:
  - type: mad
    params:
      threshold: 3.0

alerting:
  enabled: true
  channels:
    - mattermost_ops
```

[Full Configuration Guide →](guides/configuration.md)

## Detector Comparison

| Detector | Best For | Robustness | Seasonality | Speed |
|----------|----------|------------|-------------|-------|
| [MAD](reference/detectors/mad.md) | General-purpose, seasonal data | ✅ High | ✅ Yes | Fast |
| [Z-Score](reference/detectors/zscore.md) | Normal distributions | ❌ Low | ❌ No | Very Fast |
| [IQR](reference/detectors/iqr.md) | Skewed distributions | ✅ High | ❌ No | Fast |
| [Manual Bounds](reference/detectors/manual_bounds.md) | Known thresholds | N/A | ❌ No | Fastest |

[Choosing a Detector →](guides/detectors.md)

## Performance

Approximate detection speeds (including I/O):

- **Manual Bounds**: ~3,000 points/second
- **Z-Score**: ~1,800 points/second
- **MAD**: ~1,500 points/second
- **IQR**: ~1,400 points/second

All detectors are fast enough for production use. Choose based on accuracy, not performance.

## Best Practices

### 1. Start with MAD

MAD is a safe default for most metrics:

```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 100
```

### 2. Add Seasonality for Time-Based Patterns

If your metric varies by hour/day/week:

```yaml
seasonality_columns:
  - name: hour_of_day
    extract: hour

detectors:
  - type: mad
    params:
      seasonality_components:
        - "hour_of_day"
```

### 3. Use Consecutive Anomalies

Reduce false positives:

```yaml
alerting:
  consecutive_anomalies: 3  # Wait for confirmation
```

### 4. Filter by Direction

Only alert on meaningful changes:

```yaml
alerting:
  direction: "up"  # Only alert on increases (e.g., errors, latency)
  direction: "down"  # Only alert on decreases (e.g., users, revenue)
```

### 5. Test Before Production

```bash
# Test query
dtk run --select my_metric --steps load

# Test detection
dtk run --select my_metric --steps detect

# Test alert
dtk test-alert my_metric
```

[More Best Practices →](guides/detectors.md#best-practices)

## Troubleshooting

### No Alerts Received

Check:
1. `alerting.enabled: true`
2. Recent anomalies detected (query `_dtk_detections`)
3. Consecutive threshold met
4. Webhook URLs correct

```bash
dtk test-alert my_metric
```

### Too Many False Positives

Solutions:
1. Increase `threshold` parameter
2. Increase `consecutive_anomalies`
3. Add `seasonality_components` (if metric is seasonal)
4. Use `direction` filter

[Full Troubleshooting →](guides/detectors.md#troubleshooting)

## Getting Help

- **Documentation**: You're reading it!
- **Issues**: https://github.com/alexeiveselov92/detectkit/issues
- **PyPI**: https://pypi.org/project/detectkit/

## Project Status

**Version**: 0.1.0 (initial release)

**Status**: Production-ready

- ✅ Core features implemented
- ✅ 287/288 tests passing (99.7%)
- ✅ Published to PyPI
- ✅ Tested in production

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please:
1. Open an issue to discuss changes
2. Fork and create pull request
3. Ensure tests pass
4. Follow existing code style

## Changelog

### 0.1.0 (2024-03-15)

Initial release:
- ✅ Statistical detectors (MAD, Z-Score, IQR, Manual Bounds)
- ✅ Seasonality support (MAD detector)
- ✅ Multi-channel alerting (Mattermost, Slack, Telegram, Email)
- ✅ Database support (ClickHouse, PostgreSQL, MySQL)
- ✅ Batch processing and incremental loading
- ✅ CLI tool (`dtk`)
- ✅ Complete documentation

---

**[Get Started →](getting-started/quickstart.md)**
