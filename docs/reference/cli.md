# CLI Reference

Complete reference for the `dtk` command-line tool.

## Overview

The `dtk` CLI provides dbt-like commands for managing metric monitoring:

```bash
dtk init <project>              # Initialize new project
dtk run --select <selector>     # Run metric pipeline
dtk test-alert <metric>         # Test alert channels
dtk unlock --select <selector>  # Clear a stuck pipeline lock
dtk clean --select <selector>   # Prune data that no longer matches configs
dtk --version                   # Show version
dtk --help                      # Show help
```

## Global Options

### `--version`

Show the installed detectkit package version:

```bash
dtk --version
```

Output:
```
detectkit, version x.y.z
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

Selector for metrics to run. Three selector types are supported:

**1. Metric name** (searches only root `metrics/` directory):
```bash
dtk run --select cpu_usage          # Finds metrics/cpu_usage.yml
dtk run --select api_latency        # Finds metrics/api_latency.yml
```

Note: When using metric name (without path separators), **do not** include `.yml` extension. The extension is added automatically.

**2. Path pattern** (glob - supports subdirectories):
```bash
# Select specific file with full path
dtk run --select "metrics/critical/cpu.yml"

# Select all metrics in a folder
dtk run --select "metrics/critical/*"

# Select all metrics recursively
dtk run --select "metrics/**/*.yml"

# Pattern matching
dtk run --select "api_*"            # All metrics starting with "api_"
```

**3. Tag selector** (searches recursively):
```bash
# Select all metrics with "critical" tag
dtk run --select tag:critical

# Select metrics tagged as "api"
dtk run --select tag:api

# Select metrics tagged as "10min"
dtk run --select tag:10min
```

Tags must be configured in metric YAML files:
```yaml
name: api_latency
tags: ["critical", "api", "10min"]
# ... rest of config
```

**Uniqueness validation**: All selected metrics are validated to ensure no duplicate metric names exist. If duplicates are found, an error is raised listing the conflicting files.

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

Ignore an existing task lock and run anyway.

```bash
dtk run --select cpu_usage --force
```

**Behavior**:
- Skips the held-lock check (runs even if another lock is marked `running`)
- Still takes ownership of the lock for the duration of the run **and releases
  it on exit** — so a `--force` run also clears a previously stuck lock
- Allows concurrent runs (not recommended)

**Warning**: Can cause data corruption if multiple processes run simultaneously.

> **Note:** You usually don't need `--force` to recover from a crash. A
> `running` lock left behind by a dead process (e.g. the database restarted
> mid-run) auto-expires after its timeout (1 hour) and is overridden by the
> next normal run. To clear a stuck lock immediately, use
> [`dtk unlock`](#dtk-unlock) instead of `--force`.

##### `--profile` (optional)

Override the default profile from project config.

```bash
dtk run --select cpu_usage --profile staging
```

**Use cases**:
- Testing with different database
- Running against multiple environments

#### Metric Selection Rules

Understanding how metric selection works is important to avoid confusion:

##### File Name vs Metric Name

**Two different identifiers**:
1. **File name** (e.g., `metrics/cpu.yml`) - where config is stored
2. **Metric name** (e.g., `name: cpu_usage` in YAML) - identifier used in database

**Important**: detectkit uses **metric name** (from config) for all operations:
- Database table rows are keyed by `metric_name`
- Task locking uses `metric_name`
- Display shows `metric_name` (not file name)

**Best practice**: Keep file names and metric names consistent:
```yaml
# File: metrics/cpu_usage.yml
name: cpu_usage    # ✅ Matches file name (recommended)
```

```yaml
# File: metrics/cpu.yml
name: server_cpu_usage    # ⚠️ Confusing - file name doesn't match
```

##### Uniqueness Requirements

**Metric names MUST be unique** across the entire project.

**Why uniqueness matters**:
- Database tables use `metric_name` as PRIMARY KEY component
- Duplicate names cause data to mix from different sources
- Task locking conflicts prevent metrics from running
- Anomaly detection becomes invalid (mixed data)

**Example of invalid configuration**:
```yaml
# metrics/api/cpu.yml
name: cpu_usage          # ❌ Duplicate name!
query: "SELECT * FROM api_metrics"

# metrics/system/cpu.yml
name: cpu_usage          # ❌ Same name causes data corruption!
query: "SELECT * FROM system_metrics"
```

**Validation**: detectkit automatically validates uniqueness when selecting metrics. If duplicates are found:
```
Error: Duplicate metric name 'cpu_usage' found:
  - metrics/api/cpu.yml
  - metrics/system/cpu.yml

Metric names must be unique across the project.
Please rename one of the metrics to avoid data corruption.
```

**Solution - use unique names**:
```yaml
# metrics/api/cpu.yml
name: api_cpu_usage      # ✅ Unique

# metrics/system/cpu.yml
name: system_cpu_usage   # ✅ Unique
```

##### Selector Behavior Summary

| Selector Type | Example | Searches | Extension |
|--------------|---------|----------|-----------|
| Metric name | `cpu_usage` | Root `metrics/` only | Auto-added |
| Path with `/` | `metrics/api/cpu.yml` | Glob pattern | Keep as-is |
| Pattern with `*` | `api_*` | Glob pattern | Keep as-is |
| Tag | `tag:critical` | Recursive search | N/A |

**Common mistakes**:
- ❌ `dtk run --select cpu_usage.yml` → Won't work (searches for `metrics/cpu_usage.yml.yml`)
- ✅ `dtk run --select cpu_usage` → Correct (searches for `metrics/cpu_usage.yml`)
- ✅ `dtk run --select "metrics/cpu_usage.yml"` → Also works (explicit path)

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

### `dtk unlock`

Clear a stuck pipeline lock for the selected metric(s).

#### Syntax

```bash
dtk unlock --select <selector> [OPTIONS]
```

#### Options

**`--select`, `-s`** (required)
Metric selector — same semantics as `dtk run` (metric name, path pattern, or
`tag:<name>`).

**`--profile`** (optional)
Profile to use (overrides project default).

#### Examples

```bash
# Unlock a single metric
dtk unlock --select cpu_usage

# Unlock everything matching a tag
dtk unlock --select "tag:critical"
```

#### When to use it

Every `dtk run` records a `running` lock in `_dtk_tasks` while it works and
clears it on exit. If a run is killed without releasing its lock — most
commonly when **the database restarts mid-run** — the `running` row is left
behind. Until it's cleared, every subsequent **non-`--force`** run fails with:

```
RuntimeError: Failed to acquire lock for metric '<name>'. Another task is
running. Use --force to override.
```

Stuck locks **auto-expire** after their timeout (1 hour) — the next normal run
treats the stale `running` row as released and overrides it, so the error
clears itself. `dtk unlock` simply does this **immediately** instead of waiting
for the timeout. It marks the task `completed`, so the next scheduled (cron)
run proceeds normally without needing `--force`.

#### Behavior

- Reports, per metric, whether a lock was cleared or none was held
- Clears even a not-yet-expired lock (use with the same care as `--force`)
- Does **not** run the pipeline — only releases the lock

#### Example Output

```
Project root: /path/to/project
Found 1 metric(s) to unlock

  ✓ cpu_usage: lock cleared

Done. Cleared 1 lock(s) of 1 metric(s).
```

---

### `dtk clean`

Remove internal data that no longer matches the project's YAML configs.

Editing metrics over time leaves stale rows behind in the internal tables.
`dtk clean` finds and removes that drift. **Both modes default to a dry-run**
that only reports what would be deleted; pass `--execute` to actually delete.

#### Syntax

```bash
dtk clean --select <selector> [--execute] [OPTIONS]   # drift mode
dtk clean --orphaned-metrics [--execute] [OPTIONS]    # GC mode
```

#### Options

##### `--select`, `-s` (drift mode)

Metric selector — same semantics as `dtk run`. For each selected
(still-existing) metric, removes:

- `_dtk_detections` rows whose `detector_id` is no longer produced by the
  config — i.e. you changed a detector parameter or `seasonality_components`
  (which changes the detector's hash), or removed a detector;
- `_dtk_alert_states` rows whose `alert_config_id` is no longer produced —
  i.e. you changed an alerting block's functional params (channels,
  `min_detectors`, `consecutive_anomalies`, cooldown) or removed the block.

Datapoints are **not** touched — they are keyed only by `(metric, timestamp)`
and are never orphaned by a parameter edit. Use `dtk run --full-refresh` to
reload those.

##### `--orphaned-metrics` (GC mode)

Deletes **all** rows, across every internal table, for metric names present in
the database but no longer defined by any YAML in the project (a renamed or
deleted metric). Operates over the whole project (ignores `--select`).

##### `--execute` (flag)

Actually delete. Without it, the command only reports (dry-run).

##### `--yes`, `-y` (flag)

Skip the confirmation prompt for `--orphaned-metrics --execute`.

##### `--profile` (optional)

Profile to use (overrides project default).

#### Examples

```bash
# See what stale detector/alert data a metric has accumulated (dry-run)
dtk clean --select cpu_usage

# ...then actually delete it
dtk clean --select cpu_usage --execute

# Clean drift across everything matching a tag
dtk clean --select "tag:critical" --execute

# List metrics in the DB that no longer exist in the project
dtk clean --orphaned-metrics

# Purge them (asks for confirmation unless -y)
dtk clean --orphaned-metrics --execute
```

#### Safety

- Dry-run by default; nothing is deleted without `--execute`.
- `--orphaned-metrics --execute` asks for confirmation (skip with `--yes`), and
  **refuses** to run if the project defines no metrics or its configs fail to
  parse — so a wrong directory or a duplicate-name error can't wipe valid data.
- In drift mode, if a metric's config defines no detectors/alerting at all (so
  *every* stored row counts as orphaned), the command prints a loud warning
  before deleting.
- Deletes are synchronous ClickHouse mutations and idempotent — safe to re-run.

#### Example Output

```
Project root: /path/to/project
DRY-RUN — nothing will be deleted. Use --execute to apply.

Found 1 metric(s) to inspect

  cpu_usage:
    detector a1b2c3d4e5f6a7b8: would delete 4,320 detection row(s)
    alert_config 9f8e7d6c5b4a3210: would delete stale alert state

Would delete 1 orphaned detector group(s) and 1 orphaned alert-state row(s).
Re-run with --execute to apply.
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (configuration, database, etc.) |
| 2 | Command-line argument error |

## Environment Variables

The CLI itself defines no special environment variables, but configuration
files support environment-variable interpolation so secrets stay out of YAML.
Both `${VAR}` and `{{ env_var('VAR') }}` syntaxes are supported:

```yaml
# profiles.yml
profiles:
  prod:
    type: clickhouse
    host: "{{ env_var('CLICKHOUSE_HOST') }}"
    port: 9000
    password: "${CLICKHOUSE_PASSWORD}"

alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"
```

Unresolved placeholders (variable not set) are kept as-is, so missing
variables surface as configuration errors instead of empty strings.

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

# Detector/alert params changed → prune the now-orphaned old results
dtk clean --select cpu_usage            # preview
dtk clean --select cpu_usage --execute
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
# Clear a stuck lock left by a crashed run (e.g. DB restarted mid-run)
dtk unlock --select cpu_usage

# Force run if previous run crashed (also clears the stuck lock on exit)
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

To recover from a *crashed* run (no live process), prefer `dtk unlock` — it
clears the stale lock without running the pipeline concurrently. A stuck lock
also auto-expires after 1 hour, so often no manual action is needed at all.

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

### "Task is locked" / "Failed to acquire lock"

**Cause**: Previous run is still in progress, or it crashed/was killed with the
`running` lock held. The most common crash cause is the **database restarting
mid-run**, which leaves a stale `running` row in `_dtk_tasks`.

**Solution**:
```bash
# Check if a process is actually still running
ps aux | grep dtk

# If no process is running, clear the stuck lock immediately:
dtk unlock --select cpu_usage

# (Or just wait — a stale lock auto-expires after 1 hour and the next
#  normal run overrides it. --force also clears it on exit.)
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
