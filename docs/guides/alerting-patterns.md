# Patterns & troubleshooting

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

### Pattern 5: Flapping Incidents (Fraction-Based Window)

```yaml
name: payment_success_rate
detectors:
  - type: mad
    params:
      threshold: 3.0

alerting:
  channels:
    - slack_critical
  consecutive_anomalies: 3   # still fires on an unbroken streak
  anomaly_window: "30min"    # OR: fire on a flapping incident too
  min_anomaly_share: 0.3     # >=30% of the last 30min's points anomalous
```

**Note**: A real incident sometimes flickers — mostly anomalous, but with an
occasional normal-looking point that resets a pure `consecutive_anomalies`
chain before it reaches threshold. `anomaly_window` + `min_anomaly_share`
catch it anyway: the rule fires once enough of the trailing window is
anomalous, independent of an unbroken streak. See [Alerting →
Fraction-Based Alert Window](alerting.md#fraction-based-alert-window-optional).

## Troubleshooting

### No Alerts Received

**Checklist**:
1. `alerting.enabled: true` in metric config
2. Channels exist in `profiles.yml`
3. Recent anomalies detected (check `_dtk_detections` table)
4. Consecutive anomaly threshold met
5. Direction filter not blocking alerts

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

### 6. Gate Your Scheduler on the Exit Code

Alert tuning (this whole guide) is about *which* anomalies notify — it says
nothing about whether the pipeline itself ran. `dtk run` returns a reliable
exit code (`0` success, `1` failure, `2` usage error — see [Exit
Codes](../reference/cli.md#exit-codes)), so have cron/CI fail the job when it
does, independent of `error_alerting`:

```bash
dtk run --select "*" || alert-oncall "detectkit run failed"
```

## See Also

- [Configuration Guide](configuration.md) - Alert configuration options
- [Detectors Guide](detectors.md) - Reducing false positives
- [CLI Reference](../reference/cli.md) - `dtk test-alert` command
