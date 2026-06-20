# Templates, mentions & testing

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

The default message foregrounds the **alert** (the rule that fired and the
parameters it fired with); the anomaly appears as supporting evidence below.

```
⚠ Alert: {metric_name}
{description_line}Quorum {detector_count}/{min_detectors} · direction {direction} (policy {direction_policy}) · consecutive {consecutive_count}/{consecutive_required}
Rule: min_detectors={min_detectors} · direction={direction_policy} · consecutive={consecutive_required}

Latest point (evidence):
· Time: {timestamp}
· Value: {value_display} | Expected: {expected_range}
· Severity: {severity:.2f}
Detectors: {detector_name}
Parameters: {detector_params}
{mentions_line}
```

The first line names the **alert** and the metric. The `Quorum … · direction …
· consecutive …` line shows the observed match against the rule (`actual/required`),
and the `Rule:` line restates the configured thresholds. The detector value,
expected range and severity follow as evidence. `{expected_range}` renders
one-sided detector bounds cleanly (e.g. `>= 7.00` for a lower-only
`manual_bounds`) instead of `[7.00, nan]`.

### Creating Custom Template

1. Create template file in `templates/` directory:

```jinja2
# templates/custom_alert.j2
Alert: {{ metric_name }}

Current value: {{ value|round(2) }}
Expected range: [{{ confidence_lower|round(2) }}, {{ confidence_upper|round(2) }}]

Severity: {{ severity|round(2) }} ({{ direction }})
Detected by: {{ detector_name }}

Time: {{ timestamp }} {{ timezone }}

{% if consecutive_count > 1 %}
Persisting for {{ consecutive_count }} consecutive points!
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
| `expected_range` | One-sided aware expected band: `>= lo`, `<= hi`, `[lo, hi]`, or `"N/A"`. Renders one-sided detector bounds cleanly instead of `[7.00, nan]` | all |
| `detector_name` | Detector that triggered (e.g., `"MADDetector:threshold=3.0"`); `"N detectors"` when several detectors formed the quorum | anomaly, recovery |
| `detector_count` | Observed number of detectors that agreed (the quorum size that fired) | anomaly |
| `min_detectors` | Configured quorum threshold the alert fired on (the rule) | anomaly, recovery |
| `severity` | Severity score; max across the quorum for multi-detector alerts | anomaly |
| `direction` | Observed/locked anomaly direction: `"up"` or `"down"`; also `"mixed"` for an `any`-policy quorum spanning both up and down, and `"none"` for no-data/recovery | anomaly |
| `direction_policy` | Configured direction rule: `"same"`, `"any"`, `"up"`, `"down"` | anomaly, recovery |
| `consecutive_count` | Observed number of consecutive anomalies | anomaly |
| `consecutive_required` | Configured consecutive threshold the alert fired on (the rule) | anomaly, recovery |
| `status` | `"ANOMALY"`, `"RECOVERED"`, `"NO_DATA"`, or `"ERROR"` | all (v0.5.0 added NO_DATA / ERROR) |
| `error_type` / `error_message` | Exception details | error only (v0.5.0) |
| `description` / `description_line` | Metric description | all |
| `mentions` / `mentions_line` | Formatted mentions | all |

All variables are always substitutable in every alert kind — the
"Available in" column marks where a value is *meaningful*, not where the
placeholder is valid. Using a variable outside its listed kinds renders a
neutral fallback rather than raising a `KeyError`.

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

This sends a mock alert through configured channels with fake data. The mock
uses the alert config's own rule (`min_detectors` / `direction` /
`consecutive_anomalies`), so the preview matches what a real firing would look
like — here with the defaults (`min_detectors: 1`, `direction: same`,
`consecutive_anomalies: 3`):

```
⚠ Alert: api_response_time
Quorum 1/1 · direction up (policy same) · consecutive 3/3
Rule: min_detectors=1 · direction=same · consecutive=3

Latest point (evidence):
· Time: 2026-06-12 14:30:00 (UTC)
· Value: 0.8532 | Expected: [0.45, 0.62]
· Severity: 4.52
Detectors: MADDetector:threshold=3.0
Parameters: {"threshold": 3.0, "window_size": 8640}
```

**Use cases**:
- Verify webhook URLs work
- Check alert formatting
- Test custom templates
- Validate channel permissions

