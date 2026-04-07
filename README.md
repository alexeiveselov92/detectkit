# detectkit

**Metric monitoring with automatic anomaly detection**

`detectkit` is a Python library for data analysts and engineers to monitor time-series metrics with automatic anomaly detection and alerting.

## Status

[![PyPI version](https://img.shields.io/pypi/v/detectkit.svg)](https://pypi.org/project/detectkit/)
[![Python](https://img.shields.io/pypi/pyversions/detectkit.svg)](https://pypi.org/project/detectkit/)

✅ **Production Ready** — published to [PyPI](https://pypi.org/project/detectkit/)

### What's New in v0.3.8

✅ **Mentions** - @mention users and groups in alert messages
- Channel-agnostic: write usernames once, each platform formats natively
- `mentions: ["oncall_user", "here"]` in metric config
- Supports Mattermost, Slack (with User IDs), Telegram, Email
- Custom placement via `{mentions}` template variable

### What's New in v0.3.6

✅ **Recovery Notifications** - Know when your metrics stabilize
- `notify_on_recovery: true` sends a message when anomaly resolves
- Custom `template_recovery` for recovery message format
- One notification per incident, no duplicates

### What's New in v0.3.0

🎯 **Alert Cooldown** - Prevent alert spam from persistent anomalies
- Configure minimum time between alerts (`alert_cooldown: "30min"`)
- Automatic recovery detection (`cooldown_reset_on_recovery: true`)
- Stops duplicate alerts during long-running issues

## Features

- ✅ **Pure numpy arrays** - No pandas dependency in core logic
- ✅ **Batch processing** - Efficient vectorized operations
- ✅ **Multiple detectors** - Statistical methods (Z-Score, MAD, IQR, Manual Bounds)
- ✅ **Alert channels** - Mattermost, Slack, Telegram, Email, Webhook support
- ✅ **Mentions** - @mention users/groups in alerts (channel-agnostic)
- ✅ **Database agnostic** - ClickHouse, PostgreSQL, MySQL support
- ✅ **Idempotent operations** - Resume from interruptions
- 🚧 **CLI interface** - dbt-like commands (coming soon)

## Installation

```bash
pip install detectkit
```

Or from source:

```bash
git clone https://github.com/alexeiveselov92/detectkit
cd detectkit
pip install -e .
```

### Optional dependencies

```bash
# ClickHouse support
pip install detectkit[clickhouse]

# All database drivers
pip install detectkit[all-db]

# Development dependencies
pip install detectkit[dev]
```

## Quick Start

### CLI Usage (Recommended)

```bash
# Create a new project
dtk init my_monitoring_project
cd my_monitoring_project

# Configure database in profiles.yml
# Then run your metrics
dtk run --select example_cpu_usage

# Run specific pipeline steps
dtk run --select cpu_usage --steps load,detect

# Run all critical metrics
dtk run --select tag:critical

# Reload data from specific date
dtk run --select cpu_usage --from 2024-01-01
```

### Python API Usage

```python
import numpy as np
from detectkit.detectors.statistical import ZScoreDetector

# Your time-series data
timestamps = np.array([...], dtype='datetime64[ms]')
values = np.array([1.0, 2.0, 1.5, 10.0, 1.8])  # 10.0 is anomaly

# Create detector
detector = ZScoreDetector(threshold=3.0, window_size=100)

# Detect anomalies
data = {
    'timestamp': timestamps,
    'value': values
}
results = detector.detect(data)

# Check results
for result in results:
    if result.is_anomaly:
        print(f"Anomaly at {result.timestamp}: {result.value}")
```

## Architecture

- **Detectors** - Statistical and ML-based anomaly detection
- **Loaders** - Metric data loading from databases with gap filling
- **Alerting** - Multi-channel notifications with orchestration
- **Config** - YAML-based configuration (dbt-like)

## Testing

```bash
# Run tests
pytest tests/

# With coverage
pytest tests/ --cov=detectkit --cov-report=html
```

**Current status:** 287 tests passing, 87% coverage

## Development Status

### ✅ Completed (Phases 1-6)
- ✅ **Phase 1**: Core models (Interval, TableModel, ColumnDefinition)
- ✅ **Phase 2**: Database managers & data loading (MetricLoader, gap filling, seasonality)
- ✅ **Phase 3**: Statistical detectors (Z-Score, MAD, IQR, Manual Bounds)
- ✅ **Phase 4**: Alerting system (Channels, Orchestrator, consecutive anomalies)
- ✅ **Phase 5**: Task manager (Pipeline execution, locking, idempotency)
- ✅ **Phase 6**: CLI commands (dtk init, dtk run with selectors)

### 🔄 Integration Status
- ⚠️ Full end-to-end integration pending (database connection required)
- ⚠️ Advanced detectors (Prophet, TimesFM) - optional extras
- ⚠️ Additional alert channels (Telegram, Email) - optional

## Documentation

📚 **Complete documentation available at: https://github.com/alexeiveselov92/detectkit/tree/main/docs**

- [Getting Started](https://github.com/alexeiveselov92/detectkit/blob/main/docs/getting-started/quickstart.md) - 5-minute quickstart
- [Configuration Guide](https://github.com/alexeiveselov92/detectkit/blob/main/docs/guides/configuration.md) - All configuration options
- [Detectors Guide](https://github.com/alexeiveselov92/detectkit/blob/main/docs/guides/detectors.md) - Choosing the right detector
- [Alerting Guide](https://github.com/alexeiveselov92/detectkit/blob/main/docs/guides/alerting.md) - Setting up alerts
- [CLI Reference](https://github.com/alexeiveselov92/detectkit/blob/main/docs/reference/cli.md) - Command-line documentation
- [Examples](https://github.com/alexeiveselov92/detectkit/tree/main/docs/examples) - Real-world monitoring scenarios


## Requirements

- Python 3.10+
- numpy >= 1.24.0
- pydantic >= 2.0.0
- click >= 8.0
- PyYAML >= 6.0
- Jinja2 >= 3.0

## License

MIT License - See LICENSE file for details

## Contributing

This project is currently in active development. Contributions are welcome once we reach v1.0.0.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for complete version history.

### Recent Releases

**[0.3.8]** (2026-04-07) - Channel-agnostic mentions in alerts
**[0.3.6]** (2025-11-12) - Recovery notifications when metric stabilizes
**[0.3.0]** (2025-11-10) - Alert cooldown system, spam prevention
**[0.2.8]** (2025-11-10) - Fix incomplete interval detection
**[0.2.7]** (2025-11-10) - Add _dtk_metrics table
**[0.2.0]** (2025-11-06) - Detector preprocessing and value weighting
**[0.1.0]** (2025-11-03) - Initial release

[Full changelog →](CHANGELOG.md)
