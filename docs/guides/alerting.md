# Alerting Guide

This guide explains how to configure and customize alerting in detectkit.

## Overview

detectkit's alerting system:
- ✅ Checks only recent data (not historical)
- ✅ Requires consecutive anomalies (reduces false positives)
- ✅ Supports multiple channels (Mattermost, Slack, Telegram, Email)
- ✅ Filters by detector agreement and direction
- ✅ Customizable templates

## How Alerting Works

### Alert Flow

```
1. Detection Step
   └─> Detects anomalies in recent data

2. Alert Step
   ├─> Load N most recent detection results
   ├─> Check if conditions met:
   │   ├─> Consecutive anomalies ≥ threshold
   │   ├─> Direction matches (if specified)
   │   └─> Min detectors agree (if multiple)
   └─> Send alert through configured channels
```

### Key Concepts

**Consecutive Anomalies**: Requires N consecutive points to be anomalous before alerting.

**Example** with `consecutive_anomalies: 3`:
```
Point 1: Anomaly ✓
Point 2: Anomaly ✓
Point 3: Anomaly ✓  → Alert sent!
Point 4: Normal  ✗  → Reset counter
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
- `consecutive_anomalies: 3` - Requires 3 consecutive anomalies
- `min_detectors: 1` - Any detector can trigger
- `direction: "same"` - All detectors must agree on direction

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
  min_detectors: 1               # Min detectors that must agree
  direction: "same"              # "same", "any", "up", "down"
  consecutive_anomalies: 3       # Consecutive points required

  # Special alerts
  no_data_alert: false           # Alert on missing data

  # Custom templates
  template_single: null          # Custom template file
  template_consecutive: null     # Custom template file
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

Send alerts to multiple channels:

```yaml
alerting:
  enabled: true
  channels:
    - mattermost_ops       # Team chat
    - slack_critical       # Escalation channel
    - email_oncall         # On-call engineer
```

All channels receive the same alert message.

## Alert Filtering

### Consecutive Anomalies

Require N consecutive anomalous points before alerting.

```yaml
alerting:
  consecutive_anomalies: 1   # Alert immediately (use with caution)
  consecutive_anomalies: 3   # Alert after 3 consecutive (recommended)
  consecutive_anomalies: 5   # Alert after 5 consecutive (conservative)
```

**Use cases**:
- `1` - Critical metrics (errors should be 0)
- `3` - Standard (good balance)
- `5+` - Noisy metrics or high false-positive cost

### Direction Matching

Control which anomaly directions trigger alerts.

```yaml
alerting:
  direction: "any"    # Alert on any anomaly (above or below)
  direction: "same"   # All detectors must agree on direction
  direction: "up"     # Only alert when value is above bounds
  direction: "down"   # Only alert when value is below bounds
```

**Use cases**:
- `"any"` - Most metrics (any deviation matters)
- `"same"` - Multiple detectors (reduce false positives)
- `"up"` - CPU usage, error rates (high is bad, low is good)
- `"down"` - Cache hit rate, uptime (low is bad, high is good)

### Multiple Detector Agreement

With multiple detectors, control how many must agree:

```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
  - type: zscore
    params:
      threshold: 3.0

alerting:
  min_detectors: 1  # Any detector triggers alert
  min_detectors: 2  # Both detectors must agree
```

**Use cases**:
- `1` - High recall (catch more anomalies, some false positives)
- `N` (all) - High precision (fewer false positives, may miss some)

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
  min_detectors: 2         # Both must agree
  direction: "same"         # Must agree on direction
  consecutive_anomalies: 3  # 3 consecutive points
```

This creates a **very conservative** alert:
- Both detectors must detect anomaly
- Both must say "above" or both say "below"
- Must persist for 3 consecutive points

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
⚠️ Anomaly Detected: {metric_name}

Value: {value}
Expected: {confidence_lower} - {confidence_upper}
Severity: {severity}
Direction: {direction}
Detector: {detector_name}

Timestamp: {timestamp} ({timezone})
Consecutive: {consecutive_count} points
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

- `metric_name` - Metric name
- `timestamp` - Timestamp (formatted)
- `timezone` - Timezone display name
- `value` - Current metric value
- `confidence_lower` - Lower bound of confidence interval
- `confidence_upper` - Upper bound of confidence interval
- `detector_name` - Detector that triggered (e.g., "MADDetector:threshold=3.0")
- `severity` - Severity score (how far from bounds)
- `direction` - "above" or "below"
- `consecutive_count` - Number of consecutive anomalies

### Template Types

- **`template_single`** - Used for first anomaly in sequence
- **`template_consecutive`** - Used for consecutive anomalies (default: same as single)

## Testing Alerts

Test alert configuration without waiting for real anomalies.

### Test Alert Command

```bash
cd my_project
dtk test-alert --metric api_response_time
```

This sends a mock alert through configured channels with fake data:

```
⚠️ Anomaly Detected: api_response_time

Value: 0.8532
Expected: 0.4521 - 0.6234
Severity: 4.52
Direction: above
Detector: MADDetector:threshold=3.0

Timestamp: 2024-03-15 14:30:00 UTC
Consecutive: 3 points
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
  - name: hour
    extract: hour

detectors:
  - type: mad
    params:
      threshold: 3.0
      # Only anomalies during 9-18 hours will be meaningful
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
dtk test-alert --metric my_metric
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
dtk test-alert --metric new_metric
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
