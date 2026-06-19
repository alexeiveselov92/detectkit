# Configuration Guide

This guide explains all configuration options in detectkit.

> **This reference is split into focused pages:**
>
> - **This page** — config-file overview and `detectkit_project.yml` (project settings).
> - [Profiles](configuration-profiles.md) — database connections and alert channels (`profiles.yml`).
> - [Metrics](configuration-metrics.md) — metric definitions (`metrics/*.yml`): query, interval, detectors, alerting, examples.

## Configuration Files

detectkit uses three main configuration files:

1. **`detectkit_project.yml`** - Project-level settings
2. **`profiles.yml`** - Database connections and alert channels
3. **`metrics/*.yml`** - Individual metric definitions

## Project Configuration

File: `detectkit_project.yml`

### Basic Structure

```yaml
# Project name
name: my_monitoring

# Project version (optional)
version: "1.0"

# Paths
paths:
  metrics: metrics            # Directory with metric YAML files
  sql: sql                    # Directory with SQL query files
  templates: templates        # Directory with custom alert templates

# Default profile
default_profile: prod

# Default table names (can be overridden per metric)
tables:
  datapoints: _dtk_datapoints
  detections: _dtk_detections
  tasks: _dtk_tasks
  metrics: _dtk_metrics

# Default timeouts (seconds)
timeouts:
  load: 3600                  # Data loading timeout
  detect: 7200                # Detection timeout
  alert: 300                  # Alerting timeout
```

> **Note**: `dtk run` currently resolves metric files from the literal
> `<project>/metrics` directory regardless of the `paths.metrics` override —
> the override is not yet honoured for metric discovery.

### Available Options

#### `name` (string, required)
Project identifier used in logs and task management.

#### `version` (string, optional)
Project version label (default: `"1.0"`). Purely informational.

#### `paths` (object, optional)
Directory paths relative to project root.

- **`metrics`** (default: `"metrics"`) - Where metric YAML files are located
- **`sql`** (default: `"sql"`) - Where SQL query files are located
- **`templates`** (default: `"templates"`) - Where custom alert templates are located

#### `default_profile` (string, required)
Name of the default database profile to use (from `profiles.yml`).

#### `tables` (object, optional)
Default names for internal tables:

- **`datapoints`** (default: `"_dtk_datapoints"`) - Stores loaded metric data
- **`detections`** (default: `"_dtk_detections"`) - Stores detection results
- **`tasks`** (default: `"_dtk_tasks"`) - Stores task execution state
- **`metrics`** (default: `"_dtk_metrics"`) - Stores metric configuration state

#### `timeouts` (object, optional)
Operation timeouts in seconds:

- **`load`** (default: `3600`) - Data loading timeout
- **`detect`** (default: `7200`) - Detection timeout
- **`alert`** (default: `300`) - Alerting timeout

#### `error_alerting` (object, optional)

**New in v0.5.0** — project-scoped error alerting. Catches any exception
from `TaskManager.run_metric` (DB outage, query timeout, lock acquisition
failure, channel HTTP error, etc.) and ships **one** alert through the
named channels. After the alert fires the rest of the `dtk run`
invocation aborts — if the source DB is down there's no point loading
the next 30 metrics.

```yaml
# detectkit_project.yml
error_alerting:
  enabled: true                       # default: false
  channels:                           # channel names from profiles.yml
    - mattermost_oncall
    - email_oncall
  mentions: [oncall_engineer, here]   # optional, same syntax as metric mentions
  timezone: "Europe/Moscow"           # optional, used for {timestamp} display
  template: |                         # optional, see template variables below
    🔥 detectkit pipeline failed
    Metric: {metric_name}
    {error_type}: {error_message}
    Time: {timestamp} ({timezone})
    {mentions}
```

**Fields**:

- **`enabled`** (default: `false`) - Master switch.
- **`channels`** (default: `[]`) - Channel names from `profiles.yml`. If
  none resolve, error alerting silently no-ops.
- **`template`** (default: `null`) - Custom message body. Default is
  `"Pipeline failed for metric: {metric_name}\n...Time: {timestamp}\nError: {error_type}: {error_message}\n{mentions_line}"`.
- **`mentions`** (default: `[]`) - Same syntax as metric-level mentions.
- **`timezone`** (default: `null` / UTC) - Display timezone for `{timestamp}`.

**Template variables** (in addition to `{metric_name}`, `{timestamp}`,
`{timezone}`, `{mentions}`, `{mentions_line}`, `{description}`,
`{description_line}`):

- `{error_type}` - Exception class name (e.g., `ConnectionRefusedError`)
- `{error_message}` - Exception `str(exc)`
- `{status}` - Always `"ERROR"`
- `{project_name}` - Project `name` from `detectkit_project.yml`
  (v0.5.3). Empty string when not set.
- `{project_name_prefix}` - `"[<project_name>] "` when set, empty
  otherwise. The default error title uses this so multi-project
  channels stay distinguishable (`[my_monitoring] Pipeline error: <startup>`).

**Behaviour notes**:

- **One alert per `dtk run`.** Subsequent metric failures in the same
  invocation are suppressed via an in-memory flag.
- **Run aborts** after the first error alert (`result["abort_run"] = True`
  → CLI breaks the metric loop).
- **No persistent cooldown** between separate `dtk run` invocations.
  Storing state in the DB doesn't help when the DB itself is down, and
  a local file would break the dbt-style stateless model. Use cron
  schedule cadence to space out repeated alerts.
- A flaky channel cannot crash the run — dispatch is wrapped in its
  own `try/except`.

