# No-data & error alerts

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
    {metric_name} stopped reporting
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
| `{project_name}` | `detectkit_project.yml` `name`, or empty string. Since v0.15.0 populated for every alert kind, not just errors |
| `{project_name_prefix}` | `"[<project_name>] "` when set, empty string otherwise. Leads the default no-data title |
| `{timestamp}` | Timestamp of the missing interval (formatted, in `{timezone}`) |
| `{timezone}` | Configured timezone |
| `{description}` | Metric `description`, empty string if none |
| `{description_line}` | Same with trailing newline, empty if none |
| `{status}` | Always `"NO_DATA"` |
| `{mentions}` / `{mentions_line}` | Formatted mentions |
| `{help_url}` / `{help_line}` | "How to read this alert" link URL / line (since v0.16.0); empty when hidden project-wide via `alert_help_url: false` |
| `{value_display}` | Always the literal string `"no data"` |

If a template uses `{value:.2f}` or another numeric format spec on a
no-data alert, detectkit falls back to the default no-data template
rather than crashing — but write the template with no-data in mind.

### Visual Distinction

Every no-data title leads with the **🟡 status circle** so the kind reads
from color alone (🔴 anomaly / 🟢 recovery / 🟡 no-data / 🔵 pipeline
error). On webhook channels (Slack/Mattermost) the attachment accent bar
is also the amber `#F0AD4E`, distinguishing it from anomalies (red) and
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
    Pipeline failure
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
🔵 {project_name_prefix}Pipeline failed for metric: {metric_name}
{description_line}Time: {timestamp}
Error: {error_type}: {error_message}
{mentions_line}
```

Title (webhook channels): `🔵 [{project_name}] Pipeline error: {metric_name}`
when `project_name` is set in `detectkit_project.yml`, otherwise just
`🔵 Pipeline error: {metric_name}` (backwards-compat). Since v0.15.0 the
`{project_name_prefix}` lead is not error-specific — **every** default alert
title/headline/subject carries it (see the
[Channels guide](alerting-channels.md)). The bracketed prefix makes it obvious
which project crashed when multiple detectkit instances share an alert channel.

### Template Variables

| Variable | Description |
|---|---|
| `{metric_name}` | Name of the metric whose pipeline failed (or `<startup>` for early failures) |
| `{project_name}` | `detectkit_project.yml` `name` field, or empty string. Since v0.15.0 populated for every alert, not just errors |
| `{project_name_prefix}` | `"[<project_name>] "` when set, empty string otherwise. Since v0.15.0 leads every default title/headline/subject |
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
    {project_name_prefix}pipeline crashed
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

