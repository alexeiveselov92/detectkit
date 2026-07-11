# detectkit — Project & Profiles config

Two project-level files: `detectkit_project.yml` (project settings) and
`profiles.yml` (database connections + alert channels). Both support
environment-variable interpolation — `{{ env_var('VAR') }}` and `${VAR}` — so
secrets stay out of YAML. Unresolved placeholders are left as-is and surface as
errors (not empty strings).

## `detectkit_project.yml`

```yaml
name: my_monitoring            # required — project identifier; also labels every
                               # alert ("[my_monitoring] Alert: …") so multiple
                               # projects on one channel stay distinct (alerting.md)
version: "1.0"                 # optional (default "1.0")
default_profile: prod          # profile name from profiles.yml

paths:                         # optional — directory names
  metrics: metrics             # where metric YAMLs live (default: metrics)
  sql: sql                     # where query_file: SQL lives (default: sql)
  templates: templates         # custom alert templates (default: templates)

tables:                        # internal table names (overridable per metric)
  datapoints: _dtk_datapoints
  detections: _dtk_detections
  tasks: _dtk_tasks

timeouts:                      # per-step, seconds
  load: 3600                   # load step (default 3600)
  detect: 7200                 # detect step (default 7200)
  alert: 300                   # alert step (default 300)

alert_help_url: null           # optional, see below — "How to read this alert" link
false_alert_budget: null       # optional — `dtk tune` target FDR (0,1]; per-metric override wins
loading_delay: null            # optional — default data-maturity delay; per-metric override wins

error_alerting:                # optional, see below
  enabled: false
```

`false_alert_budget` is a project-wide **target false-alert rate** (a fraction in
`(0, 1]`, e.g. `0.3` = 30%) for manual tuning: the `dtk tune` cockpit gently flags a
metric when its false-alert rate exceeds it. A per-metric `false_alert_budget`
overrides it; unset → a built-in `0.5`. Tuning-only — it never touches the pipeline.

`loading_delay` is a project-wide default **data-maturity delay** (duration string
or seconds), useful when every metric reads from one upstream pipeline that
finishes a few minutes after each interval closes. A per-metric `loading_delay`
overrides it (`0` opts that metric out); see `metrics.md` for the full
load/no-data behavior and the detection-latency trade-off. Only set this
project-wide when your metrics genuinely share the same upstream schedule.

### `alert_help_url` — "How to read this alert" link

Every default-rendered alert on every channel carries a `How to read this alert`
link for non-operator stakeholders. Tri-state:

- **unset / null** (default) → the official detectkit guide
  (`https://dtk.pipelab.dev/guides/reading-alerts/`).
- **a URL string** → your own runbook/wiki page instead.
- **`false`** → hide the link entirely.

```yaml
alert_help_url: https://wiki.ops/how-to-read-alerts   # custom page
# alert_help_url: false                               # hide the link
```

Per-channel rendering and the `{help_url}` / `{help_line}` template variables are
covered in `alerting.md` → "How to read this alert" link.

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
    {project_name_prefix}pipeline crashed
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
  (always `"ERROR"`). `{project_name}` / `{project_name_prefix}` (=
  `"[<name>] "` when `name` set) are available here **and in every other alert
  template** — and by default lead the title/headline on all channels, keeping
  multi-project channels distinguishable (see `alerting.md` → Project label).

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

> ClickHouse, PostgreSQL, MySQL and MariaDB are all fully supported.
> ClickHouse/MySQL/MariaDB use two *databases*; PostgreSQL connects to one
> `database` and uses two *schemas*.
> `dtk init --db-type {clickhouse,postgres,mysql,mariadb}` scaffolds the right shape.

**ClickHouse**:
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

**PostgreSQL** (connect to `database`, tables in schemas):
```yaml
profiles:
  prod:
    type: postgres
    host: localhost
    port: 5432
    database: detectkit            # required — must already exist
    user: postgres
    password: "..."
    internal_schema: detectkit     # required — _dtk_* tables (auto-created)
    data_schema: public            # required — data queries
    settings: {}                   # optional — extra psycopg2.connect kwargs
```

**MySQL** (8.0+; two databases):
```yaml
profiles:
  prod:
    type: mysql
    host: localhost
    port: 3306
    user: root
    password: "..."
    internal_database: detectkit   # required — _dtk_* tables (auto-created)
    data_database: analytics       # required
    database: analytics            # optional — default db for the connection
    settings: {}                   # optional — extra pymysql.connect kwargs
```

**MariaDB**: identical fields to the MySQL block above — just spell `type:
mariadb` instead of `type: mysql`. The vendor (MySQL vs MariaDB) is
auto-detected at connect (`SELECT VERSION()`), so MariaDB gets its own
`VALUES()`-form upsert instead of MySQL 8.0.19's row-alias form.
`pip install 'detectkit[mariadb]'`.

### Alert channels

Defined once in `profiles.yml`, referenced by name in each metric's
`alerting.channels` (and in `error_alerting.channels`).

The bot defaults to the **detectkit brand** name + avatar on every channel.
Override per channel; Telegram and email brand differently (see their notes).

**Mattermost** / **Slack** (Slack-compatible webhook API, same fields):
```yaml
alert_channels:
  mattermost_ops:
    type: mattermost            # or: slack
    webhook_url: "{{ env_var('MATTERMOST_WEBHOOK_URL') }}"   # required
    channel: "alerts"           # optional — override webhook default ("#alerts" for Slack)
    timeout: 10                 # optional HTTP timeout (s)
    # Bot identity defaults to the detectkit brand; override any of:
    # username: "detectkit"            # display name
    # icon_url: "https://.../bot.png"  # avatar image (default: brand avatar)
    # icon_emoji: ":warning:"          # emoji instead of an avatar image
```
> Icon precedence: `icon_url` (default: brand avatar) wins over `icon_emoji`;
> set either to opt out of the brand avatar.
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
> Telegram shows the bot account's own avatar (set in @BotFather, not
> per-message), so detectkit can't override it. Brand it via `/setuserpic` —
> the detectkit avatar is at `https://dtk.pipelab.dev/bot-icon.png`.

**Email** (SMTP):
```yaml
alert_channels:
  email_ops:
    type: email
    smtp_host: "smtp.gmail.com"   # required
    smtp_port: 587                # required (587 TLS, 465 SSL)
    from_email: "alerts@example.com"   # required
    to_emails: ["ops@example.com"]     # required (list)
    from_name: "detectkit"        # optional — From display name (default: "detectkit")
    smtp_username: "..."          # optional
    smtp_password: "..."          # optional (use env_var)
    use_tls: true                 # optional (default: true)
```
> Sends as `detectkit <from_email>` with the brand logo in an HTML body (plain
> text stays the fallback). The avatar mail clients show is set by the sending
> domain (BIMI), not the message — brand it via `from_name` + your domain.

**Webhook** (generic):
```yaml
alert_channels:
  webhook_alerts:
    type: webhook
    webhook_url: "{{ env_var('WEBHOOK_URL') }}"   # required
    format: attachments                           # optional: attachments (default) | json | alertmanager
    secret: "{{ env_var('WEBHOOK_SECRET') }}"      # optional — HMAC-SHA256-signs the request body
    extra_headers:                                # optional
      Authorization: "Bearer {{ env_var('WEBHOOK_TOKEN') }}"
```
> `format` — `attachments` (default) renders the same platform-style card as
> Mattermost/Slack; `json` sends a versioned structured event
> (`schema_version: 1`; fields like `kind`/`status`/`project`/`metric`/
> `timestamp`/`value`/`expected`/`severity`/`direction`/`detector`/`rule`/
> `quorum`/`incident`/`links`/`display`); `alertmanager` sends a Prometheus
> Alertmanager webhook-receiver payload (v4) — a trigger/resolve pair sharing
> identical labels/fingerprint, `severity: critical` for anomaly/error and
> `warning` for no-data (no-data never auto-resolves). `json`/`alertmanager`
> ignore a custom `template` and add an `X-Detectkit-Event` header.
> `secret` — signs the raw request body as HMAC-SHA256 into
> `X-Detectkit-Signature-256: sha256=<hex>`, for any `format`.

## Notes

- **First-run setup:** the `profiles.yml` that `dtk init` writes is a
  placeholder scaffolded for `--db-type` (default ClickHouse) — its `dev`
  profile points the location fields at example values on `localhost`. Edit the
  host, credentials and location names to match your environment before running
  (the **`dtk-setup-project`** skill walks this). ClickHouse/MySQL use
  `internal_database` / `data_database` (no `database:` field on ClickHouse);
  PostgreSQL connects to a `database` and uses `internal_schema` / `data_schema`.
- `dtk run` (without `--profile`) uses the `default_profile` declared in
  **`profiles.yml`**; the `default_profile` in `detectkit_project.yml` is not
  read at runtime — keep them in sync to avoid confusion.
- `internal_database`/`internal_schema` should be separate from your data
  location so the `_dtk_*` tables don't clutter analytics schemas.
- Profiles can be overridden per run (`dtk run --profile staging`) and per
  metric (`profile:` field in the metric YAML).
- Channel formatting (color, mentions syntax) is handled per channel type — you
  write plain usernames and one template; each channel renders natively. See
  `alerting.md`.
