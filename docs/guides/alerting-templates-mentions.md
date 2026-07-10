# Templates, mentions & testing

## Mentions

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

The default message foregrounds the **alert** — first *how long it has been
going on* (the plain-language lead), then the rule that fired, with the anomaly
as supporting evidence below. The order is the same on every channel and for
both anomaly and recovery: **description → Rule → Value/Expected**.

```
🔴 {project_name_prefix}Alert: {metric_name}
{description_line}{anomaly_lead}
Rule: {rule_display}

Value: {value_display} | Expected: {expected_range}
Quorum: {detector_count}/{min_detectors} · {direction}
Severity: {severity:.2f}
{window_line}Detectors: {detector_name}
Parameters: {detector_params}
{dashboard_line}{help_line}{mentions_line}
```

The first line names the **alert** and the metric, led by the project name as a
`[name] ` prefix (from `detectkit_project.yml`) so two projects posting to the
same channel stay distinguishable while keeping the default brand bot name +
avatar. See [Channels](alerting-channels.md) for where each channel surfaces it.
`{anomaly_lead}` answers *"when did this start, how long has it been running?"*
— e.g. `Anomalous for 2h 30m — 15 consecutive 10min intervals.` (the metric
interval, the true streak length and the wall-clock duration). The `Rule:` line
sits right above the evidence it explains and restates the configured
thresholds via `{rule_display}` — for a config with no [fraction-based alert
window](alerting.md#fraction-based-alert-window-optional) this renders the
same `min_detectors=… · direction=… · consecutive=…` chip as before; a
share-configured metric also names `anomaly_window` / `min_anomaly_share`,
leading with whichever rule actually fired. `{window_line}` gives the
problematic span as `Anomaly began: … | Latest reading: …` (and
`Anomaly began: … | Alert fired: … | Recovered: …` on recovery — where
**Alert fired** is the on-grid moment the rule first tripped, distinct from the
onset).
`{expected_range}` renders one-sided detector bounds cleanly (e.g. `>= 7.00`
for a lower-only `manual_bounds`) instead of `[7.00, nan]`.

> **How long is "true"?** The streak length / onset are resolved at fire time by
> looking back over the detection history until the run breaks (bounded — a run
> older than the lookback window renders as `over …`), so it reflects the real
> incident, not just the `consecutive_anomalies` points the rule needs. The
> recovery message reports the same span the just-cleared incident covered
> (`Incident lasted …`).

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
| `project_name` | `detectkit_project.yml` `name`, empty if not set | all — populated for every alert by the pipeline |
| `project_name_prefix` | `"[<project_name>] "` if set, else empty; **leads every default title/headline/subject** so multiple projects on one channel stay distinct | all |
| `timestamp` | Timestamp (formatted in `{timezone}`) | all |
| `timezone` | Timezone display name | all |
| `value` | Current metric value (numeric, or string `"no data"` for no-data) | all |
| `value_display` | NaN-safe string version — always renders, falls back to `"no data"` | all |
| `confidence_lower` / `confidence_upper` | Bounds of confidence interval | anomaly, recovery |
| `confidence_interval` | Formatted as `[lower, upper]` or `"N/A"` | all |
| `expected_range` | One-sided aware expected band: `>= lo`, `<= hi`, `[lo, hi]`, or `"N/A"`. Renders one-sided detector bounds cleanly instead of `[7.00, nan]` | all |
| `detector_name` | Detector that triggered (e.g., `"MADDetector:threshold=3.0"`); `"N detectors"` when several detectors formed the quorum | anomaly, recovery |
| `detector_params` | Detector parameters as a JSON string (empty for no-data/error) | anomaly, recovery |
| `detector_count` | Observed number of detectors that agreed (the quorum size that fired) | anomaly |
| `min_detectors` | Configured quorum threshold the alert fired on (the rule) | anomaly, recovery |
| `severity` | Severity score; max across the quorum for multi-detector alerts | anomaly |
| `direction` | Observed/locked anomaly direction: `"up"` or `"down"`; also `"mixed"` for an `any`-policy quorum spanning both up and down, and `"none"` for no-data/recovery | all |
| `direction_policy` | Configured direction rule: `"same"`, `"any"`, `"up"`, `"down"` | anomaly, recovery |
| `consecutive_count` | **True** consecutive streak length — resolved at fire time by looking back over the detection history, not capped at the rule threshold (recovery: the just-ended incident length) | anomaly, recovery |
| `consecutive_required` | Configured consecutive threshold the alert fired on (the rule) | anomaly, recovery |
| `rule_display` | The full alert-rule chip — the legacy `min_detectors=… · direction=… · consecutive=…` unless the metric also configures the [fraction-based alert window](alerting.md#fraction-based-alert-window-optional), in which case it also names `anomaly_window` / `min_anomaly_share`, leading with whichever rule fired | anomaly, recovery (a share-configured metric's recovery echoes the same combined chip, so fire and recovery name one rule) |
| `window_points` / `window_matched` | Fraction-rule window size (in points) and the matched-quorum-point count within it; both empty unless the alert is share-configured (`window_points`) / share-fired (`window_matched`) | anomaly, recovery (`window_points` only) |
| `interval_display` | Metric interval as a string (e.g. `"10min"`) | all |
| `duration_display` | How long the streak/incident has run (e.g. `"2h 30m"`; `"over …"` when older than the lookback window) | anomaly, recovery |
| `onset_display` / `started_display` | First **anomalous** timestamp of the run — the onset, **not** the alert-fire time (formatted in `{timezone}`); `started_display` adds `"or earlier"` when the run is capped | anomaly, recovery |
| `fired_display` | On-grid moment the alert first fired — `onset + (consecutive_required − 1) × interval` (formatted in `{timezone}`); empty when the run is capped or no interval is wired in | recovery |
| `anomaly_lead` / `recovery_lead` | Ready-made plain-language lead — `"Anomalous for …"` / `"… Incident lasted …"` (falls back to `"Latest X/Y consecutive points met the quorum."` when no interval is wired in) | anomaly, recovery |
| `window_line` | `"Anomaly began: … \| Latest reading: …\n"` (anomaly) / `"Anomaly began: … \| Alert fired: … \| Recovered: …\n"` (recovery), or a single `"Detected at: …"` line when the onset is unknown | all |
| `status` | `"ANOMALY"`, `"RECOVERED"`, `"NO_DATA"`, or `"ERROR"` | all |
| `error_type` / `error_message` | Exception details | error only |
| `description` / `description_line` | Metric description | all |
| `synonyms` / `synonyms_line` | Metric's alternative names from `ai_context.synonyms` — `"total revenue, gross sales"` / `"Also known as: …\n"` (empty when unset). **Opt-in**: not in the default templates, so add `{synonyms_line}` to a custom `template` to surface an "Also known as: …" line | all |
| `mentions` / `mentions_line` | Formatted mentions | all |
| `dashboard_url` | Raw `alerting.dashboard_url` (empty string when unset); also surfaced natively as a clickable title on Slack/Mattermost, an inline link on Telegram, and an "Open dashboard" button in email | all |
| `dashboard_line` | `"Dashboard: <url>\n"` when set, else empty; appended to the default plain-text templates | all |
| `help_url` | Raw "How to read this alert" URL (empty when hidden via `alert_help_url: false`); also surfaced natively as a clickable label in the webhook `Links` line, a links-line entry on Telegram, and a footer link in email | all |
| `help_line` | `"How to read this alert: <url>\n"` when set, else empty; appended to the default plain-text templates | all |

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
🔴 [my_monitoring] Alert: api_response_time
Anomalous for 30m — 3 consecutive 10min intervals.
Rule: min_detectors=1 · direction=same · consecutive=3

Value: 0.8532 | Expected: [0.45, 0.62]
Quorum: 1/1 · up
Severity: 4.52
Anomaly began: 2026-06-12 14:10:00 (UTC) | Latest reading: 2026-06-12 14:30:00 (UTC)
Detectors: MADDetector:threshold=3.0
Parameters: {"threshold": 3.0, "window_size": 8640}
```

**Use cases**:
- Verify webhook URLs work
- Check alert formatting
- Test custom templates
- Validate channel permissions
