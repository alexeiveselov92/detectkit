# detectkit — Project & Profiles config

Two project-level files: `detectkit_project.yml` (project settings) and
`profiles.yml` (database connections + alert channels). Both support
environment-variable interpolation — `{{ env_var('VAR') }}` and `${VAR}` — so
secrets stay out of YAML. Unresolved placeholders are left as-is and surface as
errors (not empty strings).

## `detectkit_project.yml`

```yaml
name: my_monitoring            # project identifier (shown in logs, error-alert titles)
default_profile: prod          # profile name from profiles.yml

paths:
  metrics_dir: metrics         # where metric YAMLs live (default: metrics)
  sql_dir: sql                 # where query_file: SQL lives (default: sql)
  templates_dir: templates     # custom alert templates (default: templates)

default_tables:                # internal table names (overridable per metric)
  datapoints: _dtk_datapoints
  detections: _dtk_detections
  tasks: _dtk_tasks

timeouts:
  query_timeout: 300           # SQL execution timeout (s)
  lock_timeout: 3600           # how long a task lock is held before expiring (s)

error_alerting:                # optional, see below
  enabled: false
```

### `error_alerting` — project-scoped failure alerts

Catches any exception from a metric's pipeline (DB down, query timeout, lock
failure, channel HTTP error) and sends **one** alert, then aborts the rest of
the `dtk run` (no point loading 30 more metrics if the DB is down).

```yaml
error_alerting:
  enabled: true
  channels: [mattermost_oncall, email_oncall]   # names from profiles.yml
  mentions: [oncall_engineer, here]             # optional
  timezone: "Europe/Moscow"                     # optional, for {timestamp}
  template: |                                   # optional
    {project_name_prefix}🔥 pipeline crashed
    Metric: {metric_name}
    {error_type}: {error_message}
    Time: {timestamp} ({timezone})
    {mentions}
```

- One alert per `dtk run`; subsequent failures in the same invocation are
  suppressed and the run aborts. No persistent cross-run cooldown (space repeats
  via cron cadence). Channel send failures are swallowed so a flaky webhook
  can't crash the run.
- Extra template variables: `{error_type}`, `{error_message}`, `{status}`
  (always `"ERROR"`), `{project_name}`, `{project_name_prefix}` (=
  `"[<name>] "` when `name` set — keeps multi-project channels distinguishable).

## `profiles.yml`

```yaml
default_profile: prod

profiles:
  prod:
    type: clickhouse
    # ... connection fields (per type, below)

alert_channels:
  mattermost_ops:
    type: mattermost
    # ... channel fields (per type, below)
```

### Database profiles

**ClickHouse** (priority backend):
```yaml
profiles:
  prod:
    type: clickhouse
    host: clickhouse.example.com
    port: 9000                 # native protocol
    user: default              # optional (default: "default")
    password: ""               # optional
    internal_database: analytics   # required — where _dtk_* tables live
    data_database: default         # required — where your queries read from
    settings:                  # optional ClickHouse settings
      max_execution_time: 600
      max_memory_usage: 10000000000
```

**PostgreSQL**:
```yaml
profiles:
  prod:
    type: postgres
    host: localhost
    port: 5432
    database: analytics            # required
    user: postgres
    password: "..."
    internal_schema: detectkit     # required — _dtk_* tables
    data_schema: public            # required — data queries
    pool_size: 5                   # optional
    max_overflow: 10               # optional
```

**MySQL**:
```yaml
profiles:
  prod:
    type: mysql
    host: localhost
    port: 3306
    database: analytics            # required
    user: root
    password: "..."
    internal_database: detectkit   # required
    data_database: analytics       # required
    charset: utf8mb4               # optional
    autocommit: true               # optional
```

### Alert channels

Defined once in `profiles.yml`, referenced by name in each metric's
`alerting.channels` (and in `error_alerting.channels`).

**Mattermost** / **Slack** (Slack-compatible webhook API, same fields):
```yaml
alert_channels:
  mattermost_ops:
    type: mattermost            # or: slack
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"   # required
    username: "detectkit"       # optional (default: "detectkit")
    icon_emoji: ":warning:"     # optional
    channel: "alerts"           # optional — override webhook default ("#alerts" for Slack)
    timeout: 10                 # optional HTTP timeout (s)
```
> Slack note: `@username` in a Slack webhook is **display-only** (no real ping).
> Use Slack user IDs (`U…`) for real pings.

**Telegram**:
```yaml
alert_channels:
  telegram_alerts:
    type: telegram
    bot_token: "{{ env_var('TG_BOT_TOKEN') }}"   # required
    chat_id: "-1001234567890"                    # required
```

**Email** (SMTP):
```yaml
alert_channels:
  email_ops:
    type: email
    smtp_host: "smtp.gmail.com"   # required
    smtp_port: 587                # required (587 TLS, 465 SSL)
    from_email: "alerts@example.com"   # required
    to_emails: ["ops@example.com"]     # required (list)
    smtp_user: "..."              # optional
    smtp_password: "..."          # optional (use env_var)
    use_tls: true                 # optional (default: true)
```

**Webhook** (generic):
```yaml
alert_channels:
  webhook_alerts:
    type: webhook
    url: "{{ env_var('WEBHOOK_URL') }}"
    method: POST
    headers:
      Authorization: "Bearer {{ env_var('WEBHOOK_TOKEN') }}"
```

## Notes

- `internal_database`/`internal_schema` should be separate from your data
  location so the `_dtk_*` tables don't clutter analytics schemas.
- Profiles can be overridden per run (`dtk run --profile staging`) and per
  metric (`profile:` field in the metric YAML).
- Channel formatting (color, mentions syntax) is handled per channel type — you
  write plain usernames and one template; each channel renders natively. See
  `alerting.md`.
