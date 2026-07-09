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

> **Fastest path:** let Claude Code set it up for you — run `dtk init-claude`,
> then the **`dtk-setup-project`** skill configures `profiles.yml` interactively
> for your database. See
> [Quickstart → Fastest start](getting-started/quickstart.md#fastest-start-set-up-with-an-ai-assistant).

```bash
# Initialize project
dtk init my_monitoring
cd my_monitoring

# (Optional) Set up Claude Code context for working with detectkit
dtk init-claude

# Edit profiles.yml (add database connection)

# Create metric config
cat > metrics/cpu_usage.yml <<EOF
name: cpu_usage
interval: 1min
query: "SELECT timestamp, cpu_percent AS value FROM system_metrics WHERE timestamp >= '{{ dtk_start_time }}' AND timestamp < '{{ dtk_end_time }}' ORDER BY timestamp"

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

> **Not sure which detector or threshold to use?** After loading some history,
> let `dtk autotune` pick the detector type, hyperparameters and seasonality for
> you — see [Auto-tuning](guides/autotuning.md).

## Documentation Structure

### Getting Started
- **[Installation](getting-started/installation.md)** - Install detectkit and dependencies
- **[Quickstart](getting-started/quickstart.md)** - Create your first metric

### Guides
- **[Configuration](guides/configuration.md)** - Complete configuration reference
- **[Detectors](guides/detectors.md)** - Choosing and configuring detectors
- **[Auto-tuning](guides/autotuning.md)** - Let `dtk autotune` pick the detector, params and seasonality for you
- **[Tuning by hand](guides/tuning.md)** - Interactively tune a detector on its real data and write it back (`dtk tune`, the manual sibling of autotune)
- **[Alerting](guides/alerting.md)** - Setting up alerts and notifications
- **[Reading an alert](guides/reading-alerts.md)** - For stakeholders who receive alerts: what they mean and what to do
- **[Visualizing results](guides/visualizing-results.md)** - Build dashboards/charts on the `_dtk_*` tables in any BI tool
- **[Project UI](guides/project-ui.md)** - Project-wide monitoring cockpit — overview, pipeline control, metric management
- **[Semantic layer (OSI)](guides/osi.md)** - `ai_context` KPI grounding on any metric (no OSI model needed); plus `dtk osi` import/export as a forward bridge to a governed OSI semantic layer

### Reference
- **[CLI Reference](reference/cli.md)** - Command-line interface documentation
- **[Auto-tune Reference](reference/autotune.md)** - `dtk autotune` flags, labels schema, `autotune:` block, scoring metrics
- **[Internal Tables](reference/internal-tables.md)** - Schema of the `_dtk_*` tables (columns, primary keys, engines)
- **[Detectors](reference/detectors/)** - Detector-specific documentation
  - [Shared Parameters](reference/detectors/shared-parameters.md) — preprocessing, weighting, detrending, identity (MAD/Z-Score/IQR)
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

### Statistical Detectors

Multiple detector types for different data patterns:

- **MAD** - Robust, general-purpose, supports seasonality
- **Z-Score** - Fast, sensitive on normal distributions
- **IQR** - Excellent for skewed distributions
- **Manual Bounds** - Simple threshold-based detection

All windowed detectors (MAD, Z-Score, IQR) also support recency weighting
(`window_weights` + `half_life`) and robust linear detrending (`detrend`)
for metrics with a gradual trend.

[Learn more →](guides/detectors.md)

### Seasonality Support

Handle time-based patterns automatically:

```yaml
seasonality_columns:
  - hour
  - day_of_week

detectors:
  - type: mad
    params:
      seasonality_components:
        - ["hour", "day_of_week"]
```

[Learn more →](reference/detectors/mad.md#with-seasonality-single-component)

### Multi-Channel Alerting

Send alerts to multiple platforms:

- **Mattermost** - Team collaboration
- **Slack** - Team notifications
- **Telegram** - Mobile alerts
- **Email** - Traditional notifications
- **Webhook** - Generic HTTP endpoint

```yaml
alerting:
  channels:
    - mattermost_ops
    - slack_critical
    - email_oncall
  min_detectors: 1            # Quorum: detectors that must agree per point
  consecutive_anomalies: 3    # Require confirmation
  direction: "up"             # Only alert on increases
  alert_cooldown: "2h"        # Recommended: without it a persisting anomaly re-alerts every run
  notify_on_recovery: true    # Send a follow-up when the metric recovers
  no_data_alert: false        # Alert when expected data is missing
  # suppress_until: "2026-07-01"  # Mute this config until a date
  mentions:                   # Users/groups to @-mention
    - "@oncall"
```

Define multiple independent blocks by giving `alerting:` a list — each block
has its own channels and conditions, and keeps independent cooldown/recovery
state:

```yaml
alerting:
  - enabled: true
    channels:
      - mattermost_ops
    consecutive_anomalies: 3

  - enabled: true
    channels:
      - slack_critical
    consecutive_anomalies: 1   # More sensitive for this channel
    direction: "up"            # Only upward anomalies
```

[Learn more →](guides/alerting.md)

### Efficient Processing

- **Batch processing** - Handle large datasets efficiently
- **Incremental loading** - Only load new data
- **Idempotent operations** - Safe to re-run
- **numpy-based detectors** - numpy core, no pandas (windowed detectors use a
  per-point loop — fine incrementally, slower for large backfills)

### Database Support

Works with your existing data warehouse — all three backends are first-class:

- **ClickHouse** - native protocol, `detectkit[clickhouse]`
- **PostgreSQL** - 12+, `detectkit[postgres]`
- **MySQL** - 8.0+, `detectkit[mysql]`

Only the connection and the SQL dialect of your metric queries differ; detectors,
alerting and the CLI are identical. See the [Databases guide](guides/databases.md)
for the per-backend breakdown.

## Architecture

```
   dtk run
      │
      ▼
   ┌──────────────────────────────────────────────────┐
   │  Pipeline orchestration                          │
   │  load  →  detect  →  alert                       │
   └──────────────────────────────────────────────────┘
      │
      ├─▶  Data source   ClickHouse query, gap-filled to the grid
      ├─▶  Detectors     MAD · Z-Score · IQR · manual_bounds
      └─▶  Channels      Mattermost · Slack · Telegram · Email · Webhook
      │
      ▼
   ┌──────────────────────────────────────────────────┐
   │  Internal _dtk_* tables                          │
   │    _dtk_datapoints   loaded points               │
   │    _dtk_detections   detection results           │
   │    _dtk_tasks        run / lock state            │
   └──────────────────────────────────────────────────┘
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

### Recovery

```bash
# Clear a stuck lock left by a crashed run (e.g. DB restarted mid-run)
dtk unlock --select cpu_usage
```

### Cleanup After Editing Configs

```bash
# Prune detector/alert data orphaned by a config change (dry-run by default)
dtk clean --select cpu_usage
dtk clean --select cpu_usage --execute

# Purge data for metrics no longer defined in the project
dtk clean --orphaned-metrics --execute
```

### Project Cockpit

```bash
# Open the project-wide cockpit: watch every metric's alerts/freshness/quality,
# run/autotune/unlock or launch dtk tune per metric, and create/edit/delete
# metric YAMLs — all from the browser
dtk ui
```

### Claude Code Context

```bash
# Scaffold AI-assistant context (CLAUDE.md, rules, skills) so Claude Code
# can help create metrics, tune detectors and run the pipeline. The content
# ships with detectkit and is idempotent — re-run it after upgrading.
dtk init-claude
```

[Full CLI Reference →](reference/cli.md)

## Configuration Files

detectkit uses three main configuration files:

### 1. `detectkit_project.yml`

Project-level settings:

```yaml
name: my_monitoring
version: '1.0'

default_profile: prod

tables:
  datapoints: _dtk_datapoints
  detections: _dtk_detections
  tasks: _dtk_tasks

timeouts:
  load: 1800      # 30 minutes
  detect: 3600    # 1 hour
  alert: 300      # 5 minutes
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
| [MAD](reference/detectors/mad.md) | General-purpose, seasonal data | High | Yes | Fast |
| [Z-Score](reference/detectors/zscore.md) | Normal distributions | Low | Yes | Very Fast |
| [IQR](reference/detectors/iqr.md) | Skewed distributions | High | Yes | Fast |
| [Manual Bounds](reference/detectors/manual_bounds.md) | Known thresholds | N/A | No | Fastest |

[Choosing a Detector →](guides/detectors.md)

## Performance

Detectors are fast enough for routine incremental runs, so choose primarily on
accuracy. Note that the windowed detectors (MAD, Z-Score, IQR) use a per-point
loop, which is fine incrementally but can be slow for large historical
backfills over big windows.

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
  - hour

detectors:
  - type: mad
    params:
      seasonality_components:
        - "hour"
```

### 3. Handle Trending Metrics

If your metric has a gradual trend (slow growth or decline), use recency
weighting and/or detrending so the drift itself is not flagged:

```yaml
detectors:
  - type: mad
    params:
      window_weights: exponential
      half_life: "3d"     # weight halves every 3 days of age
      detrend: linear     # optional: remove in-window linear trend
```

### 4. Use Consecutive Anomalies

Reduce false positives:

```yaml
alerting:
  consecutive_anomalies: 3  # Wait for confirmation
```

### 5. Filter by Direction

Only alert on meaningful changes:

```yaml
alerting:
  direction: "up"    # Only alert on increases (e.g., errors, latency)
  # direction: "down"  # Or only on decreases (e.g., users, revenue)
```

### 6. Test Before Production

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

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please:
1. Open an issue to discuss changes
2. Fork and create pull request
3. Ensure tests pass
4. Follow existing code style

## Changelog

See [CHANGELOG.md](../CHANGELOG.md) for complete version history.

---

**[Get Started →](getting-started/quickstart.md)**
