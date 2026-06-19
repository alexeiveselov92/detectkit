# detectkit

[![PyPI version](https://img.shields.io/pypi/v/detectkit.svg)](https://pypi.org/project/detectkit/)
[![Python](https://img.shields.io/pypi/pyversions/detectkit.svg)](https://pypi.org/project/detectkit/)

**Metric monitoring with automatic anomaly detection.**

`detectkit` is a Python library for data analysts and engineers to monitor time-series metrics with automatic anomaly detection and alerting. dbt-like project structure and CLI.

## Features

- **Pure numpy arrays** — no pandas dependency in core logic
- **Statistical detectors** — Z-Score, MAD, IQR, Manual Bounds
- **Trend & seasonality handling** — seasonality grouping, recency weighting (`half_life`), robust linear detrending for slowly drifting metrics
- **Multi-channel alerting** — Mattermost, Slack, Telegram, Email, Webhook
- **@mentions** — tag users/groups in alerts, each channel formats natively
- **Alert lifecycle** — consecutive anomalies, cooldown, recovery notifications, no-data alerts
- **Project-level error alerts** — catch DB outages and pipeline crashes once per run
- **Database agnostic** — ClickHouse, PostgreSQL, MySQL
- **Idempotent** — resume from interruptions, no duplicate processing
- **CLI** — `dtk init`, `dtk run --select`, `dtk unlock`, `dtk clean`, tag-based selectors
- **AI-native onboarding** — `dtk init-claude` sets up Claude Code context (CLAUDE.md + rules + a metric-scaffolding skill) so an assistant can help you build metrics out of the box

## Installation

```bash
pip install detectkit
```

With database drivers:

```bash
pip install detectkit[clickhouse]   # ClickHouse
pip install detectkit[all-db]       # All databases
```

## Quick Start

### CLI (Recommended)

```bash
# Create project
dtk init my_monitoring
cd my_monitoring

# Optional: set up Claude Code context so an AI assistant can help you
# write metrics, tune detectors and configure alerts (re-run after upgrades)
dtk init-claude

# Configure database in profiles.yml, then:
dtk run --select cpu_usage
dtk run --select tag:critical
dtk run --select cpu_usage --steps load,detect
dtk run --select cpu_usage --from 2024-01-01

# Clear a stuck lock left by a crashed run (e.g. DB restarted mid-run)
dtk unlock --select cpu_usage

# Prune data orphaned by config edits (dry-run; add --execute to apply)
dtk clean --select cpu_usage
```

### Metric Configuration

```yaml
# metrics/api_errors.yml
name: api_error_rate
interval: "5min"

query: |
  SELECT
    toStartOfInterval(timestamp, INTERVAL 5 MINUTE) AS timestamp,
    countIf(status_code >= 500) / count() * 100 AS value
  FROM http_requests
  WHERE timestamp >= '{{ dtk_start_time }}' AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp ORDER BY timestamp

detectors:
  - type: mad
    params:
      threshold: 3.0                 # in sigma-equivalents
      window_size: 2016              # 7 days of 5-min points
      window_weights: exponential    # optional: favor recent data
      half_life: "1d"                # weight halves every day of age

alerting:
  enabled: true
  channels: [mattermost_ops]
  consecutive_anomalies: 3
  direction: "up"
  mentions: [oncall_engineer, here]
  alert_cooldown: "30min"
  notify_on_recovery: true
  suppress_until: "2026-04-11 18:00:00"  # Suppress alerts until this UTC time
```

### Python API

```python
import numpy as np
from detectkit.detectors.statistical import ZScoreDetector

detector = ZScoreDetector(threshold=3.0, window_size=100)
results = detector.detect({
    'timestamp': np.array([...], dtype='datetime64[ms]'),
    'value': np.array([1.0, 2.0, 1.5, 10.0, 1.8]),
})

for r in results:
    if r.is_anomaly:
        print(f"Anomaly at {r.timestamp}: {r.value}")
```

## Documentation

- [Getting Started](docs/getting-started/quickstart.md) — 5-minute quickstart
- [Configuration Guide](docs/guides/configuration.md) — all config options
- [Detectors Guide](docs/guides/detectors.md) — choosing the right detector
- [Alerting Guide](docs/guides/alerting.md) — channels, mentions, cooldown, recovery
- [CLI Reference](docs/reference/cli.md) — command-line documentation
- [Examples](docs/examples/) — real-world monitoring scenarios
- [Changelog](CHANGELOG.md) — version history

## Requirements

- Python 3.10+
- numpy >= 1.24.0
- pydantic >= 2.0.0
- click >= 8.0
- PyYAML >= 6.0
- Jinja2 >= 3.0

## License

MIT License — see [LICENSE](LICENSE) for details.
