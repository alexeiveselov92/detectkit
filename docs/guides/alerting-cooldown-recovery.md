# Cooldown, suppression & recovery

## Alert Cooldown (Spam Prevention)

Prevent alert fatigue from persistent anomalies with cooldown periods.

**Default is `null` — no cooldown.** Without a cooldown, a persisting
anomaly re-alerts on **every** `dtk run` for as long as the conditions
hold. Set `alert_cooldown` (e.g. `"2h"`) for production metrics.

### The Problem: Alert Spam

With frequent monitoring intervals, long-running anomalies generate excessive duplicate alerts:

**Example**: 10-minute interval metric with 5-hour anomaly:
```
10:00 - Anomaly detected → Alert sent ✓
10:10 - Still anomalous   → Alert sent (duplicate!)
10:20 - Still anomalous   → Alert sent (duplicate!)
10:30 - Still anomalous   → Alert sent (duplicate!)
... (27 more alerts over 5 hours)
```

**Result**: 30 identical alerts for a single issue.

### The Solution: Alert Cooldown

Configure minimum time between alerts:

```yaml
alerting:
  enabled: true
  channels:
    - mattermost_ops
  consecutive_anomalies: 3

  # Cooldown configuration
  alert_cooldown: "30min"              # Minimum 30 minutes between alerts
  cooldown_reset_on_recovery: true     # Reset timer when metric recovers
```

Cooldown state is stored per alert config block (in the
`_dtk_alert_states` table). Within one block, **no-data alerts and
anomaly alerts share the same cooldown state**: either kind of alert
starts the cooldown for both.

### Cooldown Behavior

#### With Recovery Reset (Recommended)

**Configuration:**
```yaml
alert_cooldown: "30min"
cooldown_reset_on_recovery: true  # Default
```

**Timeline:**
```
10:00 - Anomaly detected  → Alert sent ✓
10:10 - Persists          → Skipped (cooldown)
10:20 - Persists          → Skipped (cooldown)
10:30 - Persists          → Skipped (cooldown)
10:40 - RECOVERS to normal → Cooldown timer RESETS
10:50 - NEW anomaly       → Alert sent ✓ (recovery reset cooldown)
```

**Advantages:**
- Alert on first occurrence
- Skip duplicate alerts during persistent issue
- Alert again when new issue occurs after recovery
- Best for most use cases

#### Strict Cooldown (Noisy Metrics)

**Configuration:**
```yaml
alert_cooldown: "1hour"
cooldown_reset_on_recovery: false  # Strict mode
```

**Timeline:**
```
10:00 - Anomaly detected → Alert sent ✓
10:10 - Persists         → Skipped (cooldown)
10:20 - RECOVERS         → No alert (recovery doesn't reset)
10:30 - NEW anomaly      → Skipped (only 30min < 1hour)
11:00 - NEW anomaly      → Skipped (only 60min = 1hour)
11:01 - NEW anomaly      → Alert sent ✓ (>1hour passed)
```

**Advantages:**
- Absolute minimum time between any alerts
- Useful for very noisy metrics
- Prevents alert storms even with rapid recovery/anomaly cycles

### Configuration Options

#### String Format (Human-Readable)

```yaml
alert_cooldown: "10min"   # 10 minutes
alert_cooldown: "30min"   # 30 minutes
alert_cooldown: "1hour"   # 1 hour
alert_cooldown: "2hours"  # 2 hours
alert_cooldown: "1day"    # 1 day
```

#### Integer Format (Seconds)

```yaml
alert_cooldown: 600    # 10 minutes (600 seconds)
alert_cooldown: 1800   # 30 minutes
alert_cooldown: 3600   # 1 hour
alert_cooldown: 7200   # 2 hours
```

#### Recovery Behavior

```yaml
# Reset cooldown on metric recovery (default)
cooldown_reset_on_recovery: true

# Strict cooldown regardless of recovery
cooldown_reset_on_recovery: false
```

### Choosing Cooldown Settings

#### By Metric Criticality

**Critical metrics** (API availability, payment processing):
```yaml
alert_cooldown: "5min"                # Short cooldown
cooldown_reset_on_recovery: true      # Alert on new issues quickly
```

**Important metrics** (Application performance, database latency):
```yaml
alert_cooldown: "30min"               # Standard cooldown
cooldown_reset_on_recovery: true      # Default behavior
```

**Noisy metrics** (Non-critical warnings, experimental monitors):
```yaml
alert_cooldown: "2hours"              # Long cooldown
cooldown_reset_on_recovery: false     # Strict mode
```

#### By Interval

**Fast intervals** (1min, 5min):
```yaml
# More aggressive cooldown needed
alert_cooldown: "30min"
```

**Slow intervals** (1hour, 1day):
```yaml
# Less aggressive cooldown
alert_cooldown: "1hour"
```

### How Recovery Detection Works

detectkit automatically detects recovery by checking if consecutive anomalies dropped below threshold:

**Example** with `consecutive_anomalies: 3`:

```
Points:  A  A  A  N  N  N  A  A  A
         ↑  ↑  ↑  ↑  ↑  ↑
         1  2  3  Recovery detected!

Timeline:
10:00 - 1st anomaly
10:10 - 2nd anomaly
10:20 - 3rd anomaly → Alert sent (threshold met)
10:30 - Normal point
10:40 - Normal point
10:50 - Normal point → Recovery detected, cooldown reset
11:00 - NEW 1st anomaly
11:10 - NEW 2nd anomaly
11:20 - NEW 3rd anomaly → Alert sent (new issue)
```

## Temporary Alert Suppression

When you've identified the root cause of an anomaly and want to stop alerts while the fix is deployed, use `suppress_until` to temporarily silence alerts without disabling the metric.

### The Problem

Using `enabled: false` requires two config edits — one to disable, another to re-enable later. If you forget the second edit, alerting stays off.

### The Solution: `suppress_until`

Set a UTC datetime after which alerts automatically resume:

```yaml
alerting:
  enabled: true
  suppress_until: "2026-04-11 18:00:00"  # Alerts suppressed until this UTC time
  channels:
    - mattermost_ops
  consecutive_anomalies: 3
```

**Key behavior:**
- Load and detect steps continue running normally — data collection is not interrupted
- Only the alert step is skipped while `now < suppress_until`
- After the specified time, alerts resume automatically — no second config edit needed
- The `suppress_until` value can be left in the config after it expires — it has no effect once the time has passed

The value is **UTC** and accepts `"2026-04-11 18:00:00"`, `"2026-04-11 18:00"`,
the ISO `"2026-04-11T18:00:00"` form, or a bare date `"2026-04-11"` (midnight).
It is validated when the config is loaded (and when the
[`dtk ui` editor](project-ui.md) saves), so a malformed value is refused up
front rather than failing the metric at alert time.

In `dtk ui`, the Builder's alerting section has a **Suppress until** field, so
muting a noisy config during a known incident is a browser edit rather than a
YAML one.

### Timeline Example

```
Config: suppress_until: "2026-04-11 18:00:00"

2026-04-10 14:00 - Anomaly detected → Suppressed (before 18:00 Apr 11)
2026-04-10 15:00 - Anomaly detected → Suppressed
2026-04-11 12:00 - Anomaly detected → Suppressed
2026-04-11 18:01 - Anomaly detected → Alert sent ✓ (suppress period ended)
2026-04-11 19:00 - Anomaly detected → Normal cooldown rules apply
```

### When to Use

| Scenario | Use |
|----------|-----|
| Known issue being fixed, ETA ~6 hours | `suppress_until: "<now + 6h>"` |
| Planned maintenance window | `suppress_until: "<end of window>"` |
| Permanently disable alerting | `enabled: false` |
| Reduce alert frequency | `alert_cooldown: "1hour"` |

## Recovery Notifications

In addition to cooldown reset, detectkit can send a separate notification when a metric **returns to normal** after an anomaly.

### Enabling Recovery Notifications

```yaml
alerting:
  enabled: true
  channels:
    - mattermost_ops
  consecutive_anomalies: 3
  notify_on_recovery: true   # Send notification when metric recovers
```

### Recovery Logic

Recovery notification is sent when **all** of the following are true:

1. A previous anomaly alert was sent for this metric
2. The metric has returned to normal (no blocking anomalies at the latest point)
3. A recovery notification has not already been sent for this incident

Recovery is **direction-aware**: only anomalies matching the alert's
direction block recovery. For example, after a "down" alert a fresh "up"
anomaly does not prevent the recovery notification — the original alert
condition no longer holds.

```
Timeline with notify_on_recovery: true and consecutive_anomalies: 3:

10:00 - 1st anomaly
10:10 - 2nd anomaly
10:20 - 3rd anomaly  → ALERT sent ("🔴 Alert: cpu_usage")
10:30 - Normal point
10:40 - Normal point → RECOVERY sent ("🟢 Alert cleared: cpu_usage")
10:50 - Normal point
11:00 - NEW 1st anomaly
...
11:20 - NEW 3rd anomaly → ALERT sent (new incident)
11:30 - Normal point    → RECOVERY sent (new recovery)
```

### Fraction-Rule Hysteresis

When a metric also configures the [fraction-based alert
window](alerting.md#fraction-based-alert-window-optional) (`anomaly_window` +
`min_anomaly_share`), recovery adds one more condition: besides a clean
latest point, the trailing window's share must also drop **below half** the
configured `min_anomaly_share` threshold before a recovery notification
sends. Without this, a share hovering right around the threshold (e.g. 29%
against a 30% bar) would flip alert → recover → alert on every small
fluctuation. Metrics configured with only `consecutive_anomalies` are
unaffected — recovery works exactly as described above.

### Custom Recovery Template

Use `template_recovery` to customize the recovery message. Supports the same variables as anomaly templates, plus `{status}`:

```yaml
alerting:
  notify_on_recovery: true
  template_recovery: "{metric_name} recovered at {timestamp}\nValue: {value} | Interval: {confidence_interval}"
```

**Available template variables:**

| Variable | Description |
|---|---|
| `{metric_name}` | Metric name |
| `{timestamp}` | Timestamp of the last detection point |
| `{timezone}` | Configured timezone |
| `{value}` | Metric value at recovery point |
| `{value_display}` | NaN-safe value string — always renders, falls back to `"no data"` (used by the default recovery template) |
| `{confidence_lower}` | Lower confidence bound |
| `{confidence_upper}` | Upper confidence bound |
| `{confidence_interval}` | Formatted as `[lower, upper]` |
| `{expected_range}` | One-sided aware expected band (`>= lo` / `<= hi` / `[lo, hi]` / `N/A`) |
| `{detector_name}` | Detector that was monitoring |
| `{min_detectors}` / `{direction_policy}` / `{consecutive_required}` | The rule of the alert that cleared (echoed so recovery names the same condition) |
| `{status}` | Always `"RECOVERED"` in recovery messages |
| `{mentions}` | Formatted mentions string (e.g., `@user1 @user2`), empty if none |
| `{mentions_line}` | Same as `{mentions}` with leading newline, empty if none |

### Recovery with Cooldown

Recovery notifications work independently of `alert_cooldown`. The cooldown only applies to anomaly alerts. Recovery is always sent once per incident regardless of cooldown settings.

```yaml
alerting:
  alert_cooldown: "30min"
  cooldown_reset_on_recovery: true  # Resets cooldown timer on recovery
  notify_on_recovery: true          # Also sends a recovery notification
```

### Complete Example

```yaml
name: api_response_time_p95
description: API response time 95th percentile
interval: "5min"

query: |
  SELECT
    timestamp,
    quantile(0.95)(response_time_ms) as value
  FROM http_requests
  WHERE timestamp >= '{{ dtk_start_time }}'
    AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

detectors:
  - type: mad
    params:
      threshold: 3.5
      window_size: 288  # 24 hours

alerting:
  enabled: true
  timezone: "UTC"

  channels:
    - mattermost_ops
    - slack_incidents

  # Anomaly filtering
  min_detectors: 1
  direction: "any"
  consecutive_anomalies: 3

  # Alert cooldown
  alert_cooldown: "30min"              # No more than 1 alert per 30 minutes
  cooldown_reset_on_recovery: true     # Alert again when new issue after recovery

  # Recovery notifications
  notify_on_recovery: true             # Send notification when metric stabilizes
  template_recovery: "{metric_name} is back to normal at {timestamp}"

  # Special alerts
  no_data_alert: false
```

### Best Practices

1. **Start with recovery reset**: Use `cooldown_reset_on_recovery: true` initially
2. **Enable recovery notifications**: `notify_on_recovery: true` is recommended for critical metrics
3. **Tune cooldown duration**: Match to your team's response time (15min - 1hour typical)
4. **Adjust for interval**: Faster intervals need longer cooldowns
5. **Monitor alert frequency**: Track via `_dtk_alert_states.alert_count` in database
6. **Use strict mode sparingly**: Only for very noisy experimental metrics
7. **Gate the scheduler on the exit code**: cooldown controls alert *spam*, not
   pipeline *health* — have cron/CI fail on `dtk run`'s non-zero exit (see
   [Exit Codes](../reference/cli.md#exit-codes)) so a crashed run is caught
   even while cooldown is quietly suppressing the alert side

> **Note**: Alert state (last alert/recovery timestamps, alert counter)
> lives in the `_dtk_alert_states` table, keyed by metric and alert
> config block. The table is created automatically — no manual migration
> needed.

### Disabling Cooldown

Omit `alert_cooldown` or set to `null` (this is the default):

```yaml
alerting:
  enabled: true
  channels:
    - mattermost_ops
  consecutive_anomalies: 3
  # No alert_cooldown = alert on EVERY run while conditions hold
```

**Warning**: Without a cooldown, a persistent anomaly fires a duplicate
alert on every `dtk run` (e.g. every cron tick). Setting `alert_cooldown`
is recommended for production metrics.
