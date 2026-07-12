# Profiles Configuration

File: `profiles.yml`

### Basic Structure

```yaml
# Default profile to use
default_profile: prod

# Database profiles
profiles:
  prod:
    type: clickhouse
    host: localhost
    port: 9000
    # ... database-specific settings

# Alert channels
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    # ... channel-specific settings
```

A metric or project can also reference a *second* profile by name via
`source_profile` to read metric SQL from one database while `_dtk_*` state
stays in another — see the [Hybrid Mode guide](hybrid-mode.md).

### Database Profiles

ClickHouse, PostgreSQL, MySQL, MariaDB, and DuckDB are all fully supported as
**state** backends (they hold `_dtk_*` state and can also run metric SQL). The
connection fields differ per backend (ClickHouse/MySQL/MariaDB use
**databases**; PostgreSQL and DuckDB use **schemas** — PostgreSQL connects to
a `database`, DuckDB opens a file at `path`). See the per-backend [Databases
guide](databases.md) for a focused walkthrough of each. MariaDB uses the
MySQL backend — set `type: mariadb` (an alias with identical fields) or keep
`type: mysql` against a MariaDB server; either way the vendor is
auto-detected at connect. See the [MySQL guide](databases-mysql.md#mariadb)
for the MariaDB-specific notes, and the [DuckDB
guide](databases-duckdb.md#single-writer-one-process-at-a-time) for its
single-writer caveat.

**Snowflake** (`type: snowflake`) is a **source-only** backend: it can only be
referenced as a hybrid-mode [`source_profile`](hybrid-mode.md), never as the
state profile — see the [Snowflake profile](#snowflake-profile-source-only)
below and the [Snowflake guide](databases-snowflake.md).

**BigQuery** (`type: bigquery`) is likewise a **source-only** backend: it can
only be referenced as a hybrid-mode [`source_profile`](hybrid-mode.md), never as
the state profile — see the [BigQuery profile](#bigquery-profile-source-only)
below and the [BigQuery guide](databases-bigquery.md).

#### ClickHouse Profile

```yaml
profiles:
  prod:
    type: clickhouse
    host: clickhouse.example.com
    port: 9000
    user: default
    password: "your_password"

    # Internal tables location (for _dtk_* tables)
    internal_database: analytics

    # Data tables location (for your metrics)
    data_database: default

    # ClickHouse-specific settings
    settings:
      max_execution_time: 600
      max_memory_usage: 10000000000
```

**Required fields**:
- `type`: Must be `"clickhouse"`
- `host`: ClickHouse server hostname
- `port`: ClickHouse native protocol port (default: 9000)
- `internal_database`: Database for _dtk_* tables
- `data_database`: Database for data queries

**Optional fields**:
- `user`: Username (default: `"default"`)
- `password`: Password (default: empty string)
- `settings`: Dict of ClickHouse settings to apply

#### PostgreSQL Profile

PostgreSQL connects to a `database` and stores tables in **schemas** inside it.
The `database` must already exist; detectkit creates the schemas.

```yaml
profiles:
  prod:
    type: postgres
    host: localhost
    port: 5432
    user: postgres
    password: "your_password"

    database: detectkit         # database to connect to (must already exist)
    internal_schema: detectkit  # schema for _dtk_* tables (auto-created)
    data_schema: public         # schema for your data queries
```

**Required fields**:
- `type`: Must be `"postgres"`
- `host`: PostgreSQL server hostname
- `port`: PostgreSQL port (default: 5432)
- `database`: Database to connect to (must already exist)
- `internal_schema`: Schema for _dtk_* tables (detectkit creates it)
- `data_schema`: Schema for data queries

**Optional fields**:
- `user`: Username (default: `"default"`)
- `password`: Password (default: empty string)
- `settings`: Extra `psycopg2.connect` keyword arguments

#### MySQL Profile

MySQL (8.0+) uses **databases** (no separate schema concept). MariaDB is
fully supported through this same backend — `type: mariadb` is an identical
alias, and `type: mysql` against a MariaDB server also works (the driver
detects the actual vendor at connect time, not from `type`). See the [MySQL
guide → MariaDB](databases-mysql.md#mariadb) for version support and the
`detectkit[mariadb]` install extra.

```yaml
profiles:
  prod:
    type: mysql
    host: localhost
    port: 3306
    user: root
    password: "your_password"

    # Database locations (auto-created)
    internal_database: detectkit
    data_database: analytics
```

**Required fields**:
- `type`: Must be `"mysql"`
- `host`: MySQL server hostname
- `port`: MySQL port (default: 3306)
- `internal_database`: Database for _dtk_* tables (detectkit creates it)
- `data_database`: Database for data queries

**Optional fields**:
- `user`: Username (default: `"default"`)
- `password`: Password (default: empty string)
- `database`: Optional default database for the connection
- `settings`: Extra `pymysql.connect` keyword arguments

#### DuckDB Profile

DuckDB is an **in-process, single-file** database — there's no host, port,
user or password, just a file `path` (or `:memory:`). Internal/data tables
live in **schemas** inside that one file, same location model as PostgreSQL.
See the [DuckDB guide](databases-duckdb.md) for the full walkthrough,
including the **single read-write connection at a time** caveat before
pointing a scheduled `dtk run` and a long-lived `dtk ui` at the same file.

```yaml
profiles:
  dev:
    type: duckdb
    path: "./detectkit.duckdb"     # file path (created if it doesn't exist), or ":memory:"

    internal_schema: detectkit     # schema for _dtk_* tables (auto-created)
    data_schema: main              # schema for your data queries (DuckDB's default schema)
```

**Required fields**:
- `type`: Must be `"duckdb"`
- `path`: Database file path (created if it doesn't exist), or the literal
  `":memory:"` (transient — tests/preview only, state is lost on exit)

**Optional fields**:
- `internal_schema` (default: `"detectkit"`) - Schema for `_dtk_*` tables (detectkit creates it)
- `data_schema` (default: `"main"`) - Schema for data queries
- `read_only` (default: `false`) - Open the file read-only; required when
  another process already holds it read-write
- `settings`: Extra `duckdb.connect(..., config=...)` options (e.g. `memory_limit`)

#### Snowflake Profile (source-only)

Snowflake is a **source-only** backend — a `type: snowflake` profile is valid
**only** as a hybrid-mode [`source_profile`](hybrid-mode.md); detectkit refuses
to store `_dtk_*` state in it. See the [Snowflake
guide](databases-snowflake.md) for the full walkthrough, including key-pair
setup and the UTC/column-folding notes.

```yaml
profiles:
  snowflake_wh:
    type: snowflake
    account: "ab12345.eu-central-1"      # Snowflake account identifier
    user: DETECTKIT_SVC
    private_key_path: "./keys/detectkit_rsa_key.p8"   # key-pair auth (recommended)
    private_key_passphrase: "{{ env_var('SNOWFLAKE_KEY_PASSPHRASE') }}"
    warehouse: MONITORING_WH             # optional
    database: ANALYTICS                  # optional
    schema: PUBLIC                       # optional (session schema)
    role: DETECTKIT_ROLE                 # optional
```

**Required fields**:
- `type`: Must be `"snowflake"`
- `account`: Snowflake account identifier (e.g. `ab12345.eu-central-1`)
- `user`: Login name (must be set explicitly)
- `private_key_path` **or** `password`: key-pair auth (recommended) or password

**Optional fields**:
- `private_key_passphrase`: Passphrase for the PEM key (env-interpolatable)
- `warehouse`: Virtual warehouse to run queries on
- `database`: Default database for the session
- `schema`: Default schema for the session (the YAML key `schema` maps to the
  session schema)
- `role`: Role to assume for the session
- `settings`: Extra Snowflake session parameters (merged over detectkit's — e.g.
  `{TIMEZONE: "..."}` to override the UTC session pin)

There is **no `host` / `port`** — Snowflake connects through its account-based
endpoint.

#### BigQuery Profile (source-only)

BigQuery is a **source-only** backend — a `type: bigquery` profile is valid
**only** as a hybrid-mode [`source_profile`](hybrid-mode.md); detectkit refuses
to store `_dtk_*` state in it. See the [BigQuery
guide](databases-bigquery.md) for the full walkthrough, including credential
setup and the `TIMESTAMP` / cost-guardrail notes.

```yaml
profiles:
  bigquery_wh:
    type: bigquery
    project: my-analytics-project                        # GCP project billed for queries
    credentials_json_path: "/etc/detectkit/bq-sa.json"   # service-account key (optional)
    location: EU                                         # optional job location
    dataset: analytics                                   # optional default dataset
    settings:
      maximum_bytes_billed: 1000000000                   # optional cost guardrail
```

**Required fields**:
- `type`: Must be `"bigquery"`
- `project`: GCP project id billed for the queries (e.g. `my-analytics-project`)

**Optional fields**:
- `credentials_json_path`: Path to a service-account JSON key file. Unset →
  **Application Default Credentials** (gcloud ADC, an attached service account,
  or Workload Identity)
- `location`: Job location (e.g. `EU`); unset → BigQuery infers it from the
  referenced datasets
- `dataset`: Default dataset so unqualified table names in the query resolve
- `api_endpoint`: API endpoint override — for the BigQuery emulator (e.g.
  `http://localhost:9050`) or a private/regional endpoint; a plain-`http://`
  endpoint without a key file switches auth to anonymous credentials (the
  emulator path), while `https://` endpoints authenticate normally via key
  file or ADC
- `settings`: Extra `QueryJobConfig` attributes applied to every query (e.g.
  `maximum_bytes_billed`, `labels`); unknown attribute names are rejected at
  connect

There is **no `host` / `port` / `user` / `password`** — BigQuery connects
through the Google client with the `project` and credentials above.

### Alert Channels

#### Mattermost Channel

```yaml
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    channel: "alerts"          # Explicit channel name
    timeout: 10                 # Request timeout (seconds)
    # Bot name + avatar default to the detectkit brand (override below).
    # username: "detectkit"
    # icon_url: "https://.../bot.png"   # or icon_emoji: ":warning:"
```

**Required fields**:
- `type`: Must be `"mattermost"`
- `webhook_url`: Mattermost incoming webhook URL

**Optional fields**:
- `username` (default: `"detectkit"`) - Bot display name
- `icon_url` (default: detectkit brand avatar) - Bot avatar image URL
- `icon_emoji` (optional) - Emoji icon, used instead of an avatar image
- `channel` - Override webhook's default channel
- `timeout` (default: `10`) - HTTP request timeout

#### Slack Channel

```yaml
alert_channels:
  slack_ops:
    type: slack
    webhook_url: "https://hooks.slack.com/services/xxx"
    channel: "#alerts"          # Explicit channel
    # Bot name + avatar default to the detectkit brand; override with
    # username / icon_url / icon_emoji.
```

Same fields as Mattermost (Slack-compatible webhook API).

#### Telegram Channel

```yaml
alert_channels:
  telegram_alerts:
    type: telegram
    bot_token: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    chat_id: "-1001234567890"
    parse_mode: "HTML"          # "Markdown", "HTML", or null (default: "HTML")
    disable_notification: false # Send silently without notification (default: false)
```

**Required fields**:
- `type`: Must be `"telegram"`
- `bot_token`: Telegram bot API token
- `chat_id`: Target chat/channel ID

**Optional fields**:
- `parse_mode` (default: `"HTML"`) - Message formatting: `"Markdown"`, `"HTML"`, or `null`
- `disable_notification` (default: `false`) - Send the message silently, without a notification sound

> The default `parse_mode` is now `HTML` (was `Markdown`). The built-in message
> is HTML-escaped, which fixes a "can't parse entities" error the old Markdown
> default raised on params JSON containing underscores (e.g. `window_size`).
> Custom templates are sent verbatim under the parse mode, so keep them
> HTML-safe — or set `parse_mode: Markdown` to restore the previous behavior.

#### Email Channel

```yaml
alert_channels:
  email_ops:
    type: email
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    smtp_username: "your_email@gmail.com"
    smtp_password: "your_app_password"
    from_email: "alerts@example.com"
    to_emails:
      - "ops@example.com"
      - "devops@example.com"
    use_tls: true
```

**Required fields**:
- `type`: Must be `"email"`
- `smtp_host`: SMTP server hostname
- `smtp_port`: SMTP server port
- `from_email`: Sender email address
- `to_emails`: List of recipient email addresses

**Optional fields**:
- `from_name` (default: `"detectkit"`) - Sender display name in the `From`
  header (the brand logo is also rendered in the HTML body)
- `smtp_username`: SMTP authentication username (the channel only logs in when both `smtp_username` and `smtp_password` are set)
- `smtp_password`: SMTP authentication password
- `use_tls` (default: `true`) - Use TLS encryption
- `subject_template` (default: `"🔴 Alert: {metric_name}"`) - Email subject, supports `{metric_name}`
- `template`: Custom message body template (falls back to the built-in default)

#### Discord Channel

```yaml
alert_channels:
  discord_ops:
    type: discord
    webhook_url: "${DISCORD_WEBHOOK}"
    # Bot identity is optional — defaults to the detectkit brand name + avatar.
    # username: "detectkit"
    # avatar_url: "https://.../bot.png"
```

**Required fields**:
- `type`: Must be `"discord"`
- `webhook_url`: Discord incoming-webhook URL
  (`https://discord.com/api/webhooks/<id>/<token>`)

**Optional fields**:
- `username` (default: `"detectkit"`) - Bot display name
- `avatar_url` (default: detectkit brand avatar) - Bot avatar image URL
- `timeout` (default: `10`) - HTTP request timeout

> A bare `@name` in `mentions:` doesn't ping on Discord — use the literal
> `<@user_id>` / `<@&role_id>` form for a real ping. See the [Channels
> guide → Discord](alerting-channels.md#discord) for the full rendering and
> mention notes.

#### Microsoft Teams Channel

```yaml
alert_channels:
  teams_ops:
    type: teams
    webhook_url: "${TEAMS_WEBHOOK_URL}"
```

**Required fields**:
- `type`: Must be `"teams"`
- `webhook_url`: the **Workflows** app's webhook-trigger URL (not the retired
  Office 365 connector)

**Optional fields**:
- `timeout` (default: `10`) - HTTP request timeout

> The message posts under the Workflow's own identity — there is no
> `username`/avatar override, and `@mentions` render as plain text without
> actually pinging. See the [Channels guide →
> Teams](alerting-channels.md#microsoft-teams) for the full caveats.

#### Google Chat Channel

```yaml
alert_channels:
  googlechat_ops:
    type: googlechat
    webhook_url: "${GOOGLE_CHAT_WEBHOOK_URL}"
    # icon_url: "https://.../bot.png"   # optional — defaults to the detectkit brand avatar
```

**Required fields**:
- `type`: Must be `"googlechat"`
- `webhook_url`: the space's full incoming-webhook URL

**Optional fields**:
- `icon_url` (default: detectkit brand avatar) - header avatar image URL
- `timeout` (default: `10`) - HTTP request timeout

> Only the space-wide `<users/all>` token actually pings; anything else in
> `mentions:` renders as a plain, non-pinging `@name`. See the [Channels
> guide → Google Chat](alerting-channels.md#google-chat).

#### ntfy Channel

```yaml
alert_channels:
  ntfy_ops:
    type: ntfy
    topic: "my-alerts"
    # server: "https://ntfy.sh"     # default; self-hosted servers work the same way
    # token: "${NTFY_TOKEN}"        # access token -> Authorization: Bearer
    # priority: 5                   # overrides the anomaly/error priority only
```

**Required fields**:
- `type`: Must be `"ntfy"`
- `topic`: ntfy topic to publish to

**Optional fields**:
- `server` (default: `"https://ntfy.sh"`) - ntfy server base URL
- `token` (optional) - ntfy access token (`Authorization: Bearer <token>`);
  wins over `user`/`password`
- `user` / `password` (optional) - HTTP basic auth, used only when `token` is unset
- `priority` (optional, `1`-`5`) - overrides the anomaly/error notification
  priority only; recovery/no-data always stay calm at `3`
- `timeout` (default: `10`) - HTTP request timeout

> ntfy has no bot avatar/color-bar concept — see the [Channels guide →
> ntfy](alerting-channels.md#ntfy) for the tag-emoji title, priority mapping
> and message-size cap.

#### Generic Webhook Channel

Sends alerts to any endpoint that accepts a JSON payload (Mattermost/Slack
attachments format). Use this for custom webhook receivers or when you need
extra HTTP headers (e.g., bearer auth).

```yaml
alert_channels:
  custom_hook:
    type: webhook
    webhook_url: "https://custom.example.com/webhook"
    format: attachments            # attachments (default) | json | alertmanager
    secret: "{{ env_var('WEBHOOK_SECRET') }}"  # optional HMAC signing secret
    channel: "#alerts"            # Target channel (optional, Slack/Mattermost)
    timeout: 10                    # Request timeout in seconds (default: 10)
    extra_headers:                 # Additional HTTP headers (optional)
      Authorization: "Bearer token"
    # Bot name + avatar default to the detectkit brand; override with
    # username / icon_url / icon_emoji.
```

**Required fields**:
- `type`: Must be `"webhook"`
- `webhook_url`: Endpoint URL to POST the JSON payload to

**Optional fields**:
- `format` (default: `"attachments"`) - Payload shape: `attachments` (today's
  Mattermost/Slack-compatible payload), `json` (a flat, stable machine-readable
  payload), or `alertmanager` (the Prometheus Alertmanager webhook-receiver
  payload) — `json`/`alertmanager` also ignore a custom `template`. `type:
  slack`/`type: mattermost` always send `attachments` regardless of this field
- `secret` (optional) - HMAC signing secret (env-interpolatable); when set,
  every request carries an `X-Detectkit-Signature-256` header, whatever the
  `format`
- `username` (default: `"detectkit"`) - Bot display name
- `icon_url` (default: detectkit brand avatar) - Bot avatar image URL
- `icon_emoji` (optional) - Emoji icon, used instead of an avatar image
- `channel` - Override the receiver's default channel
- `timeout` (default: `10`) - HTTP request timeout
- `extra_headers`: Dict of additional HTTP headers to send

See the [Channels guide → Generic
Webhook](alerting-channels.md#generic-webhook) for the full payload examples
of each format and the HMAC verification snippet, and [→
Rocket.Chat](alerting-channels.md#rocketchat) for the recipe (and caveats) to
route through this same channel type into a Rocket.Chat incoming webhook.
