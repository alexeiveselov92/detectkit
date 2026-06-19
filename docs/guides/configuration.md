# Configuration Guide

This guide explains all configuration options in detectkit.

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
project_name: my_monitoring

# Paths
paths:
  metrics_dir: metrics        # Directory with metric YAML files
  sql_dir: sql                # Directory with SQL query files
  templates_dir: templates    # Directory with custom alert templates

# Default profile
default_profile: prod

# Default table names (can be overridden per metric)
default_tables:
  datapoints: _dtk_datapoints
  detections: _dtk_detections
  tasks: _dtk_tasks

# Default timeouts
timeouts:
  query_timeout: 300          # SQL query timeout (seconds)
  lock_timeout: 3600          # Task lock timeout (seconds)
```

### Available Options

#### `project_name` (string, required)
Project identifier used in logs and task management.

#### `paths` (object, optional)
Directory paths relative to project root.

- **`metrics_dir`** (default: `"metrics"`) - Where metric YAML files are located
- **`sql_dir`** (default: `"sql"`) - Where SQL query files are located
- **`templates_dir`** (default: `"templates"`) - Where custom alert templates are located

#### `default_profile` (string, required)
Name of the default database profile to use (from `profiles.yml`).

#### `default_tables` (object, optional)
Default names for internal tables:

- **`datapoints`** (default: `"_dtk_datapoints"`) - Stores loaded metric data
- **`detections`** (default: `"_dtk_detections"`) - Stores detection results
- **`tasks`** (default: `"_dtk_tasks"`) - Stores task execution state

#### `timeouts` (object, optional)

- **`query_timeout`** (default: `300`) - SQL query execution timeout in seconds
- **`lock_timeout`** (default: `3600`) - How long to hold task locks before expiring

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

## Profiles Configuration

File: `profiles.yml`

### Basic Structure

```yaml
# Default profile to use
default_profile: prod

# Database profiles
profiles:
  prod:
    type: clickhouse
    host: localhost
    port: 9000
    # ... database-specific settings

# Alert channels
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    # ... channel-specific settings
```

### Database Profiles

#### ClickHouse Profile

```yaml
profiles:
  prod:
    type: clickhouse
    host: clickhouse.example.com
    port: 9000
    user: default
    password: "your_password"

    # Internal tables location (for _dtk_* tables)
    internal_database: analytics

    # Data tables location (for your metrics)
    data_database: default

    # ClickHouse-specific settings
    settings:
      max_execution_time: 600
      max_memory_usage: 10000000000
```

**Required fields**:
- `type`: Must be `"clickhouse"`
- `host`: ClickHouse server hostname
- `port`: ClickHouse native protocol port (default: 9000)
- `internal_database`: Database for _dtk_* tables
- `data_database`: Database for data queries

**Optional fields**:
- `user`: Username (default: `"default"`)
- `password`: Password (default: empty string)
- `settings`: Dict of ClickHouse settings to apply

#### PostgreSQL Profile

```yaml
profiles:
  prod:
    type: postgres
    host: localhost
    port: 5432
    user: postgres
    password: "your_password"
    database: analytics

    # Schema locations
    internal_schema: detectkit  # For _dtk_* tables
    data_schema: public         # For data queries

    # Connection pool settings
    pool_size: 5
    max_overflow: 10
```

**Required fields**:
- `type`: Must be `"postgres"`
- `host`: PostgreSQL server hostname
- `port`: PostgreSQL port (default: 5432)
- `database`: Database name
- `internal_schema`: Schema for _dtk_* tables
- `data_schema`: Schema for data queries

**Optional fields**:
- `user`: Username (default: `"postgres"`)
- `password`: Password
- `pool_size`: Connection pool size
- `max_overflow`: Max connections above pool_size

#### MySQL Profile

```yaml
profiles:
  prod:
    type: mysql
    host: localhost
    port: 3306
    user: root
    password: "your_password"
    database: analytics

    # Schema locations
    internal_database: detectkit
    data_database: analytics

    # Connection settings
    charset: utf8mb4
    autocommit: true
```

**Required fields**:
- `type`: Must be `"mysql"`
- `host`: MySQL server hostname
- `port`: MySQL port (default: 3306)
- `database`: Database name
- `internal_database`: Database for _dtk_* tables
- `data_database`: Database for data queries

### Alert Channels

#### Mattermost Channel

```yaml
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    username: "detectkit"
    icon_emoji: ":warning:"
    channel: "alerts"          # Explicit channel name
    timeout: 10                 # Request timeout (seconds)
```

**Required fields**:
- `type`: Must be `"mattermost"`
- `webhook_url`: Mattermost incoming webhook URL

**Optional fields**:
- `username` (default: `"detectkit"`) - Bot display name
- `icon_emoji` (default: `":warning:"`) - Bot icon
- `channel` - Override webhook's default channel
- `timeout` (default: `10`) - HTTP request timeout

#### Slack Channel

```yaml
alert_channels:
  slack_ops:
    type: slack
    webhook_url: "https://hooks.slack.com/services/xxx"
    username: "detectkit"
    icon_emoji: ":warning:"
    channel: "#alerts"          # Explicit channel
```

Same fields as Mattermost (Slack-compatible webhook API).

#### Telegram Channel

```yaml
alert_channels:
  telegram_alerts:
    type: telegram
    bot_token: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    chat_id: "-1001234567890"
```

**Required fields**:
- `type`: Must be `"telegram"`
- `bot_token`: Telegram bot API token
- `chat_id`: Target chat/channel ID

#### Email Channel

```yaml
alert_channels:
  email_ops:
    type: email
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    smtp_user: "your_email@gmail.com"
    smtp_password: "your_app_password"
    from_email: "alerts@example.com"
    to_emails:
      - "ops@example.com"
      - "devops@example.com"
    use_tls: true
```

**Required fields**:
- `type`: Must be `"email"`
- `smtp_host`: SMTP server hostname
- `smtp_port`: SMTP server port
- `from_email`: Sender email address
- `to_emails`: List of recipient email addresses

**Optional fields**:
- `smtp_user`: SMTP authentication username
- `smtp_password`: SMTP authentication password
- `use_tls` (default: `true`) - Use TLS encryption

## Metric Configuration

Files: `metrics/*.yml`

### Basic Structure

```yaml
# Metric identification
name: cpu_usage
profile: prod                   # Optional: override default_profile
enabled: true                   # Optional: disable metric

# Data loading
interval: 1min
query: |
  SELECT timestamp, cpu_percent AS value
  FROM system_metrics
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  ORDER BY timestamp

# Or use external SQL file
# query_file: sql/cpu_usage.sql

# Column mapping (optional)
query_columns:
  timestamp: timestamp
  metric: value

# Data loading options
loading_start_time: "2024-01-01 00:00:00"
loading_batch_size: 1440         # Load 1 day at a time

# Seasonality extraction (auto-extracted from timestamps)
seasonality_columns:
  - hour
  - day_of_week

# Detectors
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 1440
      min_samples: 100

# Alerting
alerting:
  enabled: true
  channels:
    - mattermost_ops
  consecutive_anomalies: 3

# Custom table names (optional)
tables:
  datapoints: _dtk_datapoints_cpu
  detections: _dtk_detections_cpu
```

> **Editing a metric after it already has data?** A detector's identity is a
> hash of its parameters, and each alerting block's state is keyed by a hash of
> its functional fields. So changing a detector parameter (or
> `seasonality_components`), removing a detector, or changing/removing an
> alerting block leaves the old rows behind in `_dtk_detections` /
> `_dtk_alert_states` — the pipeline simply stops writing to them. Run
> [`dtk clean --select <metric>`](../reference/cli.md#dtk-clean) to preview and
> prune that orphaned data. Renamed or deleted the metric entirely? Use
> `dtk clean --orphaned-metrics`. (Datapoints are *not* orphaned by a parameter
> edit — they are keyed only by timestamp; use `--full-refresh` to reload those.)

### Metric Identification

#### `name` (string, required)
Unique metric identifier. Used in:
- CLI selectors (`dtk run --select cpu_usage`)
- Database queries (WHERE metric_name = 'cpu_usage')
- Logs and alerts

Must be unique across all metrics in the project.

#### `profile` (string, optional)
Database profile to use for this metric. Overrides `default_profile` from project config.

#### `enabled` (boolean, default: true)
Whether metric is active. Disabled metrics are skipped by `dtk run`.

### Data Loading

#### `interval` (string or int, required)
Time interval between data points.

**String format**:
- `"1min"`, `"5min"`, `"10min"`
- `"1hour"`, `"2hours"`
- `"1day"`, `"7days"`

**Integer format** (seconds):
- `60` = 1 minute
- `600` = 10 minutes
- `3600` = 1 hour

#### `query` (string, optional)
Inline SQL query to load data.

**Built-in template variables** (Jinja2, substituted by detectkit for every
loading batch):
- `{{ dtk_start_time }}` - Start of time range (inclusive), rendered as `YYYY-MM-DD HH:MM:SS`
- `{{ dtk_end_time }}` - End of time range (exclusive), same format
- `{{ interval_seconds }}` - Metric interval in seconds

Every query must constrain its time range using `{{ dtk_start_time }}` and
`{{ dtk_end_time }}` — otherwise incremental and batched loading cannot
work. The rendered values are plain datetime strings, so wrap them in
quotes in SQL.

**Required columns**:
- Timestamp column (default name: `timestamp`)
- Metric value column (default name: `value`)
- Optional seasonality columns (declare them in `query_columns.seasonality`)

**Example**:
```sql
SELECT
  timestamp,
  AVG(response_time_ms) AS value,
  EXTRACT(HOUR FROM timestamp) AS hour_of_day
FROM api_logs
WHERE timestamp >= '{{ dtk_start_time }}'
  AND timestamp < '{{ dtk_end_time }}'
GROUP BY timestamp, hour_of_day
ORDER BY timestamp
```

#### `query_file` (string, optional)
Path to external SQL file (relative to `sql_dir`).

Mutually exclusive with `query`.

**Example**:
```yaml
query_file: sql/complex_metric.sql
```

#### `query_columns` (object, optional)
Map query column names to internal names.

```yaml
query_columns:
  timestamp: time_interval      # Query has "time_interval" column
  metric: metric_value          # Query has "metric_value" column
  seasonality:                  # Query has these seasonality columns
    - hour_of_day
    - day_of_week
```

**Defaults**:
- `timestamp`: `"timestamp"`
- `metric`: `"value"`
- `seasonality`: `null`

#### `loading_start_time` (string, optional)
Start timestamp for initial data load (UTC).

**Format**: `"YYYY-MM-DD HH:MM:SS"`

Used only when the metric has no saved datapoints yet. If it is not set and
no `--from` date is passed on the command line, the initial load fails with
an error — detectkit does not guess where your data begins. Once datapoints
exist, subsequent runs resume from the last saved timestamp and this setting
is ignored.

**Example**:
```yaml
loading_start_time: "2024-01-01 00:00:00"  # Start from Jan 1, 2024
```

#### `loading_batch_size` (int, optional)
Number of rows to load per batch. Useful for large datasets.

**Example**:
```yaml
interval: 10min
loading_batch_size: 2160  # 15 days of 10-min intervals
```

### Seasonality Extraction

#### `seasonality_columns` (list of strings, optional)
Seasonality features auto-extracted from the timestamp for seasonal detection.

**Available features**:
- `hour`: Hour of day (0-23)
- `day_of_week`: Day of week (0=Monday, 6=Sunday)
- `day_of_month`: Day of month (1-31)
- `month`: Month (1-12)
- `is_weekend`: Boolean (Saturday/Sunday)
- `is_holiday`: Boolean (holiday calendar not implemented yet — always false)

**Example**:
```yaml
seasonality_columns:
  - hour
  - day_of_week
```

These features are stored with each datapoint and can be referenced in detector `seasonality_components`.

Alternatively, return custom seasonality columns directly from the query and declare them in `query_columns.seasonality` — query-provided columns take precedence over `seasonality_columns`.

### Detectors

#### `detectors` (list, required)
List of detector configurations. Each detector independently analyzes the metric.

**Full parameter set** for the windowed statistical detectors (`mad`, `zscore`, `iqr` — they share one implementation and accept identical parameters):

```yaml
detectors:
  - type: mad                     # mad, zscore, iqr, manual_bounds
    params:
      # Algorithm parameters (all participate in the detector ID)
      threshold: 3.0              # defaults: mad 3.0, zscore 3.0, iqr 1.5
      window_size: 100            # trailing window in points (current point excluded)
      min_samples: 30             # min valid points in window to run detection
      seasonality_components:     # default: null
        - "hour"                  # single component
        - ["hour", "day_of_week"] # or combined grouping
      min_samples_per_group: 10   # defaults: mad 10, zscore 3, iqr 4
      input_type: values          # values | changes | absolute_changes | log_changes
      smoothing: null             # null | ema | sma
      smoothing_alpha: 0.3        # EMA factor (0, 1]
      smoothing_window: 10        # SMA window in points
      window_weights: null        # null (uniform) | exponential | linear
      half_life: null             # for exponential weights: age at which a point's
                                  # weight halves; int = points or duration string ("3d")
                                  # (default when unset: window_size / 20)
      detrend: null               # null | linear (robust in-window detrending)

      # Execution parameters (not part of the detector ID)
      start_time: "2024-01-01 00:00:00"   # when detection starts
      batch_size: 500                     # detection batch size
```

Notes:
- MAD is scaled by the normal-consistency constant (1.4826), so `threshold` is expressed in σ-equivalents for all three detectors; `threshold: 3.0` ≈ 3-sigma.
- Every algorithm parameter (non-default values) participates in the detector ID hash. Changing one creates a new detector ID, and detections for that detector recompute from scratch on the next run.
- `weight_decay` (float in (0, 1)) is a deprecated alias for `half_life`; the two are mutually exclusive.
- Parameters are validated when the detector is constructed at the start of the detect step — invalid `input_type`, `smoothing`, `window_weights`, `detrend` or `half_life` values fail fast for that run with a clear error (not at config load).

See [Detectors Guide](detectors.md) for detailed detector documentation.

### Alerting

#### `alerting` (object, optional)
Alert configuration for the metric.

```yaml
alerting:
  enabled: true                  # Enable/disable alerting
  suppress_until: null           # Suppress alerts until UTC datetime (default: null)
  timezone: "Europe/Moscow"      # Display timezone (default: UTC)
  channels:                      # List of channel names from profiles.yml
    - mattermost_ops
    - slack_critical

  # Anomaly filtering
  min_detectors: 1               # Detectors that must satisfy the quorum per point (default: 1)
  direction: "same"              # "same", "any", "up", "down" (default: "same")
  consecutive_anomalies: 3       # Consecutive quorum points to trigger (default: 3)

  # Alert cooldown - Prevent spam from persistent anomalies
  alert_cooldown: "30min"        # Minimum time between alerts
                                 # (default: null = re-alert on EVERY run!)
  cooldown_reset_on_recovery: true  # Reset cooldown when metric recovers (default: true)

  # Recovery notifications
  notify_on_recovery: false      # Send notification when metric stabilizes (default: false)
  template_recovery: null        # Custom recovery message template (default: null)

  # Mentions (v0.3.8) — tag users/groups in alerts
  mentions: []                   # Plain usernames without @, e.g., ["oncall", "here"]

  # Missing data alert (v0.5.0)
  no_data_alert: false           # Fire alert when last interval has no row (default: false)
  template_no_data: null         # Custom no-data message template

  # Custom templates
  template_single: null          # Used when consecutive_count <= 1
  template_consecutive: null     # Used for streaks (falls back to template_single)
```

**Alert filtering options** (see the [Alerting Guide](alerting.md#alert-filtering) for the full contract):

- **`min_detectors`**: How many detectors must satisfy the direction
  policy at every point in the consecutive chain
  - `1` = One qualifying detector is enough
  - `2` = At least 2 detectors must qualify at each point

- **`direction`**: Which anomalies count toward the quorum
  - `"same"` (default) = At least `min_detectors` detectors must agree
    on ONE direction at the latest point (up and down counted
    separately — disagreement is not consensus). The winning direction
    is locked for the whole consecutive chain.
  - `"any"` = Every anomaly counts regardless of direction (1 up + 1
    down satisfies `min_detectors: 2`)
  - `"up"` = Only anomalies above the confidence interval count;
    "down" anomalies are ignored (they neither help nor block)
  - `"down"` = Only anomalies below the confidence interval count

- **`consecutive_anomalies`**: Consecutive quorum points required
  - `1` = Alert on first anomaly
  - `3` = Alert after 3 consecutive anomalies (reduces false positives)
  - Points must be exactly one metric interval apart — a gap in the
    detection grid breaks the chain

- **`alert_cooldown`**: Minimum time between alerts (e.g., `"2h"`, `1800`)
  - `null` (default) = no cooldown: a persisting anomaly re-alerts on
    every `dtk run`. Set a cooldown for production metrics.
  - No-data alerts and anomaly alerts share the same cooldown state per
    alert config block.

- **`notify_on_recovery`**: Send notification when metric returns to normal
  - `false` = No recovery notifications (default)
  - `true` = Send one recovery notification per incident

- **`template_recovery`**: Custom recovery message template
  - Supports the same variables as anomaly templates (incl. `{expected_range}` and the rule echo `{min_detectors}` / `{direction_policy}` / `{consecutive_required}`), plus `{status}`
  - Default template (alert-centric): `"✅ Alert cleared: {metric_name}\nThe alert condition no longer holds — the metric is back within expected bounds.\nRule: ...\n..."`

- **`suppress_until`**: Temporarily suppress alerts until a UTC datetime
  - `null` = No suppression (default)
  - `"2026-04-11 18:00:00"` = Suppress alerts until this UTC time
  - Load and detect steps continue running; only alerting is paused
  - Alerts auto-resume after the specified time — no need to edit config again

- **`mentions`**: Users/groups to mention in alerts
  - Plain usernames without `@` prefix (e.g., `["oncall_user", "here"]`)
  - Special keywords: `here`, `channel`, `all` for broadcast mentions
  - Each channel formats mentions in its native syntax
  - Available as `{mentions}` and `{mentions_line}` template variables

- **`no_data_alert`** (v0.5.0): Alert when the latest expected interval
  has no datapoint
  - `false` (default) — disabled
  - `true` — at the alert step, checks `_dtk_datapoints` for the last
    complete interval. If no row exists OR the row's value is `NULL` /
    `NaN`, fires a dedicated alert with `status=NO_DATA` through the
    same `channels`. Honours `alert_cooldown` and `suppress_until`.
  - `min_detectors` and `consecutive_anomalies` deliberately do **not**
    apply — missing data is a single binary signal, not a per-detector
    vote.
  - Webhook channels render no-data alerts in amber (`#F0AD4E`) instead
    of red.

- **`template_no_data`** (v0.5.0): Custom message body for no-data alerts
  - Default: `"No data for metric: {metric_name}\n...Time: {timestamp}\nStatus: query returned no datapoint for the latest interval"`
  - Variables: `{metric_name}`, `{timestamp}`, `{timezone}`,
    `{description}`, `{description_line}`, `{mentions}`,
    `{mentions_line}`, `{status}` (always `"NO_DATA"`)
  - **Avoid** `{value:.2f}` / `{confidence_interval}` — there is no
    value for no-data alerts. The formatter falls back to the default
    template if your template uses a numeric format spec on a
    non-numeric value, but it's cleaner not to rely on the fallback.

### Custom Table Names

#### `tables` (object, optional)
Override default table names for this metric.

```yaml
tables:
  datapoints: _dtk_datapoints_sales
  detections: _dtk_detections_sales
```

**Use cases**:
- Separate critical metrics into dedicated tables
- Organize metrics by team or service
- Apply different retention policies

**Note**: `tasks` table cannot be overridden (shared across all metrics).

## Complete Examples

### Simple Metric

```yaml
name: api_errors
interval: 1min
query: |
  SELECT
    timestamp,
    error_count AS value
  FROM logs
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  ORDER BY timestamp

detectors:
  - type: manual_bounds
    params:
      upper_bound: 10

alerting:
  enabled: true
  channels:
    - slack_critical
  consecutive_anomalies: 1  # Alert immediately
```

### Advanced Metric with Seasonality

```yaml
name: website_traffic
interval: 10min
query_file: sql/traffic.sql

# The query itself returns the seasonality columns
query_columns:
  timestamp: period_time
  metric: visitor_count
  seasonality:
    - hour_of_day
    - day_of_week

loading_start_time: "2024-01-01 00:00:00"
loading_batch_size: 2160  # 15 days

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 8640  # 60 days
      min_samples: 1000
      start_time: "2024-03-01 00:00:00"
      seasonality_components:
        - ["hour_of_day", "day_of_week"]
      min_samples_per_group: 10
      window_weights: exponential  # favor recent data...
      half_life: "3d"              # ...so gradual trends don't cause alert spam

alerting:
  enabled: true
  timezone: "Europe/Moscow"
  channels:
    - mattermost_ops
  min_detectors: 1
  direction: "same"
  consecutive_anomalies: 3
```

### Multiple Detectors

```yaml
name: cpu_usage
interval: 30s
query: |
  SELECT timestamp, cpu_percent AS value
  FROM system_metrics
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  ORDER BY timestamp

detectors:
  # Hard limit: CPU should never exceed 95%
  - type: manual_bounds
    params:
      upper_bound: 95.0

  # Statistical: detect unusual patterns
  - type: mad
    params:
      threshold: 3.0
      window_size: 2880  # 1 day
      min_samples: 100

alerting:
  enabled: true
  channels:
    - slack_ops
  min_detectors: 1  # Alert if ANY detector triggers
  consecutive_anomalies: 2
```

## Best Practices

### 1. Use External SQL Files for Complex Queries

```yaml
# Good: Readable, maintainable
query_file: sql/daily_revenue.sql

# Avoid: Hard to read and maintain
query: |
  WITH daily_sales AS (
    SELECT ...
    FROM ...
    -- 50 lines of SQL
  )
  SELECT ...
```

### 2. Set Appropriate Batch Sizes

```yaml
# 10-minute interval, load 15 days at a time
interval: 10min
loading_batch_size: 2160  # 15 days × 144 intervals/day
```

Rule of thumb: 7-30 days worth of data per batch.

### 3. Use `loading_start_time` for Historical Metrics

```yaml
# Don't load years of old data unnecessarily
loading_start_time: "2024-01-01 00:00:00"
```

### 4. Group Related Metrics

```
metrics/
├── api_errors.yml
├── api_latency.yml
├── api_throughput.yml
└── database_cpu.yml
```

### 5. Use Descriptive Metric Names

```yaml
# Good
name: api_p95_latency_ms

# Avoid
name: metric1
```

### 6. Test Queries Manually First

Before adding to detectkit, test SQL queries in your database client to ensure they return expected data.

### 7. Document Custom Configurations

Add comments explaining non-obvious settings:

```yaml
detectors:
  - type: mad
    params:
      threshold: 4.0  # Higher threshold due to noisy metric
      window_size: 8640  # 60 days to smooth seasonality
```

## See Also

- [Detectors Guide](detectors.md) - Detector-specific configuration
- [Alerting Guide](alerting.md) - Alert channels and templates
- [CLI Reference](../reference/cli.md) - Command-line options
