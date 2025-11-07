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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
  GROUP BY timestamp
  ORDER BY timestamp

# Extract seasonality features
seasonality_columns:
  - name: hour_of_day
    extract: hour
  - name: day_of_week
    extract: dow

query_columns:
  timestamp: timestamp
  metric: value
  seasonality:
    - hour_of_day
    - day_of_week

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 10080  # 1 week of 1-min data
      min_samples: 500
      seasonality_components:
        - ["hour_of_day", "day_of_week"]
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
    AND status = 'completed'
  GROUP BY timestamp
  ORDER BY timestamp

# Extract day of week for seasonality
seasonality_columns:
  - name: day_of_week
    extract: dow

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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
  GROUP BY timestamp
  ORDER BY timestamp

# Extract hour for seasonality
seasonality_columns:
  - name: hour_of_day
    extract: hour

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 672  # 4 weeks
      min_samples: 100
      seasonality_components:
        - "hour_of_day"

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

query_columns:
  timestamp: period_time
  metric: group_assigned_users_pct
  seasonality:
    - offset_10minutes  # 0-143 (10-min offset in day)
    - league_day        # 1-3 (tournament day)

loading_start_time: "2024-01-01 00:00:00"
loading_batch_size: 2160  # 15 days

seasonality_columns:
  - name: offset_10minutes
    extract: null  # Already in query
  - name: league_day
    extract: null  # Already in query

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
  WHERE timestamp >= %(from_date)s
    AND timestamp < %(to_date)s
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
  direction: "same"        # Must agree on direction
  consecutive_anomalies: 3
```

### Why Multiple Detectors

- Conservative detector (MAD with high threshold) for confidence
- Aggressive detector (Z-Score with low threshold) for early warning
- Hard limit for SLA compliance
- Requiring 2 to agree reduces false positives

**Alert logic**:
- Manual bounds violation → Alert (immediate)
- MAD + Z-Score both detect → Alert (high confidence)
- Only Z-Score detects → No alert (might be noise)

---

## Common Patterns Summary

| Use Case | Detector | Seasonality | Consecutive | Direction |
|----------|----------|-------------|-------------|-----------|
| System Resources | Manual + Z-Score | No | 2-3 | up |
| API Latency | Manual + IQR | Optional | 3 | up |
| Error Rates | Manual | No | 1 | up |
| Traffic/Throughput | MAD | Yes (hour/dow) | 3 | any |
| User Engagement | MAD | Optional | 2-3 | down |
| Revenue | MAD | Yes (dow) | 2 | down |
| Conversion Rate | MAD | Yes (hour) | 3 | down |

## See Also

- [Detectors Guide](../guides/detectors.md) - Choosing the right detector
- [Configuration Guide](../guides/configuration.md) - All configuration options
- [Alerting Guide](../guides/alerting.md) - Alert configuration
- [Quickstart Guide](../getting-started/quickstart.md) - Getting started
