# Examples

This directory contains practical examples for common monitoring scenarios.

## Example Index

### Infrastructure Monitoring
- [CPU Usage](#example-1-cpu-usage-monitoring) - System resource monitoring with multiple bounds
- [Memory Usage](#example-2-memory-usage-monitoring) - Memory monitoring with threshold
- [Disk Usage](#example-3-disk-usage-monitoring) - Storage monitoring with SLA

### Application Monitoring
- [API Response Time](#example-4-api-response-time-monitoring) - Latency monitoring with percentiles
- [API Error Rate](#example-5-api-error-rate-monitoring) - Error tracking with zero tolerance
- [Request Throughput](#example-6-request-throughput-with-seasonality) - Traffic monitoring with hourly patterns

### Business Metrics
- [Daily Active Users](#example-7-daily-active-users) - User engagement monitoring
- [Revenue Tracking](#example-8-daily-revenue-tracking) - Financial metrics monitoring
- [Conversion Rate](#example-9-conversion-rate-monitoring) - Funnel metrics monitoring

### Advanced Examples
- [Gaming Metrics with Complex Seasonality](#example-10-gaming-metrics-with-complex-seasonality) - Multi-dimensional seasonality
- [Multi-Detector Strategy](#example-11-multi-detector-strategy) - Combining multiple detectors

### Alerting & Preprocessing Features
- **[No-Data Alerts](#example-12-no-data-alerts)** - Fire when the latest interval has no datapoint
- **[Project-Level Error Alerting](#example-13-project-level-error-alerting)** - Catch DB outages and pipeline crashes at the project level
- **[Multiple Alerting Blocks](#multiple-alerting-blocks)** - Route one metric to several independent alert blocks
- **[Mentions Example](mentions-example.yml)** - @mention users/groups in alerts across all channels
- **[Alert Cooldown Example](alert-cooldown-example.yml)** - Prevent spam with alert cooldown
- **[Recovery Notifications Example](recovery-notification-example.yml)** - "All clear" messages when metric stabilizes
- **[Detector Preprocessing Example](detector-preprocessing-example.yml)** - input_type, smoothing, window weighting, detrending

---

## Example 1: CPU Usage Monitoring

Monitor server CPU usage with both hard limit and statistical detection.

### Configuration

```yaml
name: cpu_usage
interval: 30s

query: |
  SELECT
    toStartOfInterval(timestamp, INTERVAL 30 SECOND) AS timestamp,
    AVG(cpu_percent) AS value
  FROM system_metrics
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  # Hard limit: CPU should never exceed 95%
  - type: manual_bounds
    params:
      upper_bound: 95.0

  # Statistical: detect unusual CPU patterns
  - type: zscore
    params:
      threshold: 3.0
      window_size: 2880  # 1 day of 30s intervals
      min_samples: 100

alerting:
  enabled: true
  channels:
    - slack_ops
  min_detectors: 1  # Alert if ANY detector triggers
  direction: "up"    # Only alert on high CPU (low is good)
  consecutive_anomalies: 2  # Require 2 consecutive points
```

### Why This Works

- **Manual Bounds**: Catches critical threshold violations immediately
- **Z-Score**: Detects unusual patterns even if below 95%
- **Direction filter**: Prevents alerts when CPU drops (which is good)
- **Short consecutive**: CPU spikes need fast response

---

## Example 2: Memory Usage Monitoring

Track memory usage with adaptive detection.

### Configuration

```yaml
name: memory_usage_pct
interval: 1min

query: |
  SELECT
    toStartOfMinute(timestamp) AS timestamp,
    (used_memory_bytes / total_memory_bytes) * 100 AS value
  FROM system_metrics
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 1440  # 1 day
      min_samples: 100

alerting:
  enabled: true
  channels:
    - mattermost_ops
  direction: "up"
  consecutive_anomalies: 5  # Memory grows slowly, wait for confirmation
```

### Why MAD

- Memory usage can have outliers (garbage collection spikes)
- MAD is robust to these temporary spikes
- Higher consecutive threshold avoids false positives

---

## Example 3: Disk Usage Monitoring

Monitor disk space with SLA threshold.

### Configuration

```yaml
name: disk_usage_pct
interval: 5min

query: |
  SELECT
    toStartOfInterval(timestamp, INTERVAL 5 MINUTE) AS timestamp,
    (used_space_bytes / total_space_bytes) * 100 AS value
  FROM storage_metrics
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  - type: manual_bounds
    params:
      upper_bound: 85.0  # Alert when disk > 85% full

alerting:
  enabled: true
  channels:
    - slack_critical
    - email_oncall
  consecutive_anomalies: 3  # Disk fills slowly, confirm trend
```

### Why Manual Bounds

- Clear SLA: disk should never exceed 85%
- Disk usage grows predictably, no need for statistical detection
- Simpler than statistical methods for this use case

---

## Example 4: API Response Time Monitoring

Track API latency with percentile-based detection.

### Configuration

```yaml
name: api_p95_latency_ms
interval: 1min

query: |
  SELECT
    toStartOfMinute(timestamp) AS timestamp,
    quantile(0.95)(response_time_ms) AS value
  FROM http_requests
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  # SLA: P95 latency < 1000ms
  - type: manual_bounds
    params:
      upper_bound: 1000

  # Detect degradation before hitting SLA
  - type: iqr
    params:
      threshold: 1.5
      window_size: 1440
      min_samples: 100

alerting:
  enabled: true
  channels:
    - slack_ops
  consecutive_anomalies: 3
  direction: "up"
```

### Why IQR

- Percentile metrics are skewed (heavy-tailed)
- IQR handles skewness better than Z-Score
- Manual bounds ensures SLA compliance

---

## Example 5: API Error Rate Monitoring

Zero-tolerance error monitoring.

### Configuration

```yaml
name: api_error_rate
interval: 1min

query: |
  SELECT
    toStartOfMinute(timestamp) AS timestamp,
    countIf(status_code >= 500) / count() AS value
  FROM http_requests
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  # Zero tolerance for errors
  - type: manual_bounds
    params:
      upper_bound: 0.01  # Alert if error rate > 1%

alerting:
  enabled: true
  channels:
    - slack_critical
    - email_oncall
  consecutive_anomalies: 1  # Alert immediately
  direction: "up"
```

### Why Immediate Alerts

- Errors are critical, need fast response
- No need for consecutive threshold
- Manual bounds with low threshold (1%)

---

## Example 6: Request Throughput with Seasonality

Monitor API traffic with daily/weekly patterns.

### Configuration

```yaml
name: api_requests_per_minute
interval: 1min

query: |
  SELECT
    toStartOfMinute(timestamp) AS timestamp,
    count() AS value
  FROM http_requests
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

# Extract seasonality features from timestamps (built-in)
# Available: hour, day_of_week, day_of_month, month, is_weekend
seasonality_columns:
  - hour
  - day_of_week

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 10080  # 1 week of 1-min data
      min_samples: 500
      seasonality_components:
        - ["hour", "day_of_week"]
      min_samples_per_group: 10

alerting:
  enabled: true
  channels:
    - mattermost_ops
  consecutive_anomalies: 3
```

### Why Seasonality

- Traffic varies by hour (business hours vs night)
- Traffic varies by day (weekday vs weekend)
- Combined seasonality creates 168 unique patterns (24h × 7d)
- Prevents false positives during natural low-traffic periods

---

## Example 7: Daily Active Users

Track user engagement.

### Configuration

```yaml
name: daily_active_users
interval: 1day

query: |
  SELECT
    toDate(timestamp) AS timestamp,
    uniqExact(user_id) AS value
  FROM user_events
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 60  # 2 months
      min_samples: 30

alerting:
  enabled: true
  channels:
    - slack_analytics
  consecutive_anomalies: 2
  direction: "down"  # Alert only on drops (increases are good)
```

### Why Direction Filter

- Increases in DAU are positive (don't alert)
- Decreases are concerning (alert)
- MAD robust to occasional spikes/drops

---

## Example 8: Daily Revenue Tracking

Monitor financial metrics.

### Configuration

```yaml
name: daily_revenue_usd
interval: 1day

query: |
  SELECT
    toDate(timestamp) AS timestamp,
    SUM(amount_usd) AS value
  FROM transactions
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
    AND status = 'completed'
  GROUP BY timestamp
  ORDER BY timestamp

# Extract day of week from timestamps (built-in)
seasonality_columns:
  - day_of_week

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 90  # 3 months
      min_samples: 30
      seasonality_components:
        - "day_of_week"  # Different revenue on weekends

alerting:
  enabled: true
  channels:
    - slack_finance
    - email_management
  consecutive_anomalies: 2
  direction: "down"  # Alert on revenue drops
```

### Why Seasonality

- Revenue often varies by day of week
- Weekdays vs weekends have different patterns
- Prevents false positives on expected low-revenue days

---

## Example 9: Conversion Rate Monitoring

Track funnel metrics.

### Configuration

```yaml
name: signup_conversion_rate
interval: 1hour

query: |
  SELECT
    toStartOfHour(timestamp) AS timestamp,
    countIf(action = 'signup') / countIf(action = 'visit') AS value
  FROM user_events
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

# Extract hour of day from timestamps (built-in)
seasonality_columns:
  - hour

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 672  # 4 weeks
      min_samples: 100
      seasonality_components:
        - "hour"

alerting:
  enabled: true
  channels:
    - slack_growth
  consecutive_anomalies: 3
  direction: "down"  # Alert on conversion drops
```

---

## Example 10: Gaming Metrics with Complex Seasonality

Monitor gaming metrics with multi-dimensional seasonality.

### Configuration

```yaml
name: group_assigned_users_pct
interval: 10min

query_file: sql/group_assigned.sql

# Seasonality columns come from the query itself (query_columns.seasonality),
# so no timestamp-based extraction (seasonality_columns) is needed.
query_columns:
  timestamp: period_time
  metric: group_assigned_users_pct
  seasonality:
    - offset_10minutes  # 0-143 (10-min offset in day)
    - league_day        # 1-3 (tournament day)

loading_start_time: "2024-01-01 00:00:00"
loading_batch_size: 2160  # 15 days

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 8640   # 60 days
      min_samples: 1000
      start_time: "2024-03-01 00:00:00"
      batch_size: 2160
      seasonality_components:
        - ["offset_10minutes", "league_day"]  # 432 unique combinations
      min_samples_per_group: 10

alerting:
  enabled: true
  timezone: "Europe/Moscow"
  channels:
    - mattermost_analytics
  consecutive_anomalies: 3
```

### Why Complex Seasonality

- Gaming metric with tournament schedule (3-day leagues)
- Different patterns for each 10-minute interval within each tournament day
- 432 unique groups (144 intervals × 3 days)
- Requires large window (60 days) to have enough samples per group

---

## Example 11: Multi-Detector Strategy

Combine multiple detectors with different sensitivities.

### Configuration

```yaml
name: critical_service_latency
interval: 30s

query: |
  SELECT
    toStartOfInterval(timestamp, INTERVAL 30 SECOND) AS timestamp,
    AVG(latency_ms) AS value
  FROM critical_service_logs
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  # Detector 1: Conservative (fewer false positives)
  - type: mad
    params:
      threshold: 5.0      # Very high threshold
      window_size: 2880   # 1 day
      min_samples: 100

  # Detector 2: Aggressive (catch subtle issues)
  - type: zscore
    params:
      threshold: 2.5      # Lower threshold
      window_size: 1440   # 12 hours
      min_samples: 100

  # Detector 3: Hard limit (SLA)
  - type: manual_bounds
    params:
      upper_bound: 1000   # Never exceed 1s

alerting:
  enabled: true
  channels:
    - slack_critical
  min_detectors: 2        # Require 2 detectors to agree
  direction: "same"       # ...on the SAME direction (up or down)
  consecutive_anomalies: 3
```

### Why Multiple Detectors

- Conservative detector (MAD with high threshold) for confidence
- Aggressive detector (Z-Score with low threshold) for early warning
- Hard limit for SLA compliance
- Requiring 2 to agree reduces false positives

**Alert logic** (`min_detectors: 2`, `direction: "same"`, `consecutive_anomalies: 3`):
- MAD + Z-Score both detect "up" → counts toward the alert (high confidence)
- Manual bounds fires "up" + a statistical detector fires "up" → both vote
  "up", so the quorum is met (the votes must point the SAME way)
- Only Z-Score detects → no alert (might be noise)
- One detector says "up" while another says "down" → no alert: they are two
  anomalies in opposite directions, not two votes for one direction
  (disagreement is not consensus)
- The 2-detector quorum must hold at each of the last 3 consecutive
  points (exactly one interval apart — a gap breaks the chain)

Note: with `min_detectors: 2`, a manual-bounds violation alone never
alerts — it is one vote in the quorum. If the hard limit must page
immediately on its own, monitor it as a separate metric (or a separate
alerting entry with `min_detectors: 1`, `consecutive_anomalies: 1` —
but then any single detector can trigger that entry).

---

## Example 12: No-Data Alerts

Fire an alert when a metric stops producing data — e.g., the source
ETL hung and no rows arrive for the latest interval.

### Configuration

```yaml
# metrics/hourly_revenue.yml
name: hourly_revenue_usd
description: Total revenue per hour, sourced from the orders ETL
interval: 1hour

query: |
  SELECT
    toStartOfHour(timestamp) AS timestamp,
    SUM(amount_usd) AS value
  FROM transactions
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
    AND status = 'completed'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 720    # 30 days
      min_samples: 100

alerting:
  enabled: true
  channels:
    - mattermost_finance
    - email_oncall
  consecutive_anomalies: 2
  direction: "down"

  # No-data alert — fires if the previous full hour has no row
  no_data_alert: true
  template_no_data: |
    hourly_revenue stopped reporting
    Last expected hour: {timestamp} ({timezone})
    Likely cause: orders ETL is hung. Check the upstream job.
    {mentions}
  mentions: [oncall_data]
  alert_cooldown: "1hour"   # don't spam every cron tick
```

### Why This Works

- Hourly cron schedule means a missing hour is a real signal, not noise
- `no_data_alert` independently checks the last full interval, so it
  fires even when there are no anomalies to evaluate against
- Custom `template_no_data` makes the on-call action obvious — they
  don't need to guess what "no data" means
- `alert_cooldown: "1hour"` ensures only one no-data alert per cron
  tick, even if the ETL stays broken (anomaly and no-data alerts share
  the same cooldown state per alerting block)

### When NOT to Use

- Naturally sparse metrics (events that don't happen every interval)
- High-cardinality slicing where empty buckets are normal

---

## Example 13: Project-Level Error Alerting

Catch failures at the **project** level — DB outages, query timeouts,
lock failures — that affect every metric in the run.

### Configuration

```yaml
# detectkit_project.yml
name: my_monitoring
default_profile: prod

paths:
  metrics: metrics
  sql: sql
  templates: templates

# Catch pipeline crashes (one alert per dtk run, then abort)
error_alerting:
  enabled: true
  channels:
    - mattermost_oncall
    - email_oncall
  mentions: [oncall_engineer, here]
  timezone: "Europe/Moscow"
  template: |
    detectkit pipeline failure
    Metric: {metric_name}
    {error_type}: {error_message}
    Time: {timestamp} ({timezone})
    {mentions}
```

### Why This Works

- Without `error_alerting`, the run silently moves to the next metric
  on failure — ops only notices when expected anomaly alerts stop
  arriving (could be hours)
- One alert per `dtk run` (subsequent failures suppressed) — if CH is
  down, you don't get 30 identical alerts
- Run aborts after the first error alert — no point loading the rest
  if the source is dead
- Channels reuse `profiles.yml` — no config duplication
- Pair with cron exit-code monitoring: `error_alerting` covers
  in-process crashes, cron monitoring covers `dtk run` not running
  at all

### Channel Config (in profiles.yml)

```yaml
# profiles.yml
alert_channels:
  mattermost_oncall:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    channel: "oncall-alerts"

  email_oncall:
    type: email
    smtp_host: smtp.gmail.com
    smtp_port: 587
    from_email: detectkit@example.com
    to_emails: [oncall@example.com]
```

---

## Multiple Alerting Blocks

Route the **same** metric to several destinations with different rules by
giving `alerting:` as a YAML **list** instead of a single block. Each block
is fully independent — its own channels, conditions, templates, cooldown,
and alert/recovery/cooldown state.

```yaml
name: api_latency_p95
interval: 5min

query: |
  SELECT timestamp, quantile(0.95)(response_time_ms) AS value
  FROM api_requests
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  - type: mad
    params: {threshold: 3.0, window_size: 288, min_samples: 100}
  - type: zscore
    params: {threshold: 2.5, window_size: 288, min_samples: 100}

# alerting as a list of independent blocks
alerting:
  # Route 1: page on-call fast — any single detector, short streak, tight cooldown
  - channels: [slack_oncall]
    min_detectors: 1
    direction: "up"
    consecutive_anomalies: 2
    alert_cooldown: "10min"
    mentions: ["oncall", "here"]

  # Route 2: calmer team summary — require both detectors to agree, longer streak
  - channels: [mattermost_team]
    min_detectors: 2
    direction: "same"
    consecutive_anomalies: 5
    alert_cooldown: "1hour"
    notify_on_recovery: true
```

Each block keeps its own channels, conditions, templates, cooldown, and
alert/recovery state — they fire and recover independently. See the full
config in **[multi-alert-routing-example.yml](multi-alert-routing-example.yml)**
and the [Alerting Guide](../guides/alerting.md) for routing details.

---

## Common Patterns Summary

| Use Case | Detector | Seasonality | Consecutive | Direction |
|----------|----------|-------------|-------------|-----------|
| System Resources | Manual + Z-Score | No | 2-3 | up |
| API Latency | Manual + IQR | Optional | 3 | up |
| Error Rates | Manual | No | 1 | up |
| Traffic/Throughput | MAD | Yes (hour + day_of_week) | 3 | any |
| User Engagement | MAD | Optional | 2-3 | down |
| Revenue | MAD | Yes (day_of_week) | 2 | down |
| Conversion Rate | MAD | Yes (hour) | 3 | down |

## Alerting Feature Comparison

| Feature | Config | Effect |
|---------|--------|--------|
| Basic alert | `consecutive_anomalies: 3` | Alert after 3 consecutive anomalies (default: 3; gaps in the grid break the chain) |
| Detector quorum | `min_detectors: 2` | Require 2 detectors per the `direction` policy (default: 1) |
| Direction policy | `direction: "same"` | `same` (default): quorum must agree on one direction; `any`: every anomaly counts; `up`/`down`: only that direction counts |
| Cooldown | `alert_cooldown: "30min"` | No more than 1 alert per 30 min (default: none — a persisting anomaly re-alerts on every `dtk run`) |
| Cooldown reset | `cooldown_reset_on_recovery: true` | Cooldown resets when metric normalizes |
| Recovery notify | `notify_on_recovery: true` | "All clear" sent once per incident |
| Custom recovery | `template_recovery: "..."` | Custom message text for recovery |
| Single-anomaly template | `template_single: "..."` | Used when the alert has no streak (consecutive count ≤ 1); falls back to `template_consecutive` |
| Streak template | `template_consecutive: "..."` | Used for consecutive-anomaly alerts |
| Mentions | `mentions: ["oncall", "here"]` | @mention users/groups in alerts |
| Suppress | `suppress_until: "2026-04-11 18:00:00"` | Pause alerts until UTC time |
| No-data alert | `no_data_alert: true` | Fire when latest interval has no row |
| No-data template | `template_no_data: "..."` | Custom no-data message body |
| Multiple alert routes | `alerting:` as a YAML list | Each block independent (channels/conditions/templates/cooldown/state) |
| Rule-aware template vars (v0.9+) | `{expected_range}`, `{min_detectors}`, `{direction_policy}`, `{consecutive_required}`, `{detector_count}` | Surface the rule the alert fired with (the default message is now alert-centric) |
| Project errors | `error_alerting:` in `detectkit_project.yml` | Catch pipeline crashes (DB outage etc.) |

## See Also

- [Detectors Guide](../guides/detectors.md) - Choosing the right detector
- [Configuration Guide](../guides/configuration.md) - All configuration options
- [Alerting Guide](../guides/alerting.md) - Alert configuration
- [Quickstart Guide](../getting-started/quickstart.md) - Getting started
