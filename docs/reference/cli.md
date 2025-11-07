# CLI Reference

Complete reference for the `dtk` command-line tool.

## Overview

The `dtk` CLI provides dbt-like commands for managing metric monitoring:

```bash
dtk init <project>              # Initialize new project
dtk run --select <selector>     # Run metric pipeline
dtk test-alert <metric>         # Test alert channels
dtk --version                   # Show version
dtk --help                      # Show help
```

## Global Options

### `--version`

Show detectkit version:

```bash
dtk --version
```

Output:
```
dtk, version 0.1.0
```

### `--help`

Show help for any command:

```bash
dtk --help
dtk run --help
dtk init --help
```

## Commands

### `dtk init`

Initialize a new detectkit project.

#### Syntax

```bash
dtk init <project_name> [OPTIONS]
```

#### Arguments

**`project_name`** (required)
Name of the project to create.

#### Options

**`--target-dir`, `-d`** (default: `.`)
Directory to create project in.

#### Examples

Create project in current directory:
```bash
dtk init my_monitoring
```

Create project in specific directory:
```bash
dtk init analytics --target-dir /opt/projects
```

#### Created Structure

```
my_monitoring/
├── detectkit_project.yml   # Project configuration
├── profiles.yml            # Database connections & alert channels
├── metrics/                # Metric definitions
│   └── .gitkeep
└── sql/                    # SQL query files
    └── .gitkeep
```

---

### `dtk run`

Run the metric processing pipeline.

#### Syntax

```bash
dtk run --select <selector> [OPTIONS]
```

#### Options

##### `--select`, `-s` (required)

Selector for metrics to run.

**Metric name**:
```bash
dtk run --select cpu_usage
```

**Path pattern** (glob):
```bash
dtk run --select "metrics/critical/*.yml"
```

**Tag** (not implemented yet):
```bash
dtk run --select tag:critical
```

##### `--exclude`, `-e` (optional)

Selector for metrics to exclude.

```bash
dtk run --select "*" --exclude "metrics/staging/*"
```

##### `--steps` (default: `load,detect,alert`)

Pipeline steps to execute.

**Available steps**:
- `load` - Load data from database
- `detect` - Run anomaly detection
- `alert` - Send alerts

**Examples**:
```bash
# All steps (default)
dtk run --select cpu_usage

# Load only
dtk run --select cpu_usage --steps load

# Detect and alert (skip load)
dtk run --select cpu_usage --steps detect,alert

# Detect only (no load, no alert)
dtk run --select cpu_usage --steps detect
```

##### `--from` (optional)

Start date for data loading.

**Format**: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`

```bash
# Load from January 1, 2024
dtk run --select cpu_usage --from "2024-01-01"

# Load from specific timestamp
dtk run --select cpu_usage --from "2024-01-01 12:00:00"
```

**Behavior**:
- Overrides metric's `loading_start_time` config
- Only affects `load` step
- Timestamps are in UTC

##### `--to` (optional)

End date for data loading.

**Format**: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`

```bash
# Load up to February 1, 2024
dtk run --select cpu_usage --from "2024-01-01" --to "2024-02-01"
```

**Behavior**:
- Defaults to current time if not specified
- Only affects `load` step
- Timestamps are in UTC

##### `--full-refresh` (flag)

Delete all existing data and reload from scratch.

```bash
dtk run --select cpu_usage --full-refresh
```

**Behavior**:
1. Deletes all data from `_dtk_datapoints`
2. Deletes all detections from `_dtk_detections`
3. Reloads data from `loading_start_time` or `--from`

**Use cases**:
- Fixing corrupted data
- Changing data loading logic
- Reprocessing with new detector configuration

**Warning**: This is a destructive operation. Use with caution.

##### `--force` (flag)

Ignore task locks and run anyway.

```bash
dtk run --select cpu_usage --force
```

**Behavior**:
- Bypasses task lock checks
- Allows concurrent runs (not recommended)
- Use only if previous run crashed with lock held

**Warning**: Can cause data corruption if multiple processes run simultaneously.

##### `--profile` (optional)

Override the default profile from project config.

```bash
dtk run --select cpu_usage --profile staging
```

**Use cases**:
- Testing with different database
- Running against multiple environments

#### Examples

##### Basic Usage

Run single metric:
```bash
dtk run --select cpu_usage
```

Run all metrics:
```bash
dtk run --select "*"
```

Run metrics matching pattern:
```bash
dtk run --select "api_*"
```

##### Partial Pipeline

Load data only (skip detection):
```bash
dtk run --select cpu_usage --steps load
```

Run detection only (skip load and alert):
```bash
dtk run --select cpu_usage --steps detect
```

Run detection and alert (skip load):
```bash
dtk run --select cpu_usage --steps detect,alert
```

##### Historical Backfill

Load data from specific date:
```bash
dtk run --select cpu_usage --from "2024-01-01"
```

Load specific date range:
```bash
dtk run --select cpu_usage \
  --from "2024-01-01" \
  --to "2024-02-01"
```

##### Full Refresh

Delete and reload all data:
```bash
dtk run --select cpu_usage --full-refresh
```

Full refresh with custom start date:
```bash
dtk run --select cpu_usage \
  --full-refresh \
  --from "2024-01-01"
```

##### Multiple Metrics

Run multiple metrics by pattern:
```bash
dtk run --select "metrics/critical/*.yml"
```

Run all except staging:
```bash
dtk run --select "*" --exclude "metrics/staging/*"
```

##### Different Environment

Run against staging database:
```bash
dtk run --select cpu_usage --profile staging
```

##### Force Run (Emergency)

Force run if previous run crashed:
```bash
dtk run --select cpu_usage --force
```

#### Output

Typical output:
```
[2024-03-15 10:00:00] Running metric: cpu_usage
[2024-03-15 10:00:01] ✓ Load step completed: 1440 points loaded
[2024-03-15 10:00:02] ✓ Detect step completed: 5 anomalies found
[2024-03-15 10:00:03] ✓ Alert step completed: 1 alert sent
[2024-03-15 10:00:03] ✓ Task completed successfully
```

With errors:
```
[2024-03-15 10:00:00] Running metric: cpu_usage
[2024-03-15 10:00:01] ✗ Load step failed: Connection refused
[2024-03-15 10:00:01] ✗ Task failed
```

---

### `dtk test-alert`

Send test alert for a metric.

#### Syntax

```bash
dtk test-alert <metric_name> [OPTIONS]
```

#### Arguments

**`metric_name`** (required)
Name of the metric to test alerts for.

#### Options

**`--profile`** (optional)
Profile to use (overrides project default).

#### Examples

Test alert for single metric:
```bash
dtk test-alert cpu_usage
```

Test with specific profile:
```bash
dtk test-alert cpu_usage --profile production
```

#### Behavior

Sends a mock alert through all configured channels with fake data:
- Current timestamp
- Mock anomaly value: `0.8532`
- Mock confidence interval: `[0.4521, 0.6234]`
- Mock severity: `4.52`
- Mock consecutive count: `3`

**Use cases**:
- Verify webhook URLs work
- Check alert formatting
- Test custom templates
- Validate channel permissions

#### Example Output

```
[2024-03-15 10:00:00] Loading metric configuration: cpu_usage
[2024-03-15 10:00:01] Sending test alert to channel: mattermost_ops
[2024-03-15 10:00:02] ✓ Alert sent successfully
[2024-03-15 10:00:02] ✓ Test alert completed
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (configuration, database, etc.) |
| 2 | Command-line argument error |

## Environment Variables

Currently, detectkit does not use environment variables. All configuration is in YAML files.

## Common Workflows

### Initial Setup

```bash
# 1. Initialize project
dtk init my_monitoring
cd my_monitoring

# 2. Edit profiles.yml (add database connection)
# 3. Create metric config in metrics/

# 4. Run metric
dtk run --select my_metric
```

### Daily Operations

```bash
# Run all metrics (typically in cron/scheduler)
dtk run --select "*"

# Run critical metrics only
dtk run --select "tag:critical"

# Run specific metric manually
dtk run --select cpu_usage
```

### Backfilling Historical Data

```bash
# Load last 30 days
dtk run --select cpu_usage --from "2024-02-01"

# Load specific range
dtk run --select cpu_usage \
  --from "2024-01-01" \
  --to "2024-02-01"
```

### Reprocessing After Configuration Changes

```bash
# Detector config changed → rerun detection
dtk run --select cpu_usage --steps detect --full-refresh

# Query changed → reload data
dtk run --select cpu_usage --full-refresh
```

### Testing and Debugging

```bash
# Test alert channels
dtk test-alert cpu_usage

# Load data only (verify query works)
dtk run --select cpu_usage --steps load

# Detect only (verify detector works)
dtk run --select cpu_usage --steps detect
```

### Emergency Operations

```bash
# Force run if previous run crashed
dtk run --select cpu_usage --force

# Full refresh if data is corrupted
dtk run --select cpu_usage --full-refresh
```

## Scheduling

### Cron (Linux/Mac)

```bash
# Run all metrics every 10 minutes
*/10 * * * * cd /path/to/project && dtk run --select "*" >> /var/log/detectkit.log 2>&1

# Run critical metrics every 5 minutes
*/5 * * * * cd /path/to/project && dtk run --select "tag:critical" >> /var/log/detectkit.log 2>&1
```

### systemd Timer (Linux)

Create `/etc/systemd/system/detectkit.service`:
```ini
[Unit]
Description=detectkit metric monitoring

[Service]
Type=oneshot
WorkingDirectory=/path/to/project
ExecStart=/usr/local/bin/dtk run --select "*"
User=detectkit
```

Create `/etc/systemd/system/detectkit.timer`:
```ini
[Unit]
Description=Run detectkit every 10 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
```

Enable:
```bash
systemctl enable detectkit.timer
systemctl start detectkit.timer
```

### Task Scheduler (Windows)

```powershell
# Create scheduled task to run every 10 minutes
$action = New-ScheduledTaskAction -Execute "dtk" -Argument "run --select *" -WorkingDirectory "C:\projects\my_monitoring"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "detectkit" -Action $action -Trigger $trigger
```

### Docker Cron

```dockerfile
FROM python:3.11-slim

# Install detectkit
RUN pip install detectkit[clickhouse]

# Install cron
RUN apt-get update && apt-get install -y cron

# Copy project files
COPY . /app
WORKDIR /app

# Add cron job
RUN echo "*/10 * * * * cd /app && dtk run --select '*' >> /var/log/cron.log 2>&1" | crontab -

# Start cron
CMD ["cron", "-f"]
```

## Best Practices

### 1. Use Selectors Effectively

```bash
# Good: Specific selector
dtk run --select "metrics/critical/*.yml"

# Avoid: Selecting all when not needed
dtk run --select "*"
```

### 2. Test Before Scheduling

```bash
# Always test manually before adding to cron
dtk run --select my_metric
dtk test-alert my_metric
```

### 3. Log Output

```bash
# Redirect to log file for troubleshooting
dtk run --select "*" >> /var/log/detectkit.log 2>&1
```

### 4. Use --steps for Development

```bash
# Test query without detection
dtk run --select my_metric --steps load

# Test detector without alerting
dtk run --select my_metric --steps load,detect
```

### 5. Be Careful with --force

```bash
# Only use --force if you're sure no other process is running
# Check processes first:
ps aux | grep dtk
```

## Troubleshooting

### "Metric not found"

**Cause**: Selector doesn't match any metrics.

**Solution**: Check metric name and file path:
```bash
# List metric files
ls metrics/

# Try exact match
dtk run --select cpu_usage  # Not metrics/cpu_usage.yml
```

### "Task is locked"

**Cause**: Previous run is still in progress or crashed with lock held.

**Solution**:
```bash
# Check if process is running
ps aux | grep dtk

# If no process, force unlock
dtk run --select cpu_usage --force
```

### "Connection refused"

**Cause**: Can't connect to database.

**Solution**: Check `profiles.yml` and database connectivity:
```bash
# Test ClickHouse connection
clickhouse-client --host=<host> --port=<port>
```

### "No data loaded"

**Cause**: Query returns empty result.

**Solution**: Test query manually in database client with sample dates.

## See Also

- [Configuration Guide](../guides/configuration.md) - Configure metrics
- [Detectors Guide](../guides/detectors.md) - Configure detectors
- [Alerting Guide](../guides/alerting.md) - Configure alerts
- [Quickstart Guide](../getting-started/quickstart.md) - Getting started tutorial
