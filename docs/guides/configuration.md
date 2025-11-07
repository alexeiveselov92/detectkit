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
    host: 10.10.0.49
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
  ORDER BY timestamp

# Or use external SQL file
# query_file: sql/cpu_usage.sql

# Column mapping (optional)
query_columns:
  timestamp: timestamp
  metric: value
  seasonality: ["hour_of_day"]

# Data loading options
loading_start_time: "2024-01-01 00:00:00"
loading_batch_size: 1440         # Load 1 day at a time

# Seasonality extraction
seasonality_columns:
  - name: hour_of_day
    extract: hour               # hour, day, dow, month, etc.

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

**Required placeholders**:
- `%(from_date)s` - Start of time range (inclusive)
- `%(to_date)s` - End of time range (exclusive)

**Required columns**:
- Timestamp column (default name: `timestamp`)
- Metric value column (default name: `value`)
- Optional seasonality columns

**Example**:
```sql
SELECT
  timestamp,
  AVG(response_time_ms) AS value,
  EXTRACT(HOUR FROM timestamp) AS hour_of_day
FROM api_logs
WHERE timestamp >= %(from_date)s
  AND timestamp < %(to_date)s
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

If not specified, detectkit starts from the earliest available data.

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

#### `seasonality_columns` (list, optional)
Extract seasonality features from timestamp for seasonal detection.

**Available extracts**:
- `hour`: Hour of day (0-23)
- `day`: Day of month (1-31)
- `dow`: Day of week (1=Monday, 7=Sunday)
- `month`: Month (1-12)
- `quarter`: Quarter (1-4)
- `year`: Year

**Example**:
```yaml
seasonality_columns:
  - name: hour_of_day
    extract: hour

  - name: day_of_week
    extract: dow
```

These columns are automatically added to query results and can be used in `seasonality_components` for detectors.

### Detectors

#### `detectors` (list, required)
List of detector configurations. Each detector independently analyzes the metric.

**General structure**:
```yaml
detectors:
  - type: detector_type        # mad, zscore, iqr, manual_bounds
    params:
      # Algorithm parameters
      threshold: 3.0
      window_size: 100

      # Execution parameters
      start_time: "2024-01-01 00:00:00"
      batch_size: 500

      # Seasonality parameters
      seasonality_components:
        - "hour_of_day"
```

See [Detectors Guide](detectors.md) for detailed detector documentation.

### Alerting

#### `alerting` (object, optional)
Alert configuration for the metric.

```yaml
alerting:
  enabled: true                  # Enable/disable alerting
  timezone: "Europe/Moscow"      # Display timezone (default: UTC)
  channels:                      # List of channel names from profiles.yml
    - mattermost_ops
    - slack_critical

  # Anomaly filtering
  min_detectors: 1               # Min detectors that must agree (default: 1)
  direction: "same"              # "same", "any", "up", "down" (default: "same")
  consecutive_anomalies: 3       # Consecutive anomalies to trigger (default: 3)

  # Special alerts
  no_data_alert: false           # Alert on missing data (default: false)

  # Custom templates
  template_single: null          # Custom single anomaly template
  template_consecutive: null     # Custom consecutive anomalies template
```

**Alert filtering options**:

- **`min_detectors`**: How many detectors must agree
  - `1` = Any detector triggers alert
  - `2` = At least 2 detectors must agree

- **`direction`**: Required anomaly direction
  - `"same"` = All detectors must agree on direction (all above or all below)
  - `"any"` = Any direction is acceptable
  - `"up"` = Only alert on values above confidence interval
  - `"down"` = Only alert on values below confidence interval

- **`consecutive_anomalies`**: Consecutive points required
  - `1` = Alert on first anomaly
  - `3` = Alert after 3 consecutive anomalies (reduces false positives)

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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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

query_columns:
  timestamp: period_time
  metric: visitor_count
  seasonality:
    - hour_of_day
    - day_of_week

loading_start_time: "2024-01-01 00:00:00"
loading_batch_size: 2160  # 15 days

seasonality_columns:
  - name: hour_of_day
    extract: hour
  - name: day_of_week
    extract: dow

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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
