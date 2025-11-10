# detectkit Quick Start

Quick guide to get started with detectkit for anomaly detection and alerting.

## Installation

```bash
# Install from source (for now)
git clone https://github.com/alexeiveselov92/detectkit.git
cd detectkit
pip install -e .

# Install with ClickHouse support
pip install -e ".[clickhouse]"
```

## Quick Start

### 1. Initialize Project

```bash
dtk init my_monitoring_project
cd my_monitoring_project
```

This creates:
```
my_monitoring_project/
├── detectkit_project.yml   # Project configuration
├── profiles.yml            # Database & alert channel configs
├── metrics/                # Metric definitions
│   └── example_cpu_usage.yml
└── sql/                    # SQL queries (optional)
```

### 2. Configure Database Connection

Edit `profiles.yml`:

```yaml
dev:
  type: clickhouse
  host: localhost
  port: 9000
  user: default
  password: ""

  internal_database: detectkit_internal  # For _dtk_* tables
  data_database: default                 # Your metrics data

alert_channels:
  mattermost_alerts:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
    username: detectkit
```

Set environment variable:
```bash
export MATTERMOST_WEBHOOK_URL="https://mattermost.example.com/hooks/xxx"
```

### 3. Create Metric Configuration

Create `metrics/cpu_usage.yml`:

```yaml
name: cpu_usage
description: Monitor CPU usage anomalies

# SQL query
query: |
  SELECT
    timestamp,
    cpu_usage as value
  FROM system.metrics
  WHERE metric_name = 'cpu_usage'
    AND timestamp >= {from_date}
    AND timestamp < {to_date}
  ORDER BY timestamp

# Time interval
interval: 1min

# Anomaly detectors
detectors:
  - type: zscore
    params:
      threshold: 3.0
      window_size: 100

  - type: mad
    params:
      threshold: 3.0

# Alerting
alerting:
  enabled: true
  channels:
    - mattermost_alerts
  consecutive_anomalies: 3
  alert_cooldown: "30min"  # v0.3.0: Prevent alert spam
```

### 4. Run Pipeline

```bash
# Run full pipeline (load + detect + alert)
dtk run --select cpu_usage

# Run only specific steps
dtk run --select cpu_usage --steps load,detect

# Load data from specific date
dtk run --select cpu_usage --from 2024-01-01

# Run all metrics with tag
dtk run --select tag:critical
```

## Available Detectors

### Statistical Detectors

**Z-Score Detector**
```yaml
- type: zscore
  params:
    threshold: 3.0        # Standard deviations
    window_size: 100      # Rolling window
    min_samples: 30       # Minimum samples needed
```

**MAD (Median Absolute Deviation)**
```yaml
- type: mad
  params:
    threshold: 3.0        # MAD multiples
    window_size: 100
    min_samples: 30
```

**IQR (Interquartile Range)**
```yaml
- type: iqr
  params:
    threshold: 1.5        # IQR multiples
    window_size: 100
    min_samples: 30
```

**Manual Bounds**
```yaml
- type: manual_bounds
  params:
    lower_bound: 0
    upper_bound: 100
```

## Alert Channels

### Mattermost

```yaml
mattermost_alerts:
  type: mattermost
  webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
  username: detectkit
  icon_url: https://example.com/icon.png
```

### Slack

```yaml
slack_alerts:
  type: slack
  webhook_url: "{{ env_var('SLACK_WEBHOOK_URL') }}"
  channel: "#alerts"
  username: detectkit
```

### Generic Webhook

```yaml
webhook_alerts:
  type: webhook
  url: "{{ env_var('WEBHOOK_URL') }}"
  method: POST
  headers:
    Authorization: "Bearer {{ env_var('API_TOKEN') }}"
```

## Python API

You can also use detectkit directly in Python:

```python
from detectkit.config.metric_config import MetricConfig
from detectkit.config.profile import ProfilesConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.orchestration.task_manager import TaskManager, PipelineStep

# Load configurations
profiles_config = ProfilesConfig.from_yaml("profiles.yml")
metric_config = MetricConfig.from_yaml_file("metrics/cpu_usage.yml")

# Create managers
db_manager = profiles_config.create_manager()
internal_manager = InternalTablesManager(db_manager)
internal_manager.initialize_tables()

# Create task manager
task_manager = TaskManager(
    internal_manager=internal_manager,
    db_manager=db_manager,
    profiles_config=profiles_config,
)

# Run pipeline
result = task_manager.run_metric(
    config=metric_config,
    steps=[PipelineStep.LOAD, PipelineStep.DETECT, PipelineStep.ALERT],
)

print(f"Status: {result['status']}")
print(f"Datapoints: {result['datapoints_loaded']}")
print(f"Anomalies: {result['anomalies_detected']}")
print(f"Alerts: {result['alerts_sent']}")
```

## Environment Variables

detectkit supports environment variable interpolation in configs:

```yaml
# Both formats supported
webhook_url: "${MATTERMOST_WEBHOOK_URL}"
webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
```

Common variables:
- `MATTERMOST_WEBHOOK_URL` - Mattermost webhook
- `SLACK_WEBHOOK_URL` - Slack webhook
- `CLICKHOUSE_HOST` - Database host
- `CLICKHOUSE_USER` - Database user
- `CLICKHOUSE_PASSWORD` - Database password

## Testing

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=detectkit --cov-report=html

# Test specific module
pytest tests/unit/test_detectors.py -v
```

## What's Next?

1. **Add more metrics**: Create `.yml` files in `metrics/` directory
2. **Configure alerts**: Add more channels in `profiles.yml`
3. **Schedule runs**: Use cron to run `dtk run` periodically
4. **Monitor**: Check internal tables `_dtk_datapoints`, `_dtk_detections`, `_dtk_tasks`

## Example: Production Setup

```yaml
# profiles.yml
prod:
  type: clickhouse
  host: "{{ env_var('CLICKHOUSE_HOST') }}"
  port: 9000
  user: "{{ env_var('CLICKHOUSE_USER') }}"
  password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"
  internal_database: detectkit_prod
  data_database: analytics

alert_channels:
  mattermost_critical:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_CRITICAL_WEBHOOK') }}"
    username: detectkit-prod

  slack_warnings:
    type: slack
    webhook_url: "{{ env_var('SLACK_WEBHOOK') }}"
    channel: "#monitoring-warnings"
```

```bash
# Crontab: run every 10 minutes
*/10 * * * * cd /path/to/project && dtk run --select tag:critical --profile prod
```

## Troubleshooting

**"Connection refused" error:**
- Check that ClickHouse is running: `docker ps`
- Verify connection: `clickhouse-client --host localhost --port 9000`

**"Profile not found" error:**
- Check `profiles.yml` exists in project root
- Verify profile name matches `--profile` argument

**"No metrics found" error:**
- Check metrics exist in `metrics/` directory
- Verify metric name or tag selector

**Alerts not sending:**
- Verify webhook URL is correct
- Check environment variables are set
- Look for error messages in output

## Documentation

- GitHub: https://github.com/alexeiveselov92/detectkit
- Issues: https://github.com/alexeiveselov92/detectkit/issues
