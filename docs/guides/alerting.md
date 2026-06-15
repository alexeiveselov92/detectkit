# Alerting Guide

This guide explains how to configure and customize alerting in detectkit.

## Overview

detectkit's alerting system:
- ✅ Checks only recent data (not historical)
- ✅ Requires consecutive anomalies (reduces false positives)
- ✅ Supports multiple channels (Mattermost, Slack, Telegram, Email)
- ✅ Filters by detector agreement and direction
- ✅ Customizable templates
- ✅ @mentions for users and groups (channel-agnostic)

## How Alerting Works

### Alert Flow

```
1. Detection Step
   └─> Detects anomalies in recent data

2. Alert Step
   ├─> Load the most recent detection results
   ├─> Per timestamp: check the quorum —
   │   at least min_detectors anomalies matching the direction policy
   ├─> Require consecutive_anomalies quorum points,
   │   each exactly one interval apart (a grid gap breaks the chain)
   └─> Send alert through configured channels
```

### Key Concepts

**Quorum**: at a given timestamp, the set of anomalous detections that
match the `direction` policy. A timestamp counts toward an alert only
when at least `min_detectors` detections qualify. See
[Alert Filtering](#alert-filtering) for the exact rules per direction.

**Consecutive Anomalies**: the latest `consecutive_anomalies` timestamps
must each satisfy the quorum AND be exactly one metric interval apart.

**Example** with `consecutive_anomalies: 3` (10-min interval):
```
10:00 Quorum ✓
10:10 Quorum ✓
10:20 Quorum ✓  → Alert sent!
10:30 Normal ✗  → chain reset
```

A gap in the detection grid (missing detection row) breaks the chain:
```
10:00 Quorum ✓
10:10 (no detection row)
10:20 Quorum ✓
10:30 Quorum ✓  → only 2 consecutive points, no alert
```

**Recent Data Only**: Alerts check only the most recent points, not historical data.

## Basic Configuration

### Minimal Setup

```yaml
name: api_response_time
interval: 5min
query: "..."

detectors:
  - type: mad
    params:
      threshold: 3.0

# Enable alerting
alerting:
  enabled: true
  channels:
    - mattermost_ops
```

This uses defaults:
- `consecutive_anomalies: 3` - Requires 3 consecutive anomalous points
- `min_detectors: 1` - One detector is enough
- `direction: "same"` - The detectors forming the quorum must agree on one direction
- `alert_cooldown: null` - No cooldown: a persisting anomaly re-alerts on every `dtk run` (set a cooldown for production metrics)

### Complete Configuration

```yaml
alerting:
  enabled: true                  # Enable/disable alerting
  timezone: "Europe/Moscow"      # Display timezone (default: UTC)

  # Channels
  channels:
    - mattermost_ops
    - slack_critical
    - email_team

  # Filtering
  min_detectors: 1               # Detectors that must satisfy the quorum per point
  direction: "same"              # "same", "any", "up", "down"
  consecutive_anomalies: 3       # Consecutive quorum points required

  # Cooldown (default null = re-alert on EVERY run while anomaly persists)
  alert_cooldown: "2h"

  # Special alerts
  no_data_alert: false           # Alert on missing data

  # Custom templates
  template_single: null          # Used when consecutive_count <= 1
  template_consecutive: null     # Used for streaks; each falls back to the other
```

## Alert Channels

Channels are configured in `profiles.yml` and referenced by name in metric configs.

### Mattermost

```yaml
# In profiles.yml
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    username: "detectkit"
    icon_emoji: ":warning:"
    channel: "alerts"          # Explicit channel override
    timeout: 10

# In metric config
alerting:
  channels:
    - mattermost_ops
```

**Parameters**:
- `webhook_url` (required) - Mattermost incoming webhook URL
- `username` (default: `"detectkit"`) - Bot display name
- `icon_emoji` (default: `":warning:"`) - Bot icon
- `channel` (optional) - Override webhook's default channel
- `timeout` (default: `10`) - HTTP timeout in seconds

### Slack

```yaml
# In profiles.yml
alert_channels:
  slack_ops:
    type: slack
    webhook_url: "https://hooks.slack.com/services/xxx"
    username: "detectkit"
    icon_emoji: ":warning:"
    channel: "#alerts"

# In metric config
alerting:
  channels:
    - slack_ops
```

Same parameters as Mattermost (Slack-compatible API).

### Telegram

```yaml
# In profiles.yml
alert_channels:
  telegram_alerts:
    type: telegram
    bot_token: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    chat_id: "-1001234567890"

# In metric config
alerting:
  channels:
    - telegram_alerts
```

**Parameters**:
- `bot_token` (required) - Telegram bot API token
- `chat_id` (required) - Target chat/channel ID

**Setup**:
1. Create bot with @BotFather
2. Get bot token
3. Add bot to channel
4. Get chat ID (use @userinfobot)

### Email

```yaml
# In profiles.yml
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

# In metric config
alerting:
  channels:
    - email_ops
```

**Parameters**:
- `smtp_host` (required) - SMTP server hostname
- `smtp_port` (required) - SMTP port (587 for TLS, 465 for SSL)
- `from_email` (required) - Sender email
- `to_emails` (required) - List of recipients
- `smtp_user` (optional) - SMTP authentication username
- `smtp_password` (optional) - SMTP authentication password
- `use_tls` (default: `true`) - Use TLS encryption

### Multiple Channels

Send alerts to multiple channels within a single config:

```yaml
alerting:
  enabled: true
  channels:
    - mattermost_ops       # Team chat
    - slack_critical       # Escalation channel
    - email_oncall         # On-call engineer
```

All channels receive the same alert message.

### Multiple Alert Configurations

You can define multiple independent alerting configs per metric — each with its own channels, timezone, template, and conditions:

```yaml
alerting:
  - enabled: true
    channels:
      - mattermost_ops
    timezone: "Europe/Moscow"
    consecutive_anomalies: 3

  - enabled: true
    channels:
      - slack_critical
    timezone: "UTC"
    consecutive_anomalies: 1      # More sensitive for this channel
    direction: "up"               # Only upward anomalies
    template_consecutive: "templates/slack_alert.j2"
```

Each config is evaluated and sent independently. Single dict format (backward-compatible) continues to work.

> **Changed or removed an alert config?** Each block's cooldown/recovery state
> in `_dtk_alert_states` is keyed by a hash of its functional fields (channels,
> `min_detectors`, `consecutive_anomalies`, `direction`, cooldown), so editing
> those fields or removing a block leaves the old state row behind. Run
> [`dtk clean --select <metric>`](../reference/cli.md#dtk-clean) to prune it.
> (Disabling a block with `enabled: false` keeps its state — the hash is
> unchanged — so a temporarily-paused alert is never treated as orphaned.)

## Alert Filtering

The three conditions combine into one contract:

1. At every timestamp, detections from all detectors are grouped together.
2. A timestamp satisfies the **quorum** when at least `min_detectors`
   anomalies match the `direction` policy.
3. An alert fires when the latest `consecutive_anomalies` timestamps each
   satisfy the quorum AND sit on a contiguous interval grid (each point
   exactly one metric interval after the previous — gaps break the chain).

### Consecutive Anomalies

Require N consecutive quorum-satisfying points before alerting.

```yaml
alerting:
  consecutive_anomalies: 1   # Alert immediately (use with caution)
  consecutive_anomalies: 3   # Alert after 3 consecutive (recommended)
  consecutive_anomalies: 5   # Alert after 5 consecutive (conservative)
```

The points must be **grid-adjacent**: a missing detection row between two
anomalies (e.g. a day without runs, or a detector `start_time` boundary)
breaks the chain — anomalies separated by gaps are never counted as
consecutive.

**Use cases**:
- `1` - Critical metrics (errors should be 0)
- `3` - Standard (good balance)
- `5+` - Noisy metrics or high false-positive cost

### Direction Policy

Controls which anomalies count toward the quorum.

```yaml
alerting:
  direction: "same"   # Quorum must agree on ONE direction (default)
  direction: "any"    # Every anomaly counts, regardless of direction
  direction: "up"     # Only anomalies above the interval count
  direction: "down"   # Only anomalies below the interval count
```

- **`"up"` / `"down"`**: only anomalies in that direction count toward
  `min_detectors`. Detectors firing the other way are ignored — they
  neither help nor block the quorum.
- **`"any"`**: every anomaly counts; one up-anomaly plus one
  down-anomaly together satisfy `min_detectors: 2`.
- **`"same"`** (default): at the latest point, at least `min_detectors`
  detectors must agree on ONE direction. Up- and down-anomalies are
  counted separately — disagreement is not consensus. If both directions
  independently reach quorum, the side with more detectors wins; ties go
  to the more severe side. The winning direction is then **locked for
  the whole consecutive chain**: every older point must satisfy the
  quorum in that same direction.

**Use cases**:
- `"same"` - Multiple detectors (reduce false positives, default)
- `"any"` - Most single-detector metrics (any deviation matters)
- `"up"` - CPU usage, error rates (high is bad, low is good)
- `"down"` - Cache hit rate, uptime (low is bad, high is good)

### Multiple Detector Agreement

`min_detectors` is how many detectors must satisfy the direction policy
at **every** point in the consecutive chain:

```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
  - type: zscore
    params:
      threshold: 3.0

alerting:
  min_detectors: 1  # One qualifying detector per point is enough
  min_detectors: 2  # Both detectors must qualify at each point
```

**Use cases**:
- `1` - High recall (catch more anomalies, some false positives)
- `N` (all) - High precision (fewer false positives, may miss some)

### Worked Examples

Two detectors A and B, `min_detectors: 2`, both anomalous at the latest
point:

| `direction` | A says | B says | Result |
|---|---|---|---|
| `same` | up | down | **No alert** — disagreement is not consensus |
| `same` | up | up | Quorum met; direction "up" locked for the chain |
| `up` | up | down | **No quorum** — only one "up" anomaly, needs 2 ups |
| `up` | up | up | Quorum met |
| `down` | up | up | **No quorum** — "up" anomalies are ignored, never blocking |
| `any` | up | down | Quorum met — every anomaly counts |

### Alert Payload

The message is built from the **highest-severity** detection of the
latest quorum (ties broken by detector name, so the choice is
deterministic): value, confidence interval and timestamp come from that
record. For multi-detector alerts, `{detector_name}` renders as
`"N detectors"`, `{severity}` is the maximum across the quorum, and
per-detector metadata is included.

### Combined Filtering Example

```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
  - type: zscore
    params:
      threshold: 2.5

alerting:
  min_detectors: 2          # Both must qualify at each point
  direction: "same"         # ...and agree on one direction
  consecutive_anomalies: 3  # ...for 3 grid-adjacent points
```

This creates a **very conservative** alert:
- Both detectors must report an anomaly
- Both must fire in the same direction (both "up" or both "down")
- That must hold for 3 consecutive, gap-free points

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
10:20 - 3rd anomaly  → ALERT sent ("Anomaly detected in cpu_usage")
10:30 - Normal point
10:40 - Normal point → RECOVERY sent ("Metric recovered: cpu_usage")
10:50 - Normal point
11:00 - NEW 1st anomaly
...
11:20 - NEW 3rd anomaly → ALERT sent (new incident)
11:30 - Normal point    → RECOVERY sent (new recovery)
```

### Custom Recovery Template

Use `template_recovery` to customize the recovery message. Supports the same variables as anomaly templates, plus `{status}`:

```yaml
alerting:
  notify_on_recovery: true
  template_recovery: "✅ {metric_name} recovered at {timestamp}\nValue: {value} | Interval: {confidence_interval}"
```

**Available template variables:**

| Variable | Description |
|---|---|
| `{metric_name}` | Metric name |
| `{timestamp}` | Timestamp of the last detection point |
| `{timezone}` | Configured timezone |
| `{value}` | Metric value at recovery point |
| `{confidence_lower}` | Lower confidence bound |
| `{confidence_upper}` | Upper confidence bound |
| `{confidence_interval}` | Formatted as `[lower, upper]` |
| `{detector_name}` | Detector that was monitoring |
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
  template_recovery: "✅ {metric_name} is back to normal at {timestamp}"

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

## Missing Data Alerts (v0.5.0)

Detect when a metric stops producing data — the source query returned
no rows for the latest interval, or the row's value is `NULL` / `NaN`.

> **Note**: prior to v0.5.0 the `no_data_alert` flag existed but was
> never read by the orchestrator. If you set it to `true` on an older
> version and saw nothing fire, that was the bug. Upgrading to v0.5.0
> is enough — no schema change.

### How It Works

At the alert step, after the regular anomaly check, detectkit:

1. Computes the **last complete interval** by flooring `now` to an
   interval boundary and stepping back one interval (the in-progress
   bucket is intentionally skipped — it's not "missing", it's "not
   yet ready").
2. Looks up that timestamp in `_dtk_datapoints` for the metric.
3. Fires a no-data alert if the row is missing OR the row exists with
   a `NULL` / `NaN` value. The load step writes `NaN` (never `0`) for
   gap-filled intervals, so the two cases are equivalent.

`min_detectors` and `consecutive_anomalies` **do not apply** to no-data
— missing data is a single binary metric-level signal, not a
per-detector vote. The check honours `alert_cooldown` and
`suppress_until` like anomaly alerts; no-data and anomaly alerts share
the same cooldown state within an alert config block.

### Configuration

```yaml
alerting:
  enabled: true
  channels:
    - mattermost_ops
  no_data_alert: true                # default: false
  template_no_data: null             # optional custom body
  alert_cooldown: "1hour"            # respected by no-data path
```

### Custom Template

```yaml
alerting:
  no_data_alert: true
  template_no_data: |
    🟠 {metric_name} stopped reporting
    {description_line}Last expected interval: {timestamp} ({timezone})
    Action: check the upstream pipeline / source DB
    {mentions}
  mentions: [oncall_engineer]
```

**Available variables** (no `{value}` / `{confidence_interval}` — there
is no value):

| Variable | Description |
|---|---|
| `{metric_name}` | Metric name |
| `{timestamp}` | Timestamp of the missing interval (formatted, in `{timezone}`) |
| `{timezone}` | Configured timezone |
| `{description}` | Metric `description`, empty string if none |
| `{description_line}` | Same with trailing newline, empty if none |
| `{status}` | Always `"NO_DATA"` |
| `{mentions}` / `{mentions_line}` | Formatted mentions |
| `{value_display}` | Always the literal string `"no data"` |

If a template uses `{value:.2f}` or another numeric format spec on a
no-data alert, detectkit falls back to the default no-data template
rather than crashing — but write the template with no-data in mind.

### Visual Distinction

Webhook channels (Slack/Mattermost) render no-data alerts with the
amber color `#F0AD4E` to distinguish them from anomalies (red) and
recoveries (green).

### When to Use

- Cron-driven loaders where source absence is a real failure signal
  (e.g., revenue by hour — empty hour means the upstream ETL is broken)
- Health-check style metrics where "no data" is meaningful
- **Don't** enable on metrics with naturally sparse intervals — you'll
  just spam channels every cron tick

## Project-Level Error Alerts (v0.5.0)

When a metric pipeline crashes (DB unreachable, query timeout, lock
acquisition failure, channel HTTP error), the failure is logged and
the run moves to the next metric. With CH down for the whole project
all metrics fail in a row and ops finds out only when expected alerts
stop arriving.

`error_alerting` in `detectkit_project.yml` catches that case and
sends one notification per `dtk run`.

### Configuration

```yaml
# detectkit_project.yml
name: my_monitoring
default_profile: prod

error_alerting:
  enabled: true
  channels:
    - mattermost_oncall          # channels resolved from profiles.yml
  mentions: [oncall_engineer, here]
  timezone: "Europe/Moscow"
  template: |                    # optional, defaults documented below
    🔥 Pipeline failure
    Metric: {metric_name}
    {error_type}: {error_message}
    Time: {timestamp} ({timezone})
    {mentions}
```

See the [Configuration Guide](configuration.md#error_alerting-object-optional)
for full field reference.

### Behaviour

- **One alert per run.** After the first error alert fires, an
  in-process flag suppresses subsequent failures and the run aborts
  (`result["abort_run"] = True` → CLI breaks the metric loop). If the
  source DB is down, processing the next 30 metrics won't change
  anything.
- **No persistent cooldown** between separate `dtk run` invocations.
  Storing state in the DB doesn't help when the DB itself is down,
  and a local file would break the dbt-style stateless model. Cron
  schedule cadence covers spacing.
- **Channel failures are swallowed.** A flaky webhook cannot crash the
  run — dispatch is wrapped in its own `try/except`.
- Channels are resolved from the same `profiles.yml` channel block as
  per-metric alerts. Reuse the names, no config duplication.

### Default Template

```
Pipeline failed for metric: {metric_name}
{description_line}Time: {timestamp}
Error: {error_type}: {error_message}
{mentions_line}
```

Title (webhook channels): `[{project_name}] Pipeline error: {metric_name}`
when `project_name` is set in `detectkit_project.yml`, otherwise just
`Pipeline error: {metric_name}` (backwards-compat). The bracketed prefix
makes it obvious which project crashed when multiple detectkit instances
share an alert channel.

### Template Variables

| Variable | Description |
|---|---|
| `{metric_name}` | Name of the metric whose pipeline failed (or `<startup>` for early failures) |
| `{project_name}` | `detectkit_project.yml` `name` field, or empty string (v0.5.3) |
| `{project_name_prefix}` | `"[<project_name>] "` when set, empty string otherwise (v0.5.3) |
| `{error_type}` | Exception class name (e.g., `ConnectionRefusedError`) |
| `{error_message}` | Exception `str(exc)` |
| `{timestamp}` | When the alert was built (formatted in `{timezone}`) |
| `{timezone}` | `error_alerting.timezone` or `UTC` |
| `{status}` | Always `"ERROR"` |
| `{mentions}` / `{mentions_line}` | Formatted mentions |
| `{description}` / `{description_line}` | Empty for error alerts (no metric context) |

Webhook channels render error alerts in red (same as anomalies).

### Custom Template with Project Name and Mentions

```yaml
# detectkit_project.yml
name: my_monitoring   # ← surfaces in error alert title as "[my_monitoring] Pipeline error: ..."
default_profile: prod

error_alerting:
  enabled: true
  channels: [mattermost_oncall]
  mentions: [oncall_engineer, here]   # critical alert — wake someone up
  template: |
    {project_name_prefix}🔥 pipeline crashed
    Metric: {metric_name}
    {error_type}: {error_message}
    Time: {timestamp} ({timezone})
    {mentions}
```

### When to Use

- Production deployments where silent failure is unacceptable
- Multi-metric projects where one infra issue affects everything
- Pair with cron monitoring (`dtk run` exit code) for full coverage —
  `error_alerting` covers in-process failures, cron monitors `dtk run`
  not running at all

## Mentions (v0.3.8)

Tag specific users or groups in alert messages. Mentions are **channel-agnostic**: you write plain usernames in metric config, and each channel formats them in its native syntax.

### Basic Setup

```yaml
alerting:
  enabled: true
  channels:
    - mattermost_ops
  consecutive_anomalies: 3
  mentions:
    - oncall_engineer
    - devops_team
```

This appends `@oncall_engineer @devops_team` to alert messages in Mattermost.

### Platform-Specific Formatting

detectkit automatically formats mentions for each platform:

| Config Value | Mattermost | Slack | Telegram | Email |
|---|---|---|---|---|
| `username` | `@username` | `@username` (display only) | `@username` | `CC: username` |
| `here` | `@here` | `<!here>` (broadcast) | `@here` | *(ignored)* |
| `channel` | `@channel` | `<!channel>` (broadcast) | `@channel` | *(ignored)* |
| `all` | `@all` | `<!everyone>` (broadcast) | `@all` | *(ignored)* |
| `U04ABCD1234` | `@U04ABCD1234` | `<@U04ABCD1234>` (real ping) | `@U04ABCD1234` | `CC: U04ABCD1234` |

> **Slack note**: Slack webhooks do **not** actually ping users with `@username` — it's display-only. For real pings, use Slack User IDs (format: `U` + alphanumeric, found in user profile > "Copy member ID").

### Special Keywords

Use these keywords for broadcast mentions:

- **`here`** — Notify active members (Mattermost: `@here`, Slack: `<!here>`)
- **`channel`** — Notify all channel members (Mattermost: `@channel`, Slack: `<!channel>`)
- **`all`** — Notify everyone (Mattermost: `@all`, Slack: `<!everyone>`)

### Custom Template Placement

By default, mentions appear at the end of the message. Use template variables for custom placement:

- **`{mentions}`** — Formatted mentions string (e.g., `@user1 @user2`), empty string if none
- **`{mentions_line}`** — Same but with a leading newline, empty string if none

```yaml
alerting:
  mentions:
    - oncall_engineer

  # Place mentions at the top of the message
  template_consecutive: |
    {mentions}
    Alert: {metric_name}
    Time: {timestamp}
    Value: {value} | CI: {confidence_interval}
    Consecutive: {consecutive_count}
```

### Mentions with Recovery

Mentions are included in both anomaly alerts and recovery notifications:

```yaml
alerting:
  mentions:
    - oncall_engineer
  notify_on_recovery: true
  template_recovery: |
    {mentions}
    Resolved: {metric_name} at {timestamp}
    Value: {value}
```

### Configuration

| Field | Type | Default | Description |
|---|---|---|---|
| `mentions` | `List[str]` | `[]` | Users/groups to mention. Plain usernames without `@`. |

No `@` prefix needed — detectkit adds the appropriate prefix for each channel.

## Timezone Display

Alerts display timestamps in UTC by default. Override per metric:

```yaml
alerting:
  timezone: "Europe/Moscow"     # MSK (UTC+3)
  timezone: "America/New_York"  # EST/EDT
  timezone: "Asia/Tokyo"        # JST (UTC+9)
```

**Note**: This only affects alert **display**. All internal timestamps remain UTC.

## Custom Alert Templates

Override default alert message format.

### Default Template

```
Anomaly detected in metric: {metric_name}
{description_line}Time: {timestamp}
Value: {value} | CI: {confidence_interval}
Direction: {direction} | Severity: {severity:.2f} | Consecutive: {consecutive_count}
Detector: {detector_name}
Parameters: {detector_params}
{mentions_line}
```

### Creating Custom Template

1. Create template file in `templates/` directory:

```jinja2
# templates/custom_alert.j2
🚨 Alert: {{ metric_name }}

Current value: {{ value|round(2) }}
Expected range: [{{ confidence_lower|round(2) }}, {{ confidence_upper|round(2) }}]

Severity: {{ severity|round(2) }} ({{ direction }})
Detected by: {{ detector_name }}

Time: {{ timestamp }} {{ timezone }}

{% if consecutive_count > 1 %}
⚠️ Persisting for {{ consecutive_count }} consecutive points!
{% endif %}
```

2. Reference in metric config:

```yaml
alerting:
  template_consecutive: templates/custom_alert.j2
```

### Available Template Variables

| Variable | Description | Available in |
|---|---|---|
| `metric_name` | Metric name | all |
| `project_name` | `detectkit_project.yml` `name`, empty if not set (v0.5.3) | all (currently populated by error alerts only) |
| `project_name_prefix` | `"[<project_name>] "` if set, else empty (v0.5.3) | all (same) |
| `timestamp` | Timestamp (formatted in `{timezone}`) | all |
| `timezone` | Timezone display name | all |
| `value` | Current metric value (numeric, or string `"no data"` for no-data) | all |
| `value_display` | NaN-safe string version — always renders, falls back to `"no data"` | all (v0.5.0) |
| `confidence_lower` / `confidence_upper` | Bounds of confidence interval | anomaly, recovery |
| `confidence_interval` | Formatted as `[lower, upper]` or `"N/A"` | all |
| `detector_name` | Detector that triggered (e.g., `"MADDetector:threshold=3.0"`); `"N detectors"` when several detectors formed the quorum | anomaly, recovery |
| `severity` | Severity score; max across the quorum for multi-detector alerts | anomaly |
| `direction` | `"up"` or `"down"` | anomaly |
| `consecutive_count` | Number of consecutive anomalies | anomaly |
| `status` | `"ANOMALY"`, `"RECOVERED"`, `"NO_DATA"`, or `"ERROR"` | all (v0.5.0 added NO_DATA / ERROR) |
| `error_type` / `error_message` | Exception details | error only (v0.5.0) |
| `description` / `description_line` | Metric description | all |
| `mentions` / `mentions_line` | Formatted mentions | all |

> **Format-spec safety**: if a template uses `{value:.2f}` (or any
> numeric format spec) on a no-data or error alert where there's no
> real value, detectkit falls back to the kind-appropriate default
> template instead of crashing. Still cleaner to write
> kind-appropriate templates from the start.

### Template Types

- **`template_single`** - Used when the alert has `consecutive_count` ≤ 1
  (i.e. `consecutive_anomalies: 1` configs)
- **`template_consecutive`** - Used for streaks (`consecutive_count` > 1)
- `template_single` and `template_consecutive` fall back to each other
  when only one is set
- **`template_recovery`** - Used for recovery notifications
- **`template_no_data`** - Used for no-data alerts
- **`error_alerting.template`** - Used for project-level pipeline errors (in `detectkit_project.yml`)

## Testing Alerts

Test alert configuration without waiting for real anomalies.

### Test Alert Command

```bash
cd my_project
dtk test-alert api_response_time
```

This sends a mock alert through configured channels with fake data:

```
Anomaly detected in metric: api_response_time
Time: 2026-06-12 14:30:00
Value: 0.8532 | CI: [0.4521, 0.6234]
Direction: above | Severity: 4.52 | Consecutive: 3
Detector: MADDetector:threshold=3.0
Parameters: {"threshold": 3.0, "window_size": 8640}
```

**Use cases**:
- Verify webhook URLs work
- Check alert formatting
- Test custom templates
- Validate channel permissions

## Common Patterns

### Pattern 1: Immediate Alerts for Critical Metrics

```yaml
name: api_errors
detectors:
  - type: manual_bounds
    params:
      upper_bound: 0  # Zero tolerance

alerting:
  channels:
    - slack_critical
  consecutive_anomalies: 1  # Alert immediately
  direction: "up"            # Only alert on increases
```

### Pattern 2: Conservative Alerts for Noisy Metrics

```yaml
name: network_latency
detectors:
  - type: mad
    params:
      threshold: 4.0  # Higher threshold

alerting:
  channels:
    - mattermost_ops
  consecutive_anomalies: 5  # Require 5 consecutive points
  direction: "up"            # Only alert on increases
```

### Pattern 3: Multi-Channel Escalation

```yaml
name: service_uptime
detectors:
  - type: manual_bounds
    params:
      lower_bound: 99.9

alerting:
  channels:
    - mattermost_ops        # Team notification
    - slack_oncall          # On-call engineer
    - email_management      # Management notification
  consecutive_anomalies: 1
```

### Pattern 4: Business Hours Only (via Filtering)

```yaml
# Metric runs 24/7, but only alert during business hours
name: office_occupancy

seasonality_columns:
  - hour

detectors:
  - type: mad
    params:
      threshold: 3.0
      # Per-hour statistics make 9-18h anomalies meaningful
      seasonality_components:
        - "hour"

alerting:
  channels:
    - mattermost_ops
  consecutive_anomalies: 2
```

**Note**: detectkit doesn't have built-in time-of-day filtering. Use external tools (cron, schedulers) to control when `dtk run` executes, or filter alerts in receiving system.

## Troubleshooting

### No Alerts Received

**Checklist**:
1. ✅ `alerting.enabled: true` in metric config
2. ✅ Channels exist in `profiles.yml`
3. ✅ Recent anomalies detected (check `_dtk_detections` table)
4. ✅ Consecutive anomaly threshold met
5. ✅ Direction filter not blocking alerts

**Debug**:
```bash
# Check recent detections
dtk run --select my_metric --steps detect

# Test alert channel
dtk test-alert my_metric
```

### Alerts Not Reaching Channel

**Mattermost/Slack**:
- Verify webhook URL is correct
- Check webhook permissions
- Test with `curl`:
  ```bash
  curl -X POST -H 'Content-Type: application/json' \
    -d '{"text":"Test message"}' \
    https://mattermost.example.com/hooks/xxx
  ```

**Telegram**:
- Verify bot token is valid
- Check bot is member of target chat
- Test with API:
  ```bash
  curl "https://api.telegram.org/bot<TOKEN>/getMe"
  ```

**Email**:
- Check SMTP credentials
- Verify firewall allows outbound SMTP
- Test with manual SMTP connection

### Too Many Alerts

**Solutions**:
1. Increase `consecutive_anomalies` threshold
2. Increase detector `threshold` parameter
3. Use `min_detectors: 2` (require multiple detectors)
4. Add seasonality to detector (if metric is seasonal)
5. Use `direction` filter (only alert on "up" or "down")

### Alerts for Wrong Direction

**Example**: Alerting when CPU drops (which is good)

**Solution**: Add direction filter
```yaml
alerting:
  direction: "up"  # Only alert on high CPU
```

### Missing Important Anomalies

**Causes**:
- `consecutive_anomalies` too high
- `min_detectors` too high
- Detector `threshold` too high

**Solutions**:
1. Lower `consecutive_anomalies` (e.g., from 5 to 3)
2. Lower `min_detectors` (e.g., from 2 to 1)
3. Lower detector `threshold` (e.g., from 4.0 to 3.0)

## Best Practices

### 1. Start Conservative, Then Tune

```yaml
# Initial setup
alerting:
  consecutive_anomalies: 5  # Conservative
  min_detectors: 2          # Require agreement

# After observing false positive rate, tune down
alerting:
  consecutive_anomalies: 3  # Balanced
  min_detectors: 1          # Any detector
```

### 2. Use Different Channels for Different Severities

```yaml
# Critical metrics
alerting:
  channels:
    - slack_oncall

# Informational metrics
alerting:
  channels:
    - mattermost_monitoring
```

### 3. Document Alert Rationale

```yaml
alerting:
  channels:
    - slack_ops
  consecutive_anomalies: 1  # Critical: errors should never occur
  direction: "up"            # Only alert on error increases
```

### 4. Test Alerts Before Production

```bash
# Always test before deploying
dtk test-alert new_metric
```

### 5. Monitor Alert Volume

If receiving too many alerts:
- Team becomes desensitized
- Real issues get missed
- Alert fatigue sets in

Aim for: **< 5 alerts per day per team**

## See Also

- [Configuration Guide](configuration.md) - Alert configuration options
- [Detectors Guide](detectors.md) - Reducing false positives
- [CLI Reference](../reference/cli.md) - `dtk test-alert` command
